# HuntMob — Modernização da UI (reestruturação de UX faseada)

- **Data:** 2026-10-22
- **Autor:** Mftheux! + Claude Code
- **Status:** Fase 0 aprovada para implementação; Fases 1–4 planejadas
- **Escopo do spec:** detalha a **Fase 0 (fundação visual)**. As Fases 1–4
  são registradas como roteiro; cada uma terá seu próprio spec + plano.

## 1. Contexto

A UI do HuntMob (`web/`) é um workbench dark de análise mobile já funcional:
topbar com marca HUNT/MOB, rail de ícones (52px), sidebar de dispositivos
(234px) e workspace com o mockup do telefone ao vivo + painel de abas
(Device Tools / Reverse / Files / Proxy / DAST). É vanilla JS (um `index.html`
de ~40 KB, `styles.css` de ~100 KB minificado, e ~20 módulos `*.js`).

Tokens atuais no `:root`: `--bg:#09090a`, superfícies `--surface`…`--surface-3`,
linhas `--line`/`--line-strong`, texto `--text/--muted/--quiet`, acento
`--red:#e7274a`, semânticos `--green/--amber/--blue`, `--radius:7px`, fontes
Inter + mono.

O objetivo é deixar a interface **mais moderna e intuitiva**, mantendo a
identidade "security console" dark/vermelha.

### Restrição crítica (fidelidade a "sem bug")

Os módulos JS e os testes `tests/client_*.test.cjs` consomem `id`/classes
específicos do DOM (ex.: `operator-session.js` cria elementos por tag; testes
verificam atributos e comportamento). Portanto, **nenhuma mudança pode
renomear ou remover `id`/classes que o JS e os testes usam**. Classes e
atributos novos entram apenas de forma aditiva.

Suíte de referência que deve permanecer verde:
- `PYTHONPATH=src python3 -m unittest discover -s tests` → **733 testes**
- `for f in tests/*.test.cjs; do node "$f"; done` → **16 suítes, fail 0**

## 2. Objetivos e não-objetivos

**Objetivos (programa completo):**
1. Aparência moderna e coesa, estética "dark console polido".
2. Navegação mais clara (reduzir sobreposição rail + sidebar + abas).
3. Abas do painel reorganizadas por contexto do device.
4. Onboarding / primeiro uso guiado.
5. Fluxo de pentest visível como passo-a-passo (stepper).

**Não-objetivos:**
- Modo claro (decisão do usuário: dark-only nesta rodada).
- Reescrever a lógica JS ou a API `/api/*`.
- Refatoração não relacionada ao objetivo visual/UX.
- Framework de frontend (mantém vanilla JS).

## 3. Abordagem de execução (aprovada)

Execução **faseada**. Cada fase é independente, com spec → plano →
implementação → screenshots → aprovação, mantendo os testes verdes:

| Fase | Entrega | Toca JS? | Risco |
|---|---|---|---|
| **0 — Fundação visual** | Tokens, elevação, espaçamento, tipografia, componentes, estados | Não | Baixo |
| 1 — Navegação | Consolidar rail + sidebar + abas | Sim | Médio |
| 2 — Abas do painel | Reagrupar/renomear/ordenar por contexto | Sim | Médio |
| 3 — Onboarding | Tela de primeiro uso + fluxo inicial | Sim | Médio |
| 4 — Stepper de pentest | Passo-a-passo engagement→DAST→REA→análise | Sim | Médio-alto |

As Fases 1–4 reutilizam o sistema de design definido na Fase 0.

## 4. Fase 0 — Design detalhado

### 4.1 Tokens e fundação (`:root`)

Mantém a paleta base e **estende** com tokens semânticos e escalas. Valores
são ponto de partida, ajustáveis durante a validação visual:

- **Superfícies em camadas:** manter `--surface`…`--surface-3`; adicionar
  `--surface-4` para o nível mais elevado (menus/dialogs/popovers).
