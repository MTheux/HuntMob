# Design — Modernização do Workbench "Ferramentas" (Android)

Data: 2026-10-28
Status: aprovado (direção validada via mockup descartável em
`scratchpad/workbench-mock.html`, http://127.0.0.1:8777)

## Intenção e porquê

O painel lateral `Ferramentas` (`aside.analysis-panel`) acumulou três
problemas que atrapalham o uso durante um teste:

1. **Visual** — densidade alta, caixa-alta repetida (eyebrows empilhados),
   hierarquia tipográfica achatada e estados (online / sem root / indisponível)
   difíceis de ler de relance.
2. **Organização** — duas taxonomias competem e se sobrepõem: o *stepper* de
   fases (1 Engagement → 2 Estático → 3 Dinâmico → 4 Evidências) e os grupos de
   abas (LABORATÓRIO / INVESTIGAÇÃO / RESULTADOS). O usuário precisa raciocinar
   em dois eixos pra achar uma ferramenta.
3. **Dispersão** — ferramentas/affordances moram fora do workbench (contador de
   Evidências num ícone solto no header do topo; grade de controles do device
   solta), em vez de convergirem pro painel.

## Objetivos

- **Uma taxonomia só**: as 4 fases viram a espinha de navegação; cada fase
  contém as ferramentas dela. Elimina o agrupamento paralelo
  Laboratório/Investigação/Resultados.
- Mapa fase → ferramentas:
  - **1 Engagement**: aparelho ativo + grade de controles + Arquivos/sandbox +
    Preparar pentest + Engenharia do app (seleção de APK → REA).
  - **2 Estático**: resultado observado do REA / código.
  - **3 Dinâmico**: DAST + Frida + Tráfego (Proxy) + diagnóstico TLS/mTLS.
  - **4 Evidências**: capturas e registros; o contador vive na espinha.
- **Visual nativo e mais limpo**: mesmos tokens do `styles.css` (tema escuro,
  vermelho de marca), mais respiro, caixa-alta só em eyebrows curtos, chip de
  aparelho com *status dot* e badge de perfil, tiles de controle com estado
  (armado) e hover.
- **Consolidar o disperso**: controles do device dentro da fase 1; contador de
  Evidências migra pro passo 4 da espinha e sai do header do topo.

## Não-objetivos / anti-objetivos

- Não adicionar, remover ou renomear ferramentas/capacidades — é reorganização
  e repintura, não mudança de recurso.
- Não mexer no backend, no worker, nos endpoints nem no comportamento iOS.
- **Anti-objetivo**: quebrar a fiação existente. Mesmo que fique bonito, se um
  controle parar de funcionar o trabalho falhou. Todo handler atual precisa
  continuar válido.

## Restrições

- O JS depende de contratos de DOM que **não podem sumir silenciosamente**:
  `#analysisPanel`, `#analysisToggle`, atributos `data-tab`, `data-step-tab`,
  `data-panel`, `.analysis-tabs`, `.engagement-stepper`, `#evidenceCount`,
  `.device-controls`. A migração preserva esses ganchos ou atualiza o JS que os
  usa, no mesmo passo — nunca deixa pendente.
- Acessibilidade: manter `role="tablist"`/`role="tab"`, `aria-selected`,
  `aria-controls` e rótulos.
- Bump de cache-busting (`?v=`) nos arquivos web alterados.
- Suíte cliente (`tests/*.test.cjs`) e sintaxe dos arquivos web precisam ficar
  verdes.

## O "como" já decidido (validado no mockup)

- Espinha de 4 fases no `header` do painel, substituindo a dupla
  stepper+grupos. Estados: feito (check verde), ativa (vermelho de marca),
  pendente (neutro). Passo 4 carrega o contador de evidências.
- Chip "APARELHO ATIVO" no header: dot de status + nome + id mono + badge de
  perfil (ex.: "Google Play · sem root" em âmbar).
- Fase 1 abre com a grade de controles (`deck`) em tiles de 4 colunas, seguida
  dos cards Preparar pentest e Engenharia do app, e a barra de ciclo de vida
  (Play Store / Voltar / Desligar) no rodapé da fase.
- Fase 3 reúne DAST, Frida, Tráfego e TLS como cards numa única rolagem.
- Paleta/tipografia/raios/espaços vêm dos tokens de `:root` já existentes.

## O que fica a cargo de quem implementa

- Estratégia exata de migração do DOM mantendo os IDs/atributos acima e o
  mapeamento de cada `data-tab` atual pra sua fase, incluindo se o JS de
  troca de aba passa a ser dirigido pela espinha.
- Refatoração das classes CSS (reusar vs. renomear) sem regressão de layout
  responsivo do painel.
- Onde ancorar o contador de evidências no JS após sair do header.
- Ordem de corte pra manter o app funcional a cada passo (TDD onde couber nos
  testes cliente).
