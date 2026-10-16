# HuntMob — auditoria funcional v1

Data: 14/10/2026. Alterações locais; sem commit, push ou publicação. Worker macOS, Android 15/API 35 ARM64 com root, Frida 17.23.3. Esta auditoria verifica o produto com um app de treino autorizado; não é um pentest de aplicativos de clientes.

## Resultado verificado

Foi criado um Android separado, instalado e aberto `com.android.insecurebankv2`, SHA256 `b18af2a0e44d7634bbcdf93664d9c78a2695e050393fcfbb5e8b91f902d194a4`. O lab de teste é `huntmob_lab_08ae0aaafa054dfdb4651f1135ad8c72`. Ao terminar, foi retomado `huntmob_lab_9f5013f2f5a141ff8df177e05e6ddc37`, com captura nativa restaurada e suas 500 requisições anteriores preservadas. Nenhum AVD existente foi apagado. O lab de teste permanece salvo e desligado.

| Fluxo | Estado | Evidência e limite |
|---|---|---|
| Novo Android por APK | Confirmado | Upload HTTP, criação de AVD limpo, boot, perfil root verificado, instalação e abertura reais. |
| Selecionar app instalado | Confirmado | Novo endpoint extrai o APK instalado e calcula SHA256; validado no device. Vinculação de lab vazio e recusa de outro alvo também cobertas por testes. |
| Tela, toque e reconexão | Confirmado | Tela H.264 no navegador, entrada enviada ao guest e mudança visível de estado. Rotação provocava EncodingError; após correção, configuração nova chegou ao decoder e H.264 continuou ativo. Recuperação automática de outra interrupção também observada. Não foi feito benchmark de jogos ou redes remotas. |
| Reverse e arquivo | Parcial utilizável | 6.660 arquivos; LoginActivity.java aberto no painel. Dois erros Java, 33 arquivos com trechos para revisão, bytecode disponível. Não equivale a Java completamente reconstruído. |
| Frida Android com root | Confirmado | Seis observadores carregados; job `dyn_dc938de147714af8b7e7648df09cff61`; 40 eventos e 22 chamadas. Um hook ausente. |
| Proxy e login real | Confirmado no app de treino | POST `/login` via `10.0.2.2:8888`, HTTP 200, 8 ms observados. Dados fictícios, usuário inexistente; nenhuma autenticação de cliente foi executada. |
| Send | Confirmado para loopback | Reenvio manual no painel, HTTP 200, 2 ms observados. Nesta versão, reenvio só aceita destinos loopback capturados. |
| Limpar captura | Confirmado | Lista do lab de teste voltou a zero; registros do lab original permaneceram intactos. Limpeza usa marcador e conserva snapshot no disco. |
| Porta do Proxy ocupada | Confirmado | Listener temporário na porta 18086 foi recusado sem configurar o device. Processo HuntMob existente na 8080 identificado pelo comando completo e receipt privado. Burp externo não é anunciado como captura nativa. |
| DAST e relatório | Confirmado como análise de evidências | JSON e HTML gerados: 40 eventos, 1 request e 1 candidato para revisão. Duas áreas observadas; quatro sem chamadas. Não executa automaticamente testes de lógica, IDOR, sessão ou fuzzing. |
| Evidência e exportação | Confirmado | Screenshot salvo; exportação ZIP de 347.738 bytes passou pela verificação de integridade do ZIP. Segunda captura após reinício do servidor foi salva uma única vez. |
| GPS, bateria, sensores, rede e rotação | Comandos/readback confirmados | GPS em 0/0 enviado; bateria 73 e reset; aceleração 0/0/9,81; rádios offline/Wi-Fi; latência LTE/normal; rotação e reset. Isso não comprova que todo app consuma os valores. Ver arquivo de medições. |
| Engagement do cadastro | Corrigido, testes passaram | Campo agora chega à API, é validado, persistido e exibido; preservado na criação do perfil root/stock correspondente. Não foi criado um segundo lab real apenas para repetir este campo. |
| Recuperação após reinício do servidor | Confirmado | Página aberta renovou CSRF após rejeição explicitamente anterior à execução; a captura resultante aumentou de 1 para 2, sem duplicação. Falhas de rede com execução incerta não são repetidas. |

## Bugs corrigidos nesta passagem

