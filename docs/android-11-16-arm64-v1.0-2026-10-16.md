# Android 11–16 ARM64 — v1.0 (2026-10-16)

O formulário **Novo laboratório** oferece Android 11 (API 30), Android 12 (31), Android 12L (32), Android 13 (33), Android 14 (34), Android 15 (35) e Android 16 (36). Neste worker macOS Apple Silicon, cada versão usa `arm64-v8a`, com escolha entre AOSP userdebug e a imagem oficial Google Play. A imagem selecionada é instalada pelo Android SDK Manager no primeiro uso; a falha de download ou licença preserva o laboratório atual.

O catálogo do SDK Manager neste worker listou os dois pacotes ARM64 para cada API de 30 a 36. **Execução confirmada:** AOSP Android 16 iniciou em um AVD temporário, reportou `ro.build.version.release=16`, `ro.build.version.sdk=36`, `ro.product.cpu.abi=arm64-v8a`, boot concluído e ADB root ativo. O AVD temporário foi removido após o teste. O laboratório Android 15 principal permaneceu online, com o mesmo ID e Magisk ativo.

**Limites:** esta validação não iniciou as demais versões ou as imagens Google Play. O perfil AOSP oferece ADB root; root para aplicativos depende da ativação temporária do Magisk em **Controles** e da autorização individual de cada app. O perfil Google Play usa outra imagem, sem root. Open GApps não foi instalado nas APIs 31–36: o seletor público oficial do projeto não oferece essas versões.
