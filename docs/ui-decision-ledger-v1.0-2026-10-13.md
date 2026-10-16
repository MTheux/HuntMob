# HuntMob workbench UI decision ledger v1.0 — 2026-10-13

## 2026-10-16 — revisão por modelo local no Reverse

Reference lock: painel Reverse atual, tokens preto/vermelho e hierarquia de
Evidence, Companion e revisão humana. A pesquisa de telas no Refero foi
tentada e retornou `NO_SUBSCRIPTION`; a implementação seguiu a direção já
registrada neste ledger. Nenhum sistema visual novo foi introduzido.

| Decisão | Fonte | Papel | Motivo |
| --- | --- | --- | --- |
| Botão secundário após REA e Companion | Fluxo Reverse existente | Ação explícita | O modelo só recebe Evidence concluída da seleção atual |
| Estado textual com nome do modelo | Contrato de proveniência | Feedback | Conexão local não é avaliação concluída |
| Resultado em “precisa de revisão” | Review existente | Limite de confiança | Texto do modelo não vira finding confirmado |

Validação visual no Edge: o controle apareceu no painel, o modelo local foi
identificado e o botão permaneceu indisponível sem Evidence REA concluída.

## 2026-10-16 — moldura e múltiplos aparelhos no workspace

Reference lock: canvas/moldura atuais fornecidos pelo usuário e workbench
preto/vermelho existente; craft Refero de foco/forms e identificação explícita
de ações. Pesquisa Refero live tentou developer tools/device workspace e
retornou NO_SUBSCRIPTION. Usar a direção existente, sem novo sistema visual.

A moldura segue as dimensões do frame e tem um único espaçamento interno;
Android não recebe a câmera decorativa do iPhone. Celulares adicionais ficam
lado a lado no mesmo phoneCanvas, com serial, estado e controles próprios.
Adicionar cria dados limpos com a versão/perfil do principal, sem parar o
principal nem copiar contas. Cada ação carrega uma identidade explícita.
A integração MCP começa com inventário, captura e gerenciamento dos aparelhos;
não oferece executor de shell ou automação de testes ofensivos.

## 2026-10-16 — obter app pela loja antes da análise

Reference lock: modal Novo laboratório e tokens atuais. Referências: cenário
do usuário sem APK nem loja no AOSP, craft Refero Forms (rótulo do campo e
próximo passo explícitos), documentação oficial Android sobre perfis Google
Play separados de AOSP com root. Android começa com origem Google Play;
APK local e laboratório vazio permanecem no mesmo seletor. O campo aceita
Package ID ou link HTTPS oficial; apenas o ID validado chega ao worker.
Preparação, boot e abertura da loja formam uma operação: falha de preparação
preserva o lab atual; falha da loja conserva o lab criado para retomada.
Abrir Play Store não significa instalar ou validar o app. Conta Google é
informada na loja; não é coletada pelo formulário do HuntMob.

## 2026-10-15 — referência de resposta 2007.mobile

Fonte comportamental fornecida pelo usuário: https://2007.mobile/.
Leitura do app.js público confirmou entrada por pointer events para um Worker e
frames desenhados diretamente no canvas. Preservar no HuntMob o device e os
controles atuais; adaptar somente a política de apresentação: uma decodificação
e um frame pendente mais recente, sem fila de reprodução. Exibir a contagem de
frames desenhados em lugar de anunciar 60 fps a partir da entrega no worker.
O runtime iOS continua no Mac. Não se afirma equivalência com a emulação local
de iPhone OS 1.0 nem suporte adicional a IPA.

## 2026-10-15 — criar laboratório sem identificador de projeto

Reference lock: modal atual Novo laboratório, tokens e controles existentes.
Referências: pedido explícito do usuário para remover Engagement e seção Forms
do craft Refero (rótulos claros e confirmação com alvo clicável único).
Decisão: remover o campo e o envio desse metadado opcional; manter a autorização
explícita para usar o laboratório e testar os aplicativos. O backend já aceita
o identificador vazio. Sem mudança de runtime ou promessa de suporte a IPA.

## 2026-10-15 — toque contínuo e retomada do iOS

Reference lock: canvas e controles existentes; pedido do usuário para melhorar
arraste e preservar a identidade cadastrada. O rótulo Retomar Simulator salvo
distingue retomada de Novo lab. A identidade explica a persistência no Mac,
a criação de outro UUID em Novo lab e a diferença para UDID físico e IDs do
backend. O toque usa um stream HID por gesto, com coalescência dos movimentos,
ordem down/move/up e cancelamento na perda do viewer. Não se promete FPS de
renderização ou aceite pelo cliente a partir do UUID do CoreSimulator.

## Design brief

