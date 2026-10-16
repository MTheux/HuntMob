# iOS worker e interação Android — v1

2026-10-13 · validação local macOS/Apple Silicon · sem commit/push ou release publicada.

## Resultado entregue

O perfil **HuntMob iOS Lab** usa um Apple Simulator real, separado dos AVDs Android. Xcode 27 e o runtime iOS 27.0 (24A434) foram verificados e o runtime oficial instalado. O Simulator criado para o projeto é identificado pelo registro privado em `~/.huntmob/ios/current.json`; inventário e ações recusam adoção de um device com nome diferente de HuntMob iOS.

Fluxo: escolher iOS → iniciar → instalar `.app.zip` para Simulator (autorização explícita no formulário) → abrir e interagir → capturar evidência. Também há uma fixture própria, com código em `components/ios-lab/LabApp.swift`, para validar toque, contador e rolagem. A fixture não é um resultado de pentest.

O backend verifica o Bundle ID, o executável e a plataforma Mach-O `IOSSIMULATOR` antes de instalar. ZIPs com traversal, symlinks, múltiplos apps principais ou extração excessiva são recusados. O SHA256 exibido no iOS é do executável, identificado como **Binário SHA256**, e não de todo o bundle.

Input usa uma conexão gRPC persistente com idb-companion por socket Unix privado, sem publicar porta TCP, sem registrar texto digitado. Cliques e gestos usam coordenadas em pontos do Simulator. Vídeo iOS compartilhado usa captura MJPEG do bridge, limitada a 30 fps; não chama screenshot em loop. Screenshot de evidência usa PNG privado temporário e hash verificável. Xcode 27 não escreveu em stdout ao receber `-` como destino; o caminho temporário resolve esse comportamento observado.

Dependências locais utilizadas: idb-companion 1.7.0 do tap oficial Meta e fb-idb 1.1.7 em `components/idb-client/.venv`, com protobuf 3.20.3. O runtime Apple exige macOS e Xcode; o cliente/companion iOS ainda não foram empacotados e validados em uma release portátil. Builds de device físico, jailbreak, Frida iOS, DAST iOS e reprodução integral do hardware não são anunciados como disponíveis.

## Android: vídeo e controle

O caminho preferencial agora é MediaCodec → servidor scrcpy 5.0.1 → relay H.264 → WebCodecs → canvas. Não decodifica e recodifica para JPEG no host. O componente scrcpy, sua licença Apache-2.0 e recibo ficam em `components/scrcpy`; SHA256 do asset oficial validado: `764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536`. O builder de release inclui esse componente em `_video`.

O protocolo é fixado à versão 5.0.1. Um único produtor atende viewers com GOP e fila limitados. O decoder pula deltas ao acumular atraso e retoma no próximo keyframe; quadros VideoFrame são fechados depois de renderizar. Há fallback MJPEG para browser/codec indisponível. Heartbeat detecta viewers desconectados também em tela estática.

Eventos down/move/up são enviados enquanto o mouse é arrastado, com coalescência dos moves e ordem preservada. Cancelamento libera o toque, inclusive quando o ponteiro termina fora da tela. O controle recebe somente ações fixas, coordenadas finitas e teclas permitidas, com CSRF e os gates existentes. O relay verifica o AVD e a sessão vinculada ao laboratório. Mudanças de lab reiniciam o relay. Backspace, Enter, Tab e setas têm códigos explícitos.

O console de debug do AVD atual com root foi parado com `su 0 stop console`, após a mensagem de performance do Android e confirmação de `init.svc.console=running`. Leitura confirmou `stopped`. Isso foi uma alteração de runtime nesta sessão, sem ganho de performance atribuído a ela e sem persistência para futuros boots. Reversão: `adb -s emulator-5556 shell su 0 start console`. Não alterou a disponibilidade de ADB/SU do perfil.

## Evidência e limites da medição

- Android anterior: média inicial de ~26 fps incluía períodos parados. Uma comparação posterior mostrou intervalos de movimento de ~16,6 ms no caminho antigo e ~16,7 ms no novo. **Não é prova de aumento de 26 para 60 fps**; ambos chegam a 60 durante movimento no cenário avaliado.
- Controle HTTP local, 10 pares: mediana ~144,9 ms para tap pelo caminho ADB, ~3,0 ms para down+up pelo canal direto. Métrica é reconhecimento do comando, **não input-to-photon**. Não mede toda a latência da renderização nem um jogo pesado.
- Primeiros frames da comparação: ~334,7 ms no MJPEG e ~476,1 ms no H.264 com preparação do servidor. O objetivo principal é reduzir reprocessamento e resposta de interação durante a sessão, não prometer menor cold start.
- UI Android: toque abriu teclado; arraste pela tela do HuntMob abriu a cortina de notificações usando eventos contínuos.
- UI iOS: toque pelo navegador incrementou contador de 5 para 6; ZIP selecionado pelo picker nativo instalou e abriu; evidência PNG foi registrada na UI. O seletor automatizado da extensão estava sem acesso a arquivos locais, então foi usado o picker nativo sem alterar permissões da extensão.
- 148 testes e verificações de sintaxe JS/diff passaram. Windows/Linux do novo canal, device iOS físico, múltiplos apps iOS e release instalada limpa não foram validados neste trabalho.

Artefatos: `artifacts/validation/input-latency-v1-2026-10-13.json`, `stream-direct-v1-2026-10-13.json`, `stream-baseline-motion-v1-2026-10-13.json`, `ios-runtime-v1-2026-10-13.json` e `android-console-v1-2026-10-13.json`.