- Serial ADB podia ser tratado como o lab atual sem confirmar o nome do AVD. Status, desligamento e exclusão agora exigem identidade adequada; AVD anexado e offline é preservado.
- Retomar um lab sem a imagem necessária podia encerrar o atual primeiro. Os pré-requisitos são verificados antes de interromper a sessão.
- App escolhido após instalação manual/Play Store não recebia vínculo persistente de pacote e hash. A seleção agora valida o APK; outro app exige lab próprio.
- O campo Engagement era solicitado e descartado. Agora é salvo nos labs Android/iOS e mostrado na UI sem indicar aprovação independente do escopo.
- Página sobrevivente a reinício falhava com CSRF antigo; erro HTML era tratado como JSON. Renovação limitada e mensagens de erro adequadas foram adicionadas.
- Interrupção de vídeo durante troca recusada podia deixar tela parada. Estado de conexão agora permite reinício do stream.
- Após rotação, espectadores existentes não recebiam a nova configuração H.264. O relay agora reenvia geometria e SPS quando mudam; há recuperação limitada para interrupções adicionais.
- Erro temporário do Proxy permanecia na tela por causa do cache de renderização. O cache é invalidado após falha.
- Resposta de captura pendente não atualizava o detalhe depois de concluída. Atualiza a resposta sem sobrescrever o request editado nem o resultado de Send.
- Qualquer listener na porta podia ser anunciado como captura nativa. Agora há identificação do processo/argv; listener externo recebe estado próprio.
- SHA256 já calculado era mostrado como pendente antes da decompilação. A seleção mostra o hash vinculado. Sessão Frida histórica recebe indicação explícita de última sessão.
- Parâmetros inválidos ou timeout em ações do device podiam fechar a conexão sem resposta JSON. Agora retornam erro estruturado e não instruem repetição automática incerta.

## O que ainda precisa de implementação ou validação

| Área | Situação atual | Próxima validação necessária |
|---|---|---|
| Emulador iOS próprio | Bloqueado; readiness consultada continua `blocked`. Teste persistente anterior encontrou plaintext no armazenamento ANS/NVMe. | Criptografia de armazenamento real validada, boot normal com interface e execução de IPA. Simulator não substitui esse marco. |
| iOS/IPA de iPhone | Não disponível neste runtime | Apple Simulator executa builds `.app.zip` feitos para Simulator. IPA físico não vira build de Simulator. |
| UDID iOS | UUID do Simulator, confirmado pela API atual | Não comprovado para provisioning Apple ou liberação Claro. Não apresentar como UDID de iPhone físico. |
| Jailbreak/Frida iOS | Sem jailbreak; Frida Simulator experimental permanece sem attach validado nas versões usadas | Runtime compatível e attach real, sem anunciar funcionamento antecipado. |
| Proxy iOS geral/HTTPS | Integração depende do app/rota; fixture opta pela configuração de proxy. Trust TLS não está configurado | Captura de app autorizado real e fluxo HTTPS com CA corretamente confiada. Não é interceptação universal. |
| iPhones/versões antigos | Modelos aparecem no catálogo, mas iOS 11–18 não estão instalados | Runtime compatível com modelo, host e Xcode; instalação e boot reais. |
| Play Store | Abertura foi validada anteriormente no perfil oficial sem root; não repetida nesta auditoria | Login manual pelo usuário e download autorizado. App pode não ser compatível/oferecido na loja. |
| Frida sem root | Exige build de teste com Gadget; sem app desse tipo validado | Build autorizado e conexão real; não há patch automático do APK. |
| Windows/Linux | ZIPs do viewer disponíveis; execução e worker completos não validados nesses sistemas | Executar binários, confirmar arquitetura/imagem Android, onboarding, input e captura nesses hosts. |
| iPad/Tailscale | Serve autorizado e gateway local testado anteriormente | Jornada real a partir de outro aparelho/rede: TLS, toque, teclado, reconexão e desempenho. |
| Câmera/biometria | Fixture de webcam no navegador não injeta câmera arbitrária no app; controles dependem do runtime | Exercitar APIs reais de câmera/biometria no app autorizado e confirmar comportamento do app. |
| Retomada com falha tardia de boot | Pré-requisitos preservam o lab anterior; falha depois da troca pode deixar o novo lab selecionado e desligado | Restauração transacional e validação de falhas de boot; o usuário ainda pode retomar o lab salvo. |

## Apoio do REA no Genymotion

Inspeção estática local, somente leitura, de `/Applications/Genymotion.app` e de `gmtool`. O device Genymotion “Lab Pentest” foi preservado desligado. Não houve alteração de código, licença, instalação ou dados do Genymotion.

- REA artifact graph: `ev_022e8c6a6d73ecf8cd75c19077e482fd5ae25cef0c43d6e53adf1e25cfec6cad`; inspection `ai_25f2fe9f70f620d19897140a5ce34ad8c956657756139911c25f6e13c6df959d`.
- Mach-O/gmtool: `ev_e843c527b87c4e90dce7babad94d2bbd69e42c69040a150cad049357c1682d1b`; arquitetura x86_64.
- Bundle SHA256: `cbc586d5e88acc66d5ccef63287f5d97d20dcdc089e872622e2e993c46424ae6`.

Esses resultados identificam artefatos e estrutura; não medem desempenho do Genymotion nem comprovam um adapter de execução HuntMob. Foram usados como apoio de diagnóstico, mantendo runtime e evidência do HuntMob independentes.

## Evidências

- [Relatório DAST JSON](measurements/flow-audit-report-2026-10-14.json)
- [Relatório DAST HTML](measurements/flow-audit-report-2026-10-14.html)
- [Tela com resultados DAST](measurements/flow-audit-dast-2026-10-14.png)
- [Comandos e readbacks Android](measurements/flow-audit-controls-2026-10-14.json)

Validação automatizada final: 233 testes Python e 10 testes Node de sessão, captura e vídeo passaram; sintaxe JavaScript e `git diff --check`. Os testes não substituem as observações reais identificadas na matriz.