- **Elevação:** `--shadow-sm`, `--shadow-md`, `--shadow-lg` (sombras suaves,
  baixa opacidade) para cards, dialogs, toasts e o stage do telefone.
- **Raio:** introduzir `--radius-sm:5px`, `--radius-md:8px`, `--radius-lg:12px`;
  manter `--radius` como alias de `--radius-sm` para compatibilidade.
- **Espaçamento:** `--space-1:4px … --space-6:24px` para ritmo consistente de
  paddings/gaps.
- **Tipografia:** adicionar `--text-strong` (títulos/valores); refinar
  hierarquia de tamanhos/pesos de títulos, labels e mono. Mantém Inter + mono.
- **Foco:** padronizar o anel `focus-visible` (cor `--red`, offset consistente).
- **Movimento:** `--transition:120ms` base; respeitar `prefers-reduced-motion`
  (já existente).

Compatibilidade: os tokens antigos continuam existindo; nada que os referencie
quebra.

### 4.2 Componentes (mesmos seletores, valores elevados)

- **Botões** (`.primary`, `.outline`, `.stop`, `.icon-button`, `.square-button`
  e um novo papel aditivo `.ghost` quando útil): alturas/paddings consistentes,
  estados `hover/active/disabled`, transição discreta.
- **Cards/seções** (`.sidebar-section`, `.ios-native-status`, `.finding`,
  `.proxy-state`, `.pentest-readiness`, `.empty-state`): superfície + borda +
  raio unificados; leve elevação em hover apenas quando clicável.
- **Inputs/busca** (`.search input`, `.phone-screen input`, textareas do
  `.http-split`): borda e anel de foco coerentes.
- **Abas** (`.analysis-tabs button`): estado ativo mais claro (sublinhado +
  cor + peso), hover suave; contadores (`.analysis-tabs span`) como badge.
- **Linhas de device** (`.device-row`, `.device-thumb`, `.online-dot`/
  `.offline-dot`): hover e `.selected` mais legíveis; thumbs com cor semântica
  android/ios já existente.
- **Status/pills/badges** (`.status-live`, `.safe-badge`, `.eyebrow`,
  `.engagement`, `.worker-status`): família visual única.
- **Overlays** (`dialog`, `.dialog-shell`, `.toast`): sombra `--shadow-lg`,
  raio `--radius-lg`, backdrop com blur (já existe), header consistente.

### 4.3 Layout e ritmo

- Paddings/gaps de `.topbar`, `.rail`, `.device-list`, `.workspace`,
  `.stage-toolbar`, `.event-strip`, `.panel-title` padronizados pela escala de
  espaçamento.
- Polimento de `.phone-wrap`/`.phone`/`.phone-screen` (bezel, sombra, cantos).
- Preservar o grid de layout (`.shell`, `.workspace`) e os breakpoints
  responsivos existentes; apenas refinar valores.

### 4.4 Micro-interações e acessibilidade

- Transições de `background/border/color` em botões, abas, linhas e inputs.
- `focus-visible` consistente em todos os interativos.
- Conferir contraste de `--muted`/`--quiet` sobre as superfícies.
- Sem animação quando `prefers-reduced-motion: reduce`.

## 5. Restrições de implementação

1. **Reescrita de `styles.css`** para forma organizada e legível (seções:
   tokens → base → topbar/rail/sidebar → workspace/stage → painel/abas →
   componentes → overlays → responsivo), **preservando todos os seletores**
   atuais e seu efeito. O diff será grande (reorganização), mas o comportamento
   é preservado.
2. **HTML** (`web/index.html`): apenas ajustes aditivos (wrappers, atributos,
   classes novas) quando necessário para o estilo; **sem renomear/remover**
   `id`/classes consumidos por JS/testes.
3. **Nenhuma alteração em `*.js`** na Fase 0.
4. **Sem novas dependências** nem recursos externos (mantém abertura sem build,
   sem CDN; fontes do sistema/Inter como hoje).

