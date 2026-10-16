# Aparelhos nativos e perfis independentes — v1.0 — 2026-10-16

Estado: implementação e verificação locais. Sem commit, push ou publicação.

## Fluxo entregue

**Adicionar aparelho** permite Android ou iPhone no mesmo workspace, até quatro
aparelhos no total. Android oferece herdar perfil, AOSP com root ou Google Play
sem root. A escolha do adicional não muda o principal. São AVDs/data separados;
não há cópia de contas, apps ou certificados. O perfil é conferido no aparelho
após o boot, não inferido somente do nome da imagem.

Android usa o Android Emulator oficial do SDK, avdmanager, QEMU/HVF neste Mac e
ADB. iOS usa CoreSimulator/simctl do Xcode instalado no Mac. REA não cria runtime.
Este caminho iOS continua exigindo worker Mac; não foi validado no Windows.

Cada iPhone adicional tem UDID, diretório de dados, vídeo e input próprios. Criar
um adicional não altera o current.json do iOS principal. Fechar/reiniciar o
servidor não recria aparelhos nem apaga os registros. Excluir/limpar um Simulator
ou perder o worker pode invalidar sua identidade. UDID de Simulator não equivale
ao identificador de um iPhone físico para cadastro/provisionamento do cliente.
Instalação no Simulator exige build .app de Simulator; IPA físico não é esse build.

## Catálogo iOS

Instalados observados: iOS 26.0 e 27.0. O gerenciador mostra versões instaladas,
oferecidas pelo Xcode e históricas sem prometer que todas executam neste Mac.
Os downloads oferecidos foram conferidos na tela Components do Xcode 27.1.
O catálogo de versões para download é uma fotografia de 2026-10-16; deve ser
reconciliado com o Xcode em futuras atualizações.

A matriz oficial do Xcode 27.1 inicia o suporte de Simulator em iOS 17. Versões
15/16 indicam necessidade de worker compatível; anteriores são históricas com
execução não validada. Números de releases que não existem não são inventados.
Um download só muda para instalado após confirmação pelo simctl.

Neste worker faltou armazenamento para baixar runtimes adicionais. A interface
mostra espaço disponível e reserva exigida; nenhum runtime foi baixado, nenhuma
licença aceita e nenhum dado removido para liberar espaço. O fluxo de download
foi testado por contrato, não validado com um download completo real.

## Evidência real

Mac Apple Silicon, Xcode 27.1 (27A9275). Três aparelhos no mesmo canvas:

- Principal emulator-5556: API 35 Google Play, user, ro.debuggable=0, root ausente.
- Adicional emulator-5560: API 35 AOSP, userdebug, ro.debuggable=1, root disponível.
- iPhone adicional: iOS 26.0, iPhone 17 Pro, UDID 9E7BD1CD-D233-404A-AC94-BF984C052A66.

Toque no iPhone abriu Ajustes e Home no Android adicional retornou ao launcher.
O principal não foi usado para interagir com o aplicativo de terceiro instalado.
Após reiniciar o worker, os três reapareceram sem criação de novo AVD/UDID.

As três molduras apresentaram o mesmo y=332.921875 e altura=572 CSS px; canvas
com y=338.921875 e altura=560, bordas de 6 px. A largura segue o aspecto real
do frame: Android 648×1440 e iOS 604×1312. Artefato visual:
`artifacts/validation/native-mixed-devices-v1-2026-10-16.png`.

MCP stdio: inventário, captura, criação Android/iOS e start/stop dos adicionais;
também inspeções estáticas explícitas do APK principal e contexto Companion.
Nenhum cliente de agente externo foi configurado automaticamente.

Fontes: https://developer.android.com/studio/run/managing-avds,
https://developer.apple.com/xcode/system-requirements,
https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components.

Com Reverse aberto, Ajustar selecionou 81% e o canvas rolável terminou em
x=953, antes da barra de controles em x=959, sem sobreposição.
