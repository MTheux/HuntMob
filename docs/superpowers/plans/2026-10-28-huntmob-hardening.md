# HuntMob Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, escolhido pelo operador) para implementar task-by-task. Steps usam checkbox (`- [ ]`).

**Goal:** Endurecer o HuntMob: matar o cluster `Unexpected token '<'`, baratear o polling, dar histórico/busca em SQLite, validar ferramentas via `doctor`, e parar o gateway de servir `web/` em cache velho.

**Architecture:** Front vanilla (helpers compartilhados em `web/`), persistência Python stdlib (`sqlite3` aditivo sobre o JSON vivo), CLI argparse, Docker build-arg para invalidar o layer `web`.

**Tech Stack:** JS clássico + `node:test`; Python 3.9+ stdlib + `unittest`; Docker/compose.

**Spec:** `docs/superpowers/specs/2026-10-28-huntmob-hardening-design.md`

## Global Constraints

- Python stdlib apenas — nenhuma dependência nova (`sqlite3` já vem).
- Loopback-only / modelo governado preservado; nada abre porta nem relaxa bind.
- UI em Português com acentuação completa; sem segredos/tokens em logs.
- Cada arquivo `web/*` alterado tem o `?v=` em `web/index.html` bumpado.
- Suíte verde ao fim de cada task: cliente `node --test tests/client_*.test.cjs`, Python `PYTHONPATH=src python3 -m unittest discover -s tests`.

## Review Focus

- **502 HTML num site convertido com corpo JSON de erro legítimo** (4xx com `{reason}`): `fetchJsonOk` deve lançar `reason`, não a mensagem de "worker não pareado". Teste em Task 1.
- **Polling com `document.hidden` alternando** durante um tick em andamento: `everyVisible` não pode disparar fn em background nem vazar timer. Teste em Task 2.
- **`save()` com índice SQLite indisponível/corrompido**: o hook é best-effort e nunca pode quebrar o `save()` do lab. Teste em Task 5.
- **Backfill reentrante**: rodar o backfill duas vezes não pode duplicar linhas. Teste em Task 5.
- **`doctor` com ferramenta ausente do PATH**: `check_tools()` reporta `found=False` sem lançar; `huntmob doctor` sai !=0. Teste em Task 7.

---

### Task 1: `fetchJsonOk` + conversão dos sites parse-depois-ok (A1)

**Files:**
- Modify: `web/session.js` (extrair `guardedParse`, adicionar `fetchJsonOk`)
- Modify: `web/app.js`, `web/ios.js` (converter sites vulneráveis)
- Modify: `web/index.html` (bump `?v=`)
- Test: `tests/client_fetch_json.test.cjs` (adicionar casos de `fetchJsonOk`)

**Interfaces:**
- Produces: `fetchJsonOk(input, init, label)` → corpo JSON em `response.ok`; lança `Error(body.reason || body.error || `${label} ${status}`)` em `!ok`; lança mensagem "worker não pareado"/status em não-JSON. Compartilha a guarda com `fetchJson`.
- Consumes: `fetchJson` (existente).

- [ ] **Step 1: Testes falhando** em `tests/client_fetch_json.test.cjs`: `fetchJsonOk devolve corpo em 200`; `fetchJsonOk lança body.reason em 400 JSON`; `fetchJsonOk lança mensagem acionável em 502 HTML`; `fetchJsonOk usa label+status quando não há reason`.
- [ ] **Step 2: Rodar** `node --test tests/client_fetch_json.test.cjs` → FAIL (`fetchJsonOk` indefinido).
- [ ] **Step 3: Implementar** em `web/session.js`: extrair `async function guardedParse(input, init)` → `{response, body}` (fetch + guarda content-type + `response.json()`), reescrever `fetchJson` sobre ele, adicionar `fetchJsonOk`.
- [ ] **Step 4: Rodar** o teste → PASS.
- [ ] **Step 5: Converter os sites parse-depois-ok** (os que fazem `const x = await response.json()` antes/sem `if(!response.ok)`): `web/app.js` linhas ~152, 674, 723, 818, 976, 1030, 1056, 1113, 1220, 1319, 1395, 1556; `web/ios.js` ~184, 201, 314, 372, 415. Body-only → `fetchJson`; status-aware → `fetchJsonOk(url, init, '<rótulo curto>')`. **Não** tocar os check-ok-first nem `sessionFetch`.
- [ ] **Step 6: Bump** `?v=` de `session.js`, `app.js`, `ios.js` em `web/index.html` para `runtime-110-fetchjsonok`.
- [ ] **Step 7: Suíte cliente + Python** verdes.
- [ ] **Step 8: Commit** `fix(client): fetchJsonOk e conversão dos sites parse-depois-ok`.

---

### Task 2: Polling consciente de visibilidade (A2 front)