## 6. Validação e testes

- **Comportamental:** suíte Python (733) e JS (16, fail 0) devem permanecer
  verdes após a Fase 0. São o critério objetivo de "sem bug".
- **Visual:** subir `PYTHONPATH=src python3 -m huntmob.cli ui`, abrir no Chrome
  e capturar antes/depois das telas principais (workspace vazio, device
  selecionado, aba Reverse, aba DAST, dialog). Requer a extensão do Chrome
  conectada; se indisponível, o usuário abre a UI localmente para aprovar.
- **Critério de aceite da Fase 0:**
  1. Testes verdes (Python + JS).
  2. Nenhum `id`/classe consumido por JS/testes removido ou renomeado.
  3. Aparência aprovada pelo usuário via screenshots/visualização.

## 7. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Regressão visual sutil ao reescrever CSS | Preservar seletores; validar por screenshots antes/depois |
| Quebra de teste por mudança de DOM | Fase 0 não toca JS; HTML só aditivo; rodar suíte completa |
| Diff grande dificultar revisão | Organizar CSS em seções nomeadas e comentadas |
| Breakpoints responsivos regredirem | Manter media queries existentes; refinar apenas valores |

## 8. Fora de escopo (desta fase)

- Fases 1–4 (navegação, abas, onboarding, stepper) — specs próprios.
- Modo claro, i18n, troca de framework, mudanças de API.

---

## Adendo — Execução da Fase 1 (Navegação) — 2026-10-22

A inspeção da navegação revelou que ela já estava mais limpa que o briefing:

- **Não existe elemento `.rail`** no HTML; os "3 níveis" são apenas topbar +
  sidebar de dispositivos + nav de abas (já agrupada em LABORATÓRIO /
  INVESTIGAÇÃO / RESULTADOS).
- O contrato estável é `data-tab` (valores referenciados no JS: `device-tools`,
  `reverse`, `dast`, `frida`, `evidence`). **Preservado integralmente.**
- A cascata de regras `.shell` resolve efetivamente para: `≥1101px →
  280px 1fr`; `≤1100px → coluna única + sidebar em drawer`. As demais regras
  `.shell` (base `52px 234px 1fr`, `48px 180px 1fr`, etc.) e todo o CSS `.rail*`
  estão **sobrescritos/mortos** — não renderizam. Ou seja, **não havia coluna
  visível desperdiçada**; o "item 1" era dead code, não espaço perdido.

**Implementado (CSS aditivo, sem tocar JS nem `data-tab`):**
- Item 3 — rótulos de grupo (`.tool-group-label`) agora `position:sticky` com
  divisor sutil, mantendo o contexto do grupo ao rolar a nav.
- Item 2 — toggle "Ferramentas" (`.analysis-toggle`) com raio/sombra/peso de
  controle real.
- Item 4 — hover coerente no ícone de Evidências da topbar.

**Adiado para passe de higiene separado (sem efeito visual):**
- Item 1 — remoção do dead code (`.rail*` e regras `.shell` sobrescritas). Alto
  risco de editar a linha minificada da base para ganho apenas de limpeza;
  tratado fora da Fase 1.

**Validação:** 733 testes Python + 16 suítes JS verdes; screenshots desktop/iPad
sem regressão.

**Recomendação:** o maior ganho de "intuitivo" está nas Fases 3 (onboarding) e
4 (stepper de pentest). A navegação já cumpre bem o papel após a Fase 1.

---

## Adendo — Execução da Fase 2 (Abas por contexto do device) — 2026-10-23

Como na Fase 1, a inspeção mostrou que o grosso do briefing já existia:

- **Agrupamento** (LABORATÓRIO / INVESTIGAÇÃO / RESULTADOS) já no HTML.
- **Contexto do device** já implementado: `syncPlatformTools()` (`ios.js`) +
  `tool-support.js` ocultam abas android-only no iOS (`files`, `dast`),
  renomeiam subtítulos por plataforma e carregam *reasons* de capacidade.