Designing a mobile pentest workbench for authorized security operators on web.
Goal: run a device and inspect the same app without changing tools or context.
Tone: dense, technical, controlled and unmistakably HuntBox.
Main risk: turning a security lab into an unsafe raw shell or a decorative dashboard.

## Reference lock

- Primary: existing HuntBox/Draxen UI; preserve near-black canvas, Barlow/neutral
  sans hierarchy, JetBrains-like mono metadata and `#E7274A` action red.
- Product structure: Genymotion device inventory and direct device management.
- Workbench structure: IDE file tree, editor and persistent tabs for technical tools.
- Red is reserved for primary action, current selection and security attention.
- No gradients in UI chrome, no soft rounded card grid, no decorative imagery.
- Device display is the visual anchor; reverse engineering remains visible beside it.

## Decision ledger

| Decision | Source | Role | Why |
|---|---|---|---|
| Black/graphite canvas | HuntBox UI | application chrome | brand continuity |
| `#E7274A` | HuntBox tokens | action and selection | keeps semantic discipline |
| Device list at left | Genymotion | runtime navigation | familiar device workflow |
| Device + RE split | user brief and IDE pattern | primary workspace | removes tool switching |
| Mono for hashes/code | developer-tool craft | technical content | improves scanning |
| Webcam consent dialog | privacy/accessibility craft | fixture control | no silent capture |
| Tabs for REA/Frida/Proxy/Evidence | capability contract | context switch | unified but not crowded |

## iOS readiness refinement — 2026-10-14

Direct-build target: the existing workbench screenshot
`artifacts/validation/unified-ios-workbench.png` and tokens above. Live Refero
style research was attempted in two directions but returned no active
subscription. Fallback research used the existing product reference lock
and the bundled Refero copywriting guidance: context, conditions, next step;
facts over adjectives. No new visual system or external assets were added.

| Decision | Source | Role | Why |
|---|---|---|---|
| Native iOS milestones separate from Simulator controls | verified runtime capability contract | profile hierarchy | an online Simulator does not establish a usable virtual iOS provider |
| Amber for blocked boot; green only on observed milestones | existing HuntMob status tokens | status semantics | preparation must not look like a ready runtime |
| Date and protection caveat under native disclosure | Refero copywriting and existing console disclosure | progressive detail | keep the primary state readable and preserve the evidence boundary |
| Installation disabled until online, file and approval | current backend preconditions | action availability | prevent avoidable errors and duplicate concurrent actions |
| IPA shortcut opens Reverse | existing tab navigation and user app-first flow | next action | provide a real supported action while native boot remains blocked |

Validation: native state rendered in Edge, disclosure expanded, authorization
without a file kept installation disabled, and the IPA shortcut opened the
iOS Reverse panel. No virtual iOS availability or IPA installation was
claimed. Backend checks reject malformed/disabled-protection evidence and
never infer a usable runtime from an edited research receipt.

## 14/10/2026 — criação multiplataforma e controles iOS

Referências: workbench atual e screenshot unified-ios-workbench.png; padrões
nativos de seletores e rótulos da biblioteca de craft Refero Design. Refero
live retornou NO_SUBSCRIPTION. Direção mantida: device central, ferramentas
secundárias recolhidas, identidade preta/vermelha existente. Sem redesign global.

Novo lab mantém o modal existente, com plataforma, versão e modelo em sequência.
Perfis Android com/sem root continuam separados; jailbreak iOS aparece como
indisponível, sem alteração fictícia de segurança. Catálogo iOS é do worker,
com modelos incompatíveis desabilitados. Android requer imagem instalada.
Menu DEVICE fica visível no iOS; GPS, indicador de bateria, Sistema/Home e
Screenshot são habilitados no Simulator online. Demais itens informam falta
de capacidade via estado disabled/title; não encaminham comandos Android.

## 2026-10-14 — xtool

Reference lock: current HuntMob Profile panels, existing device picker/approval controls, and official xtool CLI device workflow. Added a physical-USB card within iOS Profile; preserve emulator canvas and runtime state. Explicitly label physical device, separate IPA installation from Simulator ZIP, reset approval on device changes, and require installed Bundle ID after signing. No Apple credentials collected in browser. Render/check absence of device before reporting capability ready.

## 2026-10-14 — remote tablet access

Reference lock: existing HuntMob optional workbench, device canvas, dialog/preset controls. User scenario: iPad away from worker over Tailscale. At <=1100px, expose device drawer and full-height dismissible tools sheet, preserve canvas space; add native-browser keyboard dialog with explicit text send, no per-keystroke secret echo. Tailscale identity model follows official Serve documentation, owner-only gateway on loopback, private HTTPS port, existing local worker/video producer reused. No invented remote device capability.

## 2026-10-14 — desktop viewer and iOS identity