**Files:**
- Create: `web/polling.js`
- Modify: `web/app.js`, `web/ios.js`, `web/device-tools.js`, `web/ios-runtimes.js`, `web/workspace-devices.js`, `web/viewer.js` (trocar `setInterval` por `everyVisible`)
- Modify: `web/index.html` (registrar `polling.js`, bump `?v=`)
- Test: `tests/client_polling.test.cjs`

**Interfaces:**
- Produces: `everyVisible(fn, ms, doc=document)` → id do `setInterval`; a cada tick, se `doc.hidden` for verdadeiro, pula a chamada de `fn`. Guard CJS/browser (`module.exports`) no rodapé, como `workbench-phases.js`.

- [ ] **Step 1: Testes falhando** em `tests/client_polling.test.cjs` (require, doc stub com `hidden` alternável + fake timer manual): `everyVisible chama fn quando visível`; `everyVisible pula fn quando doc.hidden`; `everyVisible volta a chamar ao ficar visível de novo`.
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar** `web/polling.js` com o guard dual CJS/browser.
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Substituir** os `setInterval` nos arquivos listados por `everyVisible` (mesma condição-de-aba onde já existe). Consolidar os dois tickers de 2s do dinâmico (`app.js` ~1237 e ~1465) num só `everyVisible` que despacha pela aba ativa.
- [ ] **Step 6: Registrar** `polling.js?v=runtime-111-polling` em `web/index.html` antes de `app.js`; bump dos arquivos alterados.
- [ ] **Step 7: Suíte** verde.
- [ ] **Step 8: Commit** `perf(client): polling pausa em background via everyVisible`.

---

### Task 3: Cache curto de `adb devices` no worker (A2 Python)

**Files:**
- Modify: `src/huntmob/android_worker.py` (cache TTL em volta da listagem de devices)
- Test: `tests/test_android_worker.py`

**Interfaces:**
- Consumes/Produces: a função existente que lista devices (identificar; ex. `_adb_devices`/`devices`) ganha um cache in-process com TTL (`_DEVICES_TTL = 0.4s`), invalidável por timestamp monotônico; injeção de relógio para teste.

- [ ] **Step 1: Teste falhando** `test_adb_devices_cache_coalesces_within_ttl`: duas chamadas dentro do TTL batem no `adb` uma vez; após o TTL, batem de novo (relógio e runner de comando mockados).
- [ ] **Step 2: Rodar** `PYTHONPATH=src python3 -m unittest tests.test_android_worker -v` → FAIL.
- [ ] **Step 3: Implementar** o cache com TTL + injeção de clock.
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Suíte Python** verde.
- [ ] **Step 6: Commit** `perf(worker): cache curto de adb devices`.

---

### Task 4: Índice SQLite de engajamentos/evidências (A3 backend)

**Files:**
- Create: `src/huntmob/history.py`
- Test: `tests/test_history.py`

**Interfaces:**
- Produces: `connect(db_path=None) -> sqlite3.Connection` (default `~/.huntmob/history.db`, cria schema idempotente); `record_lab(record, conn=None)`; `record_evidence(lab_id, kind, path, label='', conn=None)`; `list_engagements(conn=None) -> list[dict]`; `search(query, conn=None) -> list[dict]`; `backfill(conn=None, root=None) -> int` (lê `huntmob_*.json`, upsert por `lab_id`, reentrante).
- Schema: `labs(lab_id PK, engagement, package_id, created_at, status, record_path)`; `evidence(id PK, lab_id FK, kind, path, label, created_at)`. `PRAGMA journal_mode=WAL`.

- [ ] **Step 1: Testes falhando** em `tests/test_history.py` (usando `:memory:` ou `tmp_path`): `record_lab_then_list_engagements`; `record_evidence_linked_to_lab`; `search_matches_engagement_and_package`; `backfill_is_reentrant` (rodar 2x não duplica); `connect_creates_schema_idempotently`.
- [ ] **Step 2: Rodar** `PYTHONPATH=src python3 -m unittest tests.test_history -v` → FAIL.
- [ ] **Step 3: Implementar** `src/huntmob/history.py` (upsert via `INSERT ... ON CONFLICT(lab_id) DO UPDATE`).
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Suíte Python** verde.
- [ ] **Step 6: Commit** `feat(history): índice SQLite aditivo de engajamentos/evidências`.

---

### Task 5: Hook best-effort no `save()` + CLI `history`/`search` (A3 fio)

**Files:**
- Modify: `src/huntmob/lab_sessions.py` (`save()` chama `history.record_lab` protegido)
- Modify: `src/huntmob/cli.py` (subcomandos `history`, `search`) + o handler
- Test: `tests/test_lab_sessions.py` (ou `tests/test_history.py`), `tests/test_cli.py` se existir

