# HuntMob — Retenção/poda das VMs iOS (recuperar disco)

- **Data:** 2026-10-26
- **Autor:** Mftheux! + Claude Code
- **Status:** rascunho para aprovação (nada implementado; nada apagado)
- **Escopo:** ferramenta de **retenção/poda** das VMs de pesquisa iOS em
  `~/.huntmob/research/ios-vms`, para recuperar disco. iPhone 11 (t8030),
  macOS. Dry-run por padrão; destruição só com alvo explícito + `--apply`.

## 1. Como chegamos aqui (premissas corrigidas)

A investigação inicial supôs que o inchaço vinha de checkpoints serem **cópias
inteiras** e que a solução era clonar. **Ambas as premissas estavam erradas** —
corrigidas por revisão do código e do disco:

- **O clone CoW já existe.** `scripts/trace_ios_storage_research.py:clone_checkpoint`
  já usa `/bin/cp -c` (clonefile APFS) com validação (`nlink`, `samefile`,
  digest). Os `checkpoint.json` já registram backings clonados. Um "helper de
  clone" seria no-op.
- **O custo real é divergência de blocos**, não cópia: o restore/boot reescreve
  parte da base depois do clone, e o CoW materializa só os blocos alterados.
- **`fingerprint()` é por inode** (não conteúdo); `digest()` é o hash de
  conteúdo. Cada cohort grava o próprio fingerprint no seu manifest.

Direções descartadas (com motivo registrado):

- **Migrar para iPhone X (A11):** o engine é um fork QEMU que modela **só o
  `t8030` (A13/iPhone 11)** (`components/ios-engine/firmware-recipe.json`
  `model:t8030`/`n104ap`; `AppleT8030MachineState`). Não há `t8015`. Migrar =
  escrever um SoC novo no QEMU (meses). Além disso o motivo (checkm8/blackbird)
  é propriedade de **hardware físico** e não existe na emulação. **Fora.**
- **Rodar no Windows:** o lab é macOS-only por dependência dura — loop device
  via `hdiutil`/`diskutil` (gate hardcoded em `/dev/disk[0-9]+`), macOS
  Keychain como backend de chave, QEMU apple-silicon compilado com Xcode 27
  (`macos27-build.patch`, accel HVF), `codesign`. Porte = reescrita. **Fora.**

**Conclusão:** a única alavanca real de disco é **poda/retenção**.

## 2. Estado medido (2026-10-25/26)

- `~/.huntmob/research/ios-vms` = **168 GB** (`du`), nenhuma VM ativa.
- 2 VMs `virtual-sep-*` (51 GB + 44 GB): cada uma 1 base + 5–6 `checkpoint-*`
  encadeados por timestamp.
- 9 VMs `native-storage-trace-*` (~7.4 GB cada, ~67 GB): snapshots de trace de
  14–15/out, independentes.

**Caveat de medição (crítico p/ honestidade):** `du`/`stat` **não enxergam o
sharing CoW** do APFS — contam blocos clonados como se fossem exclusivos de cada
arquivo. Então **168 GB é um teto lógico**, não o reclaim físico garantido. O
ganho real só é conhecido medindo o espaço livre (`df`) antes/depois de apagar.

## 3. Objetivos, não-objetivos, anti-objetivos

**Objetivos:**
1. `scripts/prune_ios_vms.py`: inventariar VMs/checkpoints com tamanho lógico,
   idade, e marcar a **ponta (tip)** de cada cadeia vs. checkpoints superados.
2. Recuperar disco apagando, sob confirmação explícita, checkpoints superados
   e/ou VMs de trace antigas.
3. Reportar o reclaim **real** (via `df` antes/depois) no `--apply`; no dry-run,
   deixar claro que o número é "até X" (teto lógico).
4. Opção `--archive <dir>` para comprimir antes de remover.

**Não-objetivos:** mexer no clone/engine/staging; migrar device; Windows; tocar
o runtime Android ou a UI.

**Anti-objetivos (falha mesmo "funcionando"):**
- Apagar qualquer coisa sem alvo explícito + `--apply` (dry-run é o default).
- Operar sobre VM possivelmente ativa (socket presente).
- Tocar `artifacts/validation`, receipts ou qualquer evidência.
- Apagar a ponta (tip) de uma cadeia sem `--force` explícito.
- Prometer reclaim físico que o `du` não garante.

## 4. Design da ferramenta

### 4.1 Inventário (default, read-only)

`python3 scripts/prune_ios_vms.py [--json]`

- Lista cada VM sob `ios-vms/`: tipo (`virtual-sep-*` / `native-storage-trace-*`),
  tamanho lógico (`du`), data, nº de checkpoints, qual é a ponta (checkpoint mais
  recente por timestamp do nome/`checkpoint.json`).
- Marca candidatos a poda: checkpoints não-ponta; trace VMs por idade.
- Cabeçalho com `df` do volume (livre/total) e aviso do caveat CoW.

### 4.2 Seleção e poda (`--apply`)

- Alvos explícitos: `--vm <nome>` (VM inteira), `--superseded <nome>` (só os
  checkpoints não-ponta de uma VM), `--traces-before <YYYY-MM-DD>`.
- **Sempre** imprime o plano e o `df` atual; sem `--apply` não remove nada.
- Com `--apply`: mede `df` livre antes, remove, mede depois, reporta **reclaim
  real** (delta de `df`) além do lógico.
- `--force` necessário para remover a ponta de uma cadeia.
- `--archive <dir>`: `tar`+compressão da VM/checkpoint antes de remover.

### 4.3 Segurança

- Recusa se existir `qmp.sock`/`usb.sock` em qualquer VM alvo (reutiliza o
  padrão de `ios_virtual_data_v2_contract.py`: "VM pode estar ativa").
- Valida que todo alvo tem `parent == RESEARCH/ios-vms` (mesmo invariante dos
  scripts existentes) — nunca aceita path fora disso, nem symlink.
- Nunca percorre nem toca `~/HuntMob/artifacts`, receipts ou evidência.
- Remoção é `shutil.rmtree` só após todas as checagens; sem `-rf` cego.

### 4.4 Migração concreta (proposta, opt-in)

Ordem sugerida depois de aprovado (cada passo é `--apply` explícito seu):
1. `--traces-before 2026-10-16` → remove as 9 trace VMs de 14–15/out (~67 GB
   lógico) — eram snapshots de etapa, não cadeia viva.
2. `--superseded` nas 2 `virtual-sep-*` → remove checkpoints intermediários,
   preserva a ponta de cada cadeia.
Reclaim real reportado ao fim por `df`.

## 5. O que fica a cargo do builder

- Formato exato da saída (tabela/JSON), flags finais.
- Como ler a ponta da cadeia (timestamp do nome vs. campo no `checkpoint.json`).
- Estratégia de `--archive` (nível de compressão, nome do arquivo).
- Testes: inventário em fixture temporária, recusa por socket ativo, recusa de
  path fora de `ios-vms`, preservação da ponta, dry-run não remove nada.

## 6. Decisões do usuário

1. Confirmar a **ordem de poda** da seção 4.4 (traces primeiro; depois
   superseded), ou ajustar o que preservar.
2. Querer `--archive` (guardar comprimido antes) ou remoção direta.
