# Controle Root e modelos iPhone antigos — v1.0 — 2026-10-16

Implementação local; sem commit, push ou publicação.

O ícone Root foi incluído em Ferramentas → Dispositivo. No Android principal, mostra o perfil atual e abre a troca para o perfil oposto. A tela explica antes da ação que os perfis usam Androids separados e têm apps, contas e dados próprios. Reutiliza o fluxo já existente de preservação de APK base/splits, retomada de perfil salvo e verificação de root. Não promete ativar root dentro de uma imagem Google Play, nem transformar AOSP em uma imagem release ao executar adb unroot. Nos Androids adicionais, o controle informa que o perfil é definido na criação; a alternância existente é do principal.

A confirmação carrega o ID do lab de origem. Frontend e backend recusam o pedido se o lab selecionado tiver mudado. No serviço local real, um pedido com ID de origem divergente retornou HTTP 409 e manteve o lab selecionado. Recibo: `artifacts/validation/root-shortcut-scope-v1-2026-10-16.json`.

No Apple Simulator, o ícone muda para Jailbreak, fica desabilitado e exibe a razão. Nenhum exploit, jailbreak, download de Sileo ou modificação do iOS foi executado. O backend continua com `jailbreak_supported: false`. Sileo é um gerenciador de pacotes para dispositivos já preparados com jailbreak; não é o próprio jailbreak.

O catálogo local CoreSimulator contém iPhone 7, 7 Plus, 8, 8 Plus e X. A criação do lab e a adição de iPhone agora exibem uma seção de compatibilidade para esses modelos, incluindo a faixa do runtime e sua disponibilidade real. As opções do seletor também mostram a faixa exigida. Dados observados neste worker:

| Modelo | Faixa no catálogo local | Runtime compatível instalado |
|---|---|---|
| iPhone 7 / 7 Plus | iOS 10–15 | Nenhum |
| iPhone 8 / 8 Plus / X | iOS 11–16 | Nenhum |

O worker está com macOS 27.0.1, Xcode 27.1 build 27A9275, e runtimes iOS 26.0 e 27.0 arm64. O Xcode 27 requer Simulator iOS 17 ou posterior. A existência do tipo de dispositivo no catálogo não comprova que ele pode iniciar. Para esses modelos antigos, falta um worker com conjunto macOS/Xcode/runtime compatível. Não foram baixados Xcodes ou runtimes incompatíveis, nem criado um aparelho apenas com nome antigo sobre um iOS novo.

Fontes primárias consultadas:

- Android: https://developer.android.com/studio/run/managing-avds — imagens Google Play assinadas como release não oferecem root.
- Apple: https://developer.apple.com/xcode/system-requirements — compatibilidade de Xcode, macOS e Simulator.
- Sileo: https://getsileo.app/ — gerenciador de pacotes para dispositivos com jailbreak.
- Inventário local: `xcrun simctl list devicetypes --json`, `xcrun simctl list runtimes --json`, `xcodebuild -version`.

Verificação: 607 testes Python e 28 JavaScript passaram. Incluem recusa de troca com origem desatualizada e limites de compatibilidade iOS 15/16/17/26. Interface verificada abrindo o atalho e selecionando iPhone 7 com iOS 26; criação corretamente desabilitada. A troca real do perfil do app atual não foi executada nesta validação. Os dispositivos e seus dados foram preservados.