- **Nomes** já claros.

**Implementado (aditivo, `data-tab` preservado, lógica JS não reescrita):**
- **Ordenação por fluxo de pentest** em INVESTIGAÇÃO: `Análise estática →
  Análise dinâmica (DAST) → Frida → Tráfego` (antes estática→frida→dast→proxy).
  Só reordenação de HTML; os testes não checam ordem do DOM.
- **Realce do grupo ativo** (`.tool-group-label.tool-group-active`): o rótulo do
  grupo cuja aba está ativa ganha cor de acento + borda-acento à esquerda. JS
  aditivo (`syncActiveToolGroup()` em `app.js`, chamado no clique de aba e no
  init) + CSS. Resolve "onde estou" ao rolar a nav.
- **Guarda de grupo vazio** (`syncPlatformTools` + `.tool-group-label[hidden]`):
  se todas as abas de um grupo ficarem ocultas no contexto atual, o rótulo some
  junto. Defensivo — nas configs atuais nenhum grupo esvazia.

**Validação:** 733 testes Python + 16 suítes JS verdes. Screenshots via Edge
headless + CDP em dois contextos de device: Android (reorder + realce de
INVESTIGAÇÃO vermelho) e iOS (abas android-only ocultas, realce de LABORATÓRIO,
nenhum grupo órfão).

**Nota de commit:** diferente das Fases 0/1 (só `styles.css`/`index.html`), a
Fase 2 tocou `app.js` e `ios.js`, que já carregavam WIP não commitado da branch.
Commitar isolando apenas as mudanças da Fase 2 exige *staging* cirúrgico desses
dois arquivos.

---

## Adendo — Execução da Fase 4 (Stepper de pentest) — 2026-10-23

**Decisões do usuário:** stepper no **topo do painel de ferramentas**; ordem
**engagement → estático → dinâmico → evidências** (metodológica, não a literal do
spec).

**Implementado (aditivo; `data-tab` preservado; fluxos das abas não reescritos):**
- Stepper global `#engagementStepper` numa 2ª linha do `.toolbox-head` (header do
  painel passou de altura fixa 52px para `auto`; 1ª faixa do grid do
  `.analysis-panel` ajustada de `52px`→`auto` nas 4 variantes responsivas).
- `syncEngagementStepper()` (app.js) lê sinais já rastreados e marca cada passo
  como `pending`/`current`/`done`:
  - engagement → `engagementBound` (de `activeLab.engagement` / `data.lab.engagement`)
  - estático → `reverseAnalysis`
  - dinâmico → `dastProgressReport` (report DAST, **não** `analysisReady`, que é só
    disponibilidade do motor)
  - evidências → `#evidenceCount > 0`
  - `current` = primeiro passo ainda não concluído.
- Passos **clicáveis** (`[data-step-tab]` → clica a aba correspondente; engagement
  → `device-tools`, onde fica "Preparar pentest"). Guarda: não navega se a aba
  estiver `hidden`/`disabled` (ex.: Dinâmico no iOS).
- Chamadas de `syncEngagementStepper()` nos pontos de update existentes
  (carga do lab, deep-dast, REA, report DAST, contagem de evidências, init).

**Validação:** 733 Python + 16 JS verdes; `node --check` em app.js/ios.js.
Screenshots via CDP: Android (stepper com estados mistos; clique em "Estático"
navega para a aba reverse) e iOS (stepper renderiza, abas android-only ocultas,
sem quebra de layout com header de 2 linhas).

**Refinamento futuro (não-bug):** no iOS, o passo "Dinâmico" aparece como
pendente embora o DAST seja android-only; poderia ser visualmente atenuado. A
guarda já impede erro ao clicar.

### Status do programa
Fases 0, 1, 2 e 4 concluídas. Fase 3 (onboarding) e o passe de higiene de dead
code CSS (`.rail*`, regras `.shell` sobrescritas) permanecem pendentes.