**Interfaces:**
- Consumes: Task 4 (`record_lab`, `list_engagements`, `search`).

- [ ] **Step 1: Teste falhando** `test_save_feeds_history_index_best_effort`: `save(record)` resulta em `record_lab` chamado; e com `history.record_lab` lançando (monkeypatch), `save()` **não** propaga a exceção (lab salvo mesmo assim).
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar** o hook em `save()` dentro de `try/except Exception` que apenas loga (sem segredos).
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Teste falhando** `test_cli_history_lists` e `test_cli_search_matches` (capturando stdout do handler). Implementar os subcomandos `history` e `search` em `cli.py`.
- [ ] **Step 6: Rodar** → PASS.
- [ ] **Step 7: Suíte Python** verde.
- [ ] **Step 8: Commit** `feat(cli): history/search sobre o índice; save alimenta o índice`.

---

### Task 6: `doctor`/preflight de ferramentas (A4)

**Files:**
- Create: `src/huntmob/doctor.py`
- Modify: `src/huntmob/cli.py` (subcomando `doctor`)
- Modify: `scripts/run-platform.py` (aviso de preflight não-fatal no startup)
- Test: `tests/test_doctor.py`

**Interfaces:**
- Produces: `ToolStatus` (namedtuple/dataclass: `name, found, path, version, ok, min_version, required`); `check_tools(which=shutil.which, run=subprocess.run) -> list[ToolStatus]` cobrindo `adb, emulator, sdkmanager, aapt, mitmdump, jadx, apktool, frida`; `format_table(statuses) -> str`; `exit_code(statuses) -> int` (!=0 se algum `required` faltar).

- [ ] **Step 1: Testes falhando** em `tests/test_doctor.py` (injetando `which`/`run` fakes): `check_tools_reports_missing_without_raising`; `check_tools_parses_version`; `exit_code_nonzero_when_required_missing`; `exit_code_zero_when_all_present`.
- [ ] **Step 2: Rodar** `PYTHONPATH=src python3 -m unittest tests.test_doctor -v` → FAIL.
- [ ] **Step 3: Implementar** `src/huntmob/doctor.py`.
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Wire** subcomando `doctor` em `cli.py` (imprime `format_table`, sai com `exit_code`); aviso não-fatal em `scripts/run-platform.py` (chama `check_tools`, imprime faltantes, segue).
- [ ] **Step 6: Suíte Python** verde.
- [ ] **Step 7: Commit** `feat(doctor): preflight de ferramentas + subcomando e aviso no native`.

---

### Task 7: Invalidar o layer `web` do gateway (A5)

**Files:**
- Modify: `Dockerfile.control` (`ARG HUNTMOB_WEB_REV` antes do `COPY web ./web`)
- Modify: `scripts/run-platform.py` (passar `--build-arg HUNTMOB_WEB_REV=<rev de web/>`)
- Test: `tests/test_run_platform.py` se existir; senão um teste leve de que o build-arg é computado a partir do conteúdo de `web/`.

**Interfaces:**
- Produces: função pequena `web_revision(web_dir) -> str` (hash do conteúdo de `web/`, ex. via `git rev-parse HEAD:web` com fallback para hash de mtimes) usada pelo build-arg.

- [ ] **Step 1: Teste falhando** `test_web_revision_changes_when_web_changes` (dois estados de um dir temporário dão revisões diferentes; idêntico dá igual).
- [ ] **Step 2: Rodar** → FAIL.
- [ ] **Step 3: Implementar** `web_revision` e passar o `--build-arg`; adicionar `ARG HUNTMOB_WEB_REV` antes do `COPY web` no `Dockerfile.control`.
- [ ] **Step 4: Rodar** → PASS.
- [ ] **Step 5: Validação manual** documentada: `make native` após mudar `web/` serve a versão nova sem `--no-cache` manual.
- [ ] **Step 6: Suíte** verde.
- [ ] **Step 7: Commit** `fix(gateway): invalida layer web via build-arg de revisão`.

---

## Self-Review (autor)

- **Cobertura do spec:** A1→Task 1; A2→Tasks 2–3; A3→Tasks 4–5; A4→Task 6; A5→Task 7. UI de histórico e migração total continuam fora (não-objetivos declarados).
- **Consistência de tipos:** `fetchJsonOk(input, init, label)` e `everyVisible(fn, ms, doc)` referenciados igual em todas as tasks; `record_lab(record)` produzido na Task 4 e consumido na Task 5 com o mesmo nome.
- **Review Focus:** cada item tem teste na task dona (erro JSON legítimo→Task 1; hidden→Task 2; save best-effort + backfill reentrante→Tasks 4/5; ferramenta ausente→Task 6).
- **Proporção:** steps são decisões (assinaturas, nomes de teste, sites), sem corpos transcritos.