Reference lock: current HuntMob canvas/optional tool sheet, download/status dialogs and Profile panels. User requested a phone-mirroring window and Windows/Mac/Linux download. Added viewer query mode, native isolated window, portable archive downloads with per-platform execution status, and full Simulator identity copy/export. Preserve real runtime limitations. Security boundaries follow official Electron guidance; avoid arbitrary URLs, remote Node access or certificate bypass.

## 2026-10-14 — unclutter workbench and native viewer

Reference lock: established HuntMob dark/red tokens, app-first configuration and optional tool sheet; user's supplied Genymotion behavioral reference defines display-only desktop surface. Removed duplicated/inert rail navigation, widened workbench to 60%, split Frida script library from execution/readback, bounded event console, two-column scripts when space permits. Viewer hides site chrome and exposes only device/control surface. Platform-specific lab source options replace shared Android copy; old device selections explain missing compatible runtime. Downloads gain bounded Range/ETag support rather than claiming smaller binaries or guaranteed network speed.

## 2026-10-14 — validação no aparelho remoto

Refero direct-build target: Viewer dialog already implemented and verified in the workbench; preserve dark/red tokens, optional disclosure, existing buttons and status text. Craft reference: craft-details.md focus/forms; prior viewer download and identity-export flows. Add connection check and JSON export inside a disclosure rather than reducing emulator canvas space. Report transport, ping and visible frame separately from manual touch/keyboard checks. No automatic input into the app, no credentials or full user-agent collected, no claim that local results prove an iPad/Windows journey. Validate rendered dialog and exported JSON in the existing browser.

## 2026-10-16 — perfis independentes, catálogo iOS e REA opcional

Reference lock: canvas e workbench HuntMob existentes, seletores do diálogo de
novo lab, status explícitos do worker e disclosure de evidências; pedido do
usuário para adicionar Android/iPhone sem encerrar o principal. Craft Refero
forms/foco já consultado. Live Refero indisponível por assinatura (duas tentativas);
nenhuma referência live foi inventada. A moldura conserva o aspecto do frame,
6 px uniformes e alinhamento superior comum.

Decisões: seletor de perfil independente (herdar/root/sem root), catálogo iOS
separando instalado/disponível/histórico/incompatível/falta de espaço, nenhum
download automático. Reverse mantém a decompilação e acrescenta operações REA
explícitas e preparo Companion com estado awaiting_agent. Evidência JSON em
disclosure; nenhum relatório de modelo simulado. Pesquisa técnica primária:
matriz Xcode, managing AVDs e repositórios oficiais REA/Companion.

Verificações: Android stock + Android root + iPhone no mesmo canvas, input
independente, identidades preservadas após restart. REA executado no APK de lab
InsecureBank; UI dos providers renderizada; avaliação de agente ainda pendente.

A conferência final com Reverse aberto identificou sobreposição da barra de
controles no terceiro aparelho. O scroll dos aparelhos agora termina antes da
barra; Ajustar calcula o espaço ocupado pelas tiles e limita o zoom ao espaço
disponível, com scroll quando o limite mínimo de zoom ainda não permite caber.

## 2026-10-16 — lateral de aparelhos e labs

Brief: repaginar a lateral existente para identificar os quatro aparelhos do
workspace e distinguir a seleção atual do histórico salvo, preservando o canvas.
Direct build sobre o design system HuntMob e screenshot atual fornecida pelo
usuário; sem mudança de marca. Pesquisa Refero styles dark developer tools
retornou NO_SUBSCRIPTION; fallback explícito para craft-details.md (foco,
formulários, rótulos e alvos clicáveis) e padrões já renderizados de grupos,
status e disclosures do workbench. Nenhuma referência live inventada.

Reference lock: contraste preto/cinza atual; vermelho somente na seleção/ação;
verde para estado online; tipografia existente. Lateral com cabeçalho e worker
fixos, conteúdo rolável, grupos Neste laboratório / Outros dispositivos / Labs salvos.
Todos os adicionais entram no inventário lateral, contador descreve online
deste workspace. Labs são agrupados por package com API/perfil e ID curto,
atual destacado sem repetir package em cada variante. Busca única por aparelho,
serial, package, API, perfil e ID de lab; vazio e erro explícitos. Ícones SVG
nativos, nenhum asset raster necessário. Validar render, busca, agrupamentos,
atalho de criação, foco de adicional e layout móvel, sem trocar/desligar labs.

Validação da lateral: quatro aparelhos observados no workspace; nove labs em
quatro grupos. Busca API 30 devolveu dois labs; Sem root, dois aparelhos e três
labs; termo inexistente, vazio explícito. Selecionar o adicional apenas rolou
para sua tile e moveu foco. Atalho + abriu o formulário e foi cancelado. Drawer
verificado a 900×900 e viewport restaurado. Nenhum lab foi trocado/desligado.

