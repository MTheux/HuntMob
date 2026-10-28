# HuntMob Hardening — Design (2026-10-28)

## Intenção

Endurecer o lab HuntMob em quatro frentes aprovadas pelo operador, após o
redesign do workbench e as sub-abas por fase: (1) matar o cluster de bug
`Unexpected token '<'`, (2) reduzir o custo de CPU do polling, (3) dar
persistência consultável (histórico/busca de engajamentos), (4) validar as
ferramentas externas antes de rodar. Mais um ajuste de workflow: parar o
gateway Docker de servir `web/` em cache velho.

## Contexto do que já existe

- Front vanilla (HTML/CSS/JS clássico, sem bundler). `web/session.js` já tem
  `fetchJson`/`fetchSessionToken` com guarda de content-type (commit b822a46).
- Persistência: arquivos JSON soltos em `~/.huntmob` (`current.json`,
  `huntmob_*.json`), API em `src/huntmob/lab_sessions.py`. 10 módulos leem o
  estado vivo. Sem banco.
- CLI argparse em `src/huntmob/cli.py` (subcomandos `status`, `ui`, `android`,
  `bootstrap`…). Testes Python: `tests/test_*.py` (unittest). Testes cliente:
  `tests/client_*.test.cjs` (node:test + vm/require).
- Gateway Docker (`Dockerfile.control`) assa `web/` em build-time; o buildx
  reaproveita um layer `COPY web` obsoleto → serve markup velho.

## Decisões (rulings do autor)

1. **A1 — dois helpers, um guard.** `fetchJson` (devolve corpo, inclusive de
   erro `ok:false`, lança só em não-JSON) + novo `fetchJsonOk(input, init,
   label)` que também lança em `!response.ok` usando `body.reason`/`error`.
   Extrai-se um `guardedParse` privado comum. Converte-se só os sites
   **parse-depois-ok** (vulneráveis); os **check-ok-first** (`if(!response.ok)
   throw` antes do `.json()`) já são seguros e ficam como estão (YAGNI;
   converter mudaria comportamento sem ganho de segurança). `sessionFetch`
   continua lendo o corpo cru (inspeciona `error_code` e retenta) — não vira
   `fetchJsonOk`.

2. **A2 — polling consciente de visibilidade.** Helper `everyVisible(fn, ms)`
   em `web/polling.js`: um `setInterval` que **pula** o tick quando
   `document.hidden`. Substitui os ~12 `setInterval`. Os dois tickers de 2s do
   dinâmico (dast/frida e proxy) viram um só, que despacha pela aba ativa.
   Cache curto (TTL ~400ms) de `adb devices`/estado no worker Python para não
   refazer a cada tick.

3. **A3 — índice SQLite ADITIVO, não migração total.** Novo
   `src/huntmob/history.py` sobre `sqlite3` (stdlib) em `~/.huntmob/history.db`.
   Alimentado por hook best-effort no `lab_sessions.save()` + backfill dos
   `huntmob_*.json` existentes. **O estado vivo continua em JSON** — migração
   total fica deferida (blast radius de 10 módulos, risco de regressão num lab
   governado). Entrega backend + CLI (`huntmob history`, `huntmob search`); o
   painel na UI é follow-up. Custo se errado: duas fontes de verdade, mitigado
   por o índice ser derivado e append-only (o JSON é a verdade; o índice é
   reconstruível pelo backfill).

4. **A4 — `doctor`/preflight.** Novo `src/huntmob/doctor.py`: `check_tools()`
   devolve o status (achado, caminho, versão, ok vs. versão mínima) de `adb`,
   `emulator`, `sdkmanager`, `aapt`, `mitmproxy`/`mitmdump`, `jadx`, `apktool`,
   `frida`. Subcomando `huntmob doctor` imprime tabela e sai != 0 se faltar
   ferramenta requerida. `run-platform.py` emite aviso de preflight
   (não-fatal) no startup nativo.

5. **A5 — invalidação do layer `web`.** `ARG HUNTMOB_WEB_REV` no
   `Dockerfile.control` antes do `COPY web ./web`; `run-platform.py` passa
   `--build-arg HUNTMOB_WEB_REV=<rev de web/>`. Invalida o cache só quando
   `web/` muda, sem o custo de `--no-cache` sempre.

## Não-objetivos

- Migração total do estado vivo para SQLite (deferida).
- Painel de histórico/busca na UI (follow-up).
- Login/contas/multiusuário (descartado pelo operador).
- Tooling externo (objection/drozer/MobSF/nuclei) — frente B, brainstorming à
  parte.

## Restrições globais

- Python stdlib apenas (sem dependência nova; `sqlite3` já vem).
- Loopback-only / modelo governado preservado. Nenhuma persistência ou doctor
  pode abrir porta nem relaxar bind.
- Respostas da UI em Português com acentuação completa.
- Não publicar segredos/tokens em logs.
- TDD em tudo; suíte Python (`make test`) e cliente (`node --test`) verdes.
