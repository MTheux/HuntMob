# Android: arrastar arquivos e validação do laboratório — v1.0 (2026-10-16)

## Uso

Arraste **um arquivo** do navegador para dentro da tela de um Android ligado. Um APK é instalado e, se houver atividade inicial, aberto **no mesmo AVD**. Imagens, TXT, PDF e outros arquivos vão para `Downloads/HuntMob`; o nome no Android é prefixado com um identificador curto para evitar sobrescrita. O botão **Enviar arquivo** oferece o mesmo fluxo para o Android principal sem depender de drag and drop. O arquivo sai do navegador no Mac, Windows ou Linux e é enviado ao worker que hospeda o emulador; o computador cliente não precisa executar ADB.

O envio exige a sessão da UI, escolha de um aparelho pertencente ao workspace e arquivo de até 512 MB. A API revalida a identidade do aparelho após o upload. Para APK, `aapt` valida o package ID e o ADB confirma instalação e abertura. Um APK sem atividade inicial pode ser instalado sem abrir. Nenhum arquivo enviado é executado no host.

## Validação realizada

| Caminho | Evidência | Resultado |
| --- | --- | --- |
| Upload TXT via HTTP para Android 11 Google Play | API `/api/device/drop` 200; `adb shell cat` conferiu os bytes; arquivo temporário removido | Confirmado |
| APK de laboratório para Android 11 Google Play | API 200, `installed=true`, `launched=true`; `LoginActivity` em primeiro plano; entrada de texto confirmada por UI Automator | Confirmado sem autenticação |
| Desligar e retomar o mesmo laboratório | `stop` retornou `stopped`; `resume` retornou `device`; `pm path` encontrou o APK e boot completo | Confirmado. A primeira tentativa anterior à espera pela liberação da porta retornou 409; o fluxo corrigido passou na API 35 AOSP. |
| Drag and drop no navegador Chromium local | Arquivo TXT sintético solto na tela do Android 15 AOSP; estado “Arquivo no Android”, sem erro JavaScript; imagem do aparelho presente no canvas | Confirmado neste navegador e worker Mac |
| Proxy integrado Android 11 AOSP | Proxy configurado em `10.0.2.2:8080`; GET à API local apareceu com 200; remoção restaurou `:0` | Confirmado para HTTP local |
| Frida e DAST Android 15 AOSP | Frida 17.23.3, sessão running, 18 eventos; relatório de cobertura ao parar; Proxy associado iniciado e removido | Confirmado para o app de laboratório, sem validação de vulnerabilidade |
| Frida Android 11 AOSP | `frida-server` 17.23.3 encerrou no início com assert de signal; conexão retornou `TransportError` | Bloqueado nessa combinação; DAST dependente de Frida não confirmado |
| Boot ARM64 | Android 11 AOSP/Google Play e Android 15 AOSP/Google Play iniciados nesta retomada; Android 16 AOSP iniciou em validação anterior | Parcial: APIs 31–34 e demais perfis não inicializados |

O Android 15 AOSP exibiu ADB root e o DAST executou com ele. A validação anterior de Magisk para **apps** foi feita em outro AVD Android 15 com app descartável e autorização individual; não representa todos os perfis AOSP. Google Play permanece sem root. O catálogo anuncia API 30–36 ARM64, mas neste worker estavam instaladas apenas as imagens 30, 35 e 36. Com cerca de 18 GiB livres, não foram baixadas todas as combinações para este teste.

Não foram usados logins de terceiros ou duas contas autorizadas. O APK de laboratório foi usado para instalação, abertura e observação local. Não houve teste de vulnerabilidade em app de terceiro. O worker local foi iniciado com um venv isolado em `~/.huntmob/worker-venv` contendo as dependências fixadas em `pyproject.toml`.
