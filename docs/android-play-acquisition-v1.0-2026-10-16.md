# Obtenção de apps Android pela loja — v1.0 — 2026-10-16

O fluxo anterior dependia de APK local ou de preparar o perfil Google Play
separadamente. Um AOSP funcionando não dava acesso à loja. A criação Android
agora oferece Google Play por padrão e aceita Package ID ou link oficial.

`new-play-lab` valida entrada/API antes de preparar a imagem oficial sem root,
criar um lab independente e abrir a loja. Não busca APK em mirrors, não aceita
licenças automaticamente e não coleta credenciais Google no formulário.
O SDK já precisa estar presente no worker. Falha de preparação conserva o lab
atual. Falha da loja após criar o Android devolve a identidade do lab existente
para retomada, sem incentivar nova criação pelo mesmo formulário.

Validação local: macOS Apple Silicon, Android 15/API 35 arm64, imagem oficial
Google Play. Criação pela UI abriu a loja no lab
`huntmob_lab_6002f5010c4047ee9e35ce376fdee154`; toque em Sign in abriu o formulário
Google. Build user, debuggable=0 e root indisponível foram observados. O lab
anterior `huntmob_lab_54568bef4cc84ddc8d84a445546f47c5` permaneceu salvo.

52 testes direcionados passaram: Play Store/operação composta 9, sessões 17,
servidor UI 20, parser de link/sessão cliente 6. Sintaxe JS e diff sem erros.
Evidências: `artifacts/validation/android-google-play-v1-2026-10-16.{json,png}`.

Limites: nenhum login, instalação de app de terceiro ou teste contra programa
de bug bounty foi realizado. A disponibilidade do app nesse emulador continua
pendente de validação após login manual. Windows nativo não foi testado nesta
etapa. Esta mudança não acrescenta execução de IPA no iOS ou no Windows.

Fonte do perfil oficial:
https://developer.android.com/studio/run/managing-avds
