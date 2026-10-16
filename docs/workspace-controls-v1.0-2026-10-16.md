# Workspace e controles — v1.0 — 2026-10-16

Implementação local no HuntMob. Nenhum commit, push ou publicação foi realizado nesta tarefa.

## Comportamento

- Ferramentas → Dispositivo reúne biometria, câmera, GPS, rede, bateria, rotação, sensores, navegação, Screenshot, Proxy e Frida. O seletor identifica o aparelho destinatário. Ações de conexão do principal ficam em uma seção recolhível. Reverse, captura de evidência, Proxy e Frida continuam vinculados ao principal, com essa indicação visível.
- O cabeçalho não mostra mais os placeholders LAB / Lab local / Sessão local. Os metadados existentes dos laboratórios são preservados.
- Os quadros podem ser arrastados pelo cabeçalho; a tela continua recebendo gestos do dispositivo. Checkbox, modificadores no cabeçalho e seleção por retângulo permitem selecionar vários. As setas no cabeçalho ajustam a posição; Enter abre a edição do nome.
- Nome e posição são metadados privados do par workspace/aparelho. Alterar o nome não altera AVD, porta ADB, UDID, pacote ou dados. Arquivos são gravados atomicamente com modo 0600.
- Desligar selecionados valida todos os IDs antes da primeira ação, confirma o estado offline por aparelho e remove os quadros desligados. Falhas são individuais. Os dados e a identidade permanecem salvos no worker. Conforme ajuste solicitado pelo usuário, um aparelho desligado/removido do canvas também sai da lista “Neste laboratório”; o registro offline não é exibido nessa seção. O limite é quatro aparelhos ativos por workspace.
- O caso de APKs split na troca de perfil preserva o conjunto retornado por pm path antes de desligar o perfil atual, compara o SHA256 do base com o alvo selecionado e registra hashes dos splits. Instala os arquivos originais com install-multiple; não modifica assinatura nem replica contas/dados. Em falha de instalação, tenta retomar o perfil anterior. A compatibilidade de API/ABI e a inicialização do app continuam dependendo do app e do runtime.

## Biometria: referência e implementação

Referências primárias: https://docs.genymotion.com/features/biometrics/ e https://developer.android.com/studio/run/emulator-console#fingerprint-simulation-and-validation .

REA 6.0.0 com Ghidra 12.1.4 analisou o Genymotion instalado, sem modificar seus executáveis:

- Inventário do bundle: `genymotion-rea-inventory-v1-2026-10-16.json`.
- A primeira busca no executável player não encontrou strings biométricas; não foi tratada como ausência da funcionalidade.
- Em libcom.1.0.0.dylib, a busca identificou BiometricsModule, os métodos publishRecognized/Unrecognized/Dirty/Partial/Insufficient/TooFast e autoAnswer. Evidence ID: `ev_231c6477cc4e334da54ffe15d2df7b33867add2cc5a48e0fcd2298a91b1be072`.
- A função processScan em 0x4380 distingue mensagens start, success e error. Evidence ID: `ev_c888f44c8a12387595220348a352be8daf1f4d4732b6cab7d03bfc9dd05f80f2`. Essa é uma observação estática; não comprova uso do widget num guest.
- A interface nativa instalada mostrou Genymotion 3.10.0 e somente um aparelho API 30. A referência oficial exige Android 13+ para o widget biométrico; o widget não foi validado nessa instalação. Nenhuma licença foi alterada.

HuntMob usa o console nativo do Android Emulator, não o protocolo proprietário do Genymotion. Antes de permitir um toque, verifica o sensor anunciado e a operação atual de dumpsys fingerprint. Histórico de autenticação não conta como pedido pendente. Envia finger touch / finger remove ao aparelho cuja propriedade foi verificada e relata envio, não aprovação pelo app. O ID é sintético. Os cenários de qualidade não oferecidos pelo console ficam desabilitados com motivo visível. Repetição automática só no cadastro, com a janela aberta, até 20 toques; é cancelada ao fechar ou mudar de aparelho.

## Verificação

- No navegador real: quatro aparelhos inicialmente online; arraste do Android adicional, seleção por retângulo exclusivamente dos dois Androids extras, nome “Lab pentest” no iPhone, posição e alias mantidos após reload.
- Desligamento em lote dos dois Androids adicionais confirmado: quadros removidos; principal e iPhone permaneceram online. Seus registros e identidades foram preservados.
- Retomada bloqueada pelo Android Emulator: disco do Mac com aproximadamente 1 GiB livre. O erro foi reproduzido e a interface passou a exibir motivo persistente na lateral. Nenhum dado do usuário foi removido para liberar espaço. Depois, uma leitura do host mostrou ~5,5 GB livres e ambos os Androids retomaram pela lateral, com os mesmos IDs/portas, nomes e posições. Os quatro aparelhos terminaram online. Root AOSP userdebug/debuggable=1 e Google Play stock user/debuggable=0 foram verificados novamente após o boot.
- Biometria no Android real em execução: sensor disponível, zero digitais cadastradas e nenhum pedido pendente; toques e repetição corretamente desabilitados. Abertura do controle iOS encaminhada ao iPhone adicional selecionado, sem enviar evento biométrico.
- Responsividade inspecionada em 390×844, 900×900 e tamanho original 2254×849; override restaurado.
- Testes automatizados cobrem escopo e validação integral do lote, persistência, limites de atividade, espera offline, pedido biométrico atual versus histórico, touch/release, conjunto split preservado, falha de pull, instalação e retomada do perfil anterior.

Resultado final: 605 testes Python e 26 testes JavaScript passaram; verificação de sintaxe JavaScript e git diff --check sem erros. Recibo: `artifacts/validation/workspace-controls-validation-v1-2026-10-16.json`.

## Limites atuais

A autenticação biométrica completa no app exige cadastrar uma digital no Android e abrir seu prompt. Isso não foi concluído nesta tarefa. A troca de perfil de um aplicativo de terceiro com seu conjunto real de splits também não foi executada: o principal foi preservado durante a implementação. A falha de disco observada bloqueou inicialmente a retomada, mas os dois aparelhos adicionais foram retomados após o espaço livre aumentar no host. Os testes de instalação usam comandos e arquivos controlados; não são uma instalação real desse app. Não houve teste de segurança contra os backends dos aplicativos.

Também verificada a troca de visualização Android → iOS individual e o retorno ao workspace, preservando os aparelhos ativos. A transição remove imediatamente as telas anteriores para não oferecer entrada sobre um frame de outra plataforma.

Capturas e evidências ficam em `artifacts/validation/`.

## Ajuste da lista após remoção — 2026-10-16

“Neste laboratório” passou a usar o mesmo filtro do canvas para aparelhos adicionais: estado offline remove a linha do DOM. A busca e as atualizações de nome não recriam essas linhas. Aparelhos iniciando continuam visíveis. Os arquivos e dados dos dispositivos não são apagados. Verificação com dois aparelhos online e dois Androids offline preservados no inventário do worker.