Fontes técnicas:
- https://github.com/Genymobile/scrcpy/blob/v5.0.1/doc/develop.md
- https://github.com/Genymobile/scrcpy/releases/tag/v5.0.1
- https://github.com/facebook/idb
- https://developer.apple.com/documentation/Xcode/downloading-and-installing-additional-xcode-components

## Medição e ajuste — 14/10/2026

Perfil anterior: MJPEG 30 fps, escala .5 e qualidade .8. Amostra da API
com Simulator ligado: entrega 30.0 fps, primeiro frame 199 ms, 15.91 MB
em 5.03 s. Nenhum FPS de renderização do navegador foi medido.

Perfil aplicado: MJPEG 60 fps, escala .5 (mesma resolução) e qualidade .55.
Amostra direta do worker: 59.8 fps, primeiro frame 128 ms. Depois do restart
apenas da UI, API: 60.2 fps, primeiro frame 631 ms (sessão fria), 12.66 MB
em 5.01 s. O ajuste aumenta a entrega e reduz tráfego nesta amostra; não
comprova latência ponta a ponta nem fluidez em todos os apps.
Receipt local: artifacts/validation/ios-video-delivery-v1-2026-10-14.json.

Quatro swipes na fixture própria com canal persistente: acknowledgements
809 ms (inicialização), 372, 383 e 373 ms; incluem gesto fixo de 250 ms.
A UI envia o swipe somente após pointerup. Input contínuo iOS ainda falta.
Android não teve seus parâmetros de vídeo ou gestos alterados.

Windows: runtime Apple Simulator rejeita plataformas não-Darwin no código;
execução Windows completa e despacho iOS remoto não foram validados.
README foi corrigido para distinguir arquitetura prevista de implementação.
O identificador atual vem de simctl create, é UUID estável do Simulator;
não há prova de aceitação para provisioning físico ou whitelist da Claro.
É necessário identificar se a liberação é provisioning ou cadastro backend.


## Toque contínuo e identidade — 15/10/2026

O controle anterior sintetizava um swipe de 250 ms somente após pointerup.
Agora down/move/up seguem pelo mesmo stream HID, sem esperar o fim do arraste.
Movimentos pendentes são coalescidos; eventos de início/fim preservam a ordem.
O servidor verifica o UUID selecionado antes de encaminhar o toque. Cancelamento
no navegador e timeout de inatividade de 5 s liberam o contato. A captura MJPEG
mantém os parâmetros anteriores; a amostra anterior a esta alteração entregou
60,0 fps em 5,0 s. Isso não mede FPS de renderização nem latência ponta a ponta.

Validação no Edge pela tela do HuntMob: contador da fixture própria 0→1 após
toque e lista rolada até os itens 15–30 após arraste. O servidor respondeu aos
eventos de input com HTTP 200. Essa fixture não representa execução de IPA.

A mesma identidade do CoreSimulator foi observada após reiniciar o processo HTTP
na porta 8090 e após Desligar e preservar → Retomar Simulator salvo. A fixture
instalada foi reaberta. Não foi testado reiniciar o macOS, migração ou recuperação
de backup. O registro persiste em ~/.huntmob/ios/current.json. Um Simulator salvo
ausente agora interrompe a retomada; não é recriado silenciosamente com outro UUID.
Novo lab continua criando outra instância. O formulário não exige Engagement.

UUID do Simulator não é UDID físico, IDFV nem prova de liberação pelo backend.
O identificador efetivamente usado pelo app e o aceite do cliente permanecem
pendentes. IPA físico não se torna compatível com o Simulator por este ajuste.

Passaram 45 testes Python e 9 testes Node direcionados (54 ao todo), verificação
de sintaxe JS/Python e git diff --check. Trabalho local, sem commit/push/release.
Recibo: artifacts/validation/ios-session-resume-v1-2026-10-15.json.


## Apresentação sem fila — referência 2007.mobile — 15/10/2026

O usuário forneceu https://2007.mobile/ como referência de resposta. O app.js
público usa Worker, transferência de frames de 320×480 e desenho no canvas,
com pointer events enviados ao Worker. A página abriu, mas o guest permaneceu
preto nesta sessão; não foi possível fazer uma comparação interativa de fluidez.
Não se afirma equivalência de desempenho nem compatibilidade de runtimes.

O HuntMob agora usa fetch do MJPEG e createImageBitmap para desenhar o iOS no
canvas. Mantém uma decodificação e somente um frame pendente mais recente;
fecha bitmaps inclusive após abort e descarta frames pendentes superados.
O parser limita cabeçalhos, frames e buffer e verifica formato JPEG. O browser
sem createImageBitmap conserva o caminho img. O transporte do worker continua
MJPEG; não é uma migração para H.264/WebRTC nem execução de iOS no navegador.

Contadores observados no Edge: 650 frames desenhados, 669 recebidos e 12
pendentes descartados em 11,138 s: 58,4 desenhos/s. A lista da fixture rolou
até os itens 27–40. Contar drawImage não mede apresentação no monitor,
input-to-photon, resposta remota ou fluidez de aplicativos de terceiros.

Também foi corrigida a recuperação do vídeo após falha de startup/retomada:
até cinco tentativas (500/1000/2000/4000/5000 ms), canceladas ao mudar a
plataforma, geração ou estado do device. O endpoint somente leitura
/api/ios/video-status expõe estado, contagem, tamanho do último frame e erro.

Passaram 45 testes Python e 16 Node (61 direcionados), sintaxe JS e diff check.
Receipts e screenshot: artifacts/validation/ios-latest-frame-v1-2026-10-15.*.
Alterações locais, sem commit, push ou release. O mesmo Simulator foi mantido.