## 2026-10-16 — organizar, nomear e selecionar quadros

Reference lock: pedido/HTML do usuário, canvas e cabeçalhos HuntMob, seleção
vermelha e diálogos de nome existentes; craft Refero de foco/teclado e rótulos
acabado de consultar. Arrastar apenas pelo cabeçalho; o canvas continua enviando
toque ao aparelho. Plano livre com posições persistidas por workspace e ID,
alias separado de AVD/UDID/package. Seleção pelo fundo, checkbox e Ctrl/Cmd;
botão coletivo mostra quantidade antes da ação. Fechar/desligar remove quadro
quando o runtime estiver offline e conserva dados/identidade na lateral para
retomar. Excluir quadro não equivale a apagar AVD/Simulator. Rejeitar todo o
lote antes de executar se um ID não pertencer ao workspace. Resultados parciais
mantêm visíveis aparelhos cujo desligamento não foi confirmado.

## 2026-10-16 — Workspace livre e Ferramentas de dispositivo

Referência mantida: tema e componentes atuais do HuntMob, quadros fornecidos pelo usuário, gesto de arraste somente no cabeçalho e controles separados da superfície interativa. Refero ao vivo retornou NO_SUBSCRIPTION; craft local e UI existente usados como referência de implementação. Biometrics do Genymotion foi comparado pela documentação primária e por REA/Ghidra no artefato local; sem copiar o protocolo ou modificar a licença.

Decisões: ações agrupadas em Ferramentas → Dispositivo com destino explícito; nomes/posições salvos separados da identidade nativa; seleção de grupo e desligamento com confirmação offline; remoção visual reversível com dados preservados; qualidade biométrica indisponível desabilitada com motivo. O antigo toast de “evento preparado” foi substituído por envio nativo condicionado ao pedido atual do Android. Perfil root/stock preserva APK base + splits originais.

Validação: arraste, seleção retangular e alias persistente verificados com quatro aparelhos reais do worker. Dois Androids extras desligados sem interromper o principal ou o iPhone; retomada inicialmente bloqueada pelo disco do Mac (~1 GiB livre), com diagnóstico visível. Após aumento do espaço livre no host (~5,5 GB), os mesmos Androids foram retomados; quatro aparelhos online ao final, root e stock reverificados. Ferramentas verificadas em 390×844, 900×900 e 2254×849. Override de viewport restaurado. Detalhes, Evidence IDs REA e limites em `workspace-controls-v1.0-2026-10-16.md`.

## 2026-10-16 — Atalho Root e compatibilidade dos iPhones antigos

Direção mantida: componentes atuais dos Controles, ícones SVG de traço, estados disabled e formulário existente de Novo laboratório. Referência funcional: pedido do usuário por acesso ao root na grade; limites reais das imagens Google Play, documentação oficial Apple e catálogo CoreSimulator local. Craft Refero de foco e formulários reaplicado; não houve nova direção visual.

Escolha: ícone mostra o perfil atual e abre uma ação explicitamente descrita como troca entre Androids separados. Não exibir um toggle fictício de root dentro da imagem Google Play. No iOS, Jailbreak desabilitado com razão visível. Seção recolhível para iPhone 7/8/X mostra faixas de runtime e ausência de versão compatível neste worker; nomes no catálogo não são tratados como aparelhos iniciáveis. Confirmação de perfil vinculada ao ID de origem para impedir troca de outro lab por uma tela desatualizada.

Validação: 607 testes Python, 28 JavaScript, HTTP 409 real para origem divergente sem alterar o lab atual; diálogo Root e seleção de iPhone 7/iOS 26 inspecionados no navegador. Detalhes e limitações em `root-shortcut-legacy-ios-v1.0-2026-10-16.md`.

## 2026-10-16 — Android 11 a 16 ARM64

Referências: formulário existente **Novo laboratório** do HuntMob, com versão, origem e perfil separados; catálogo oficial do Android SDK Manager no worker Apple Silicon; fluxo do Genymotion para escolher uma versão Android e instalar GApps como recurso separado. A direção visual, espaçamento e componentes do HuntMob foram mantidos.

Escolha: acrescentar Android 16 à lista de versões, manter Android 12L como opção explícita e mostrar ARM64 a partir da arquitetura observada no worker. A imagem AOSP ou Google Play é preparada no primeiro uso. O perfil AOSP é descrito como ADB root com Magisk opcional, sem prometer root automático para apps. Open GApps não é apresentado como instalável nas APIs 31–36 sem pacote oficial compatível.

Validação: as sete versões aparecem no formulário; API 36 AOSP arm64-v8a iniciou em AVD temporário e o laboratório principal permaneceu online. Detalhes em `android-11-16-arm64-v1.0-2026-10-16.md`.
