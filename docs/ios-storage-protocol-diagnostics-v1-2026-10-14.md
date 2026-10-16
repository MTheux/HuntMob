# Diagnóstico do armazenamento do emulador iOS — v1 — 2026-10-14

O trabalho permanece parcial. Foi compilado e executado um motor de pesquisa
instrumentado, mas não foi implementada a criptografia ANS/NVMe. O runtime
próprio continua bloqueado, sem SpringBoard, tela utilizável ou IPA validado.

## Alterações e isolamento

Três agentes revisaram o caminho ANS/NVMe, o contrato SEP/APFS e a auditoria
persistente. O código base continua fixado no Inferno
`cc4302a99167abec69b714cfd00c38caece7e7de`. O novo build usa um worktree
exclusivo; não copia os fontes sujos do experimento antigo e mantém o header
de proteção exatamente igual ao blob do commit fixado. O executável confiável
e seus pins não foram substituídos.

`scripts/build_ios_research_engine.py` registra revisão, patches, configuração,
submódulo e hashes de fonte/binário. A compilação usa até seis jobs, timeout e
grupo de processos próprio para encerrar também compiladores filhos. A opção
`--rebuild` admite somente uma árvore de diagnóstico consistente com o receipt,
preserva binário/receipt anteriores e aplica patches adicionais revisados.

Os eventos novos registram apenas metadados de operações. Não registram
valores de registros, chaves, buffers, keybags, LBAs ou ponteiros DMA.
`scripts/trace_ios_storage_research.py` aceita apenas o checkpoint sintético
próprio, cria cópias APFS COW com inodes independentes, verifica os nove hashes,
mantém `-snapshot`, nenhum NIC e QMP privado. Após parar a VM, revalida os
nove backings. Logs brutos e firmware permanecem fora do produto.

## Resultado real da primeira instrumentação

O binário de diagnóstico
`d77879c99bf5ed6f7e923ba6ca8f3faef47796237e4cc19d33da39b625cbebea`
foi compilado e inventariado no Mac ARM. O teste durou menos que o limite de
30 segundos de execução do guest. Todos os nove hashes do clone continuaram
idênticos após seu encerramento.

| Observação | Resultado |
| --- | --- |
| Comandos ANS submetidos/concluídos | 2.693 / 2.693 |
| Completion status NVMe | 0 em todos os eventos observados |
| Acessos vendor MMIO | 18 |
| Chamadas ao stub de admin `0xd8` | 3 |
| Transferências de chave nos endpoints instrumentados | 0 observadas |
| SEP/OS e verificador stock | Observados; verificador concluiu |
| APFS unwrap de chave | Recusado com `0xe00002e2` |
| Boot | Panic na tarefa Data Protection |
| SpringBoard / IPA / Data Protection validada | Não |

O significado criptográfico do comando vendor `0xd8` não foi identificado.
Seu handler atual devolve sucesso sem implementar a operação. Completion OK
não estabelece processamento correto ou criptografia. Zero transferências
significa apenas ausência de eventos nos pontos instrumentados neste boot.

Uma execução de comparação usou o binário anterior, em modo efêmero, no mesmo
clone. Também falhou na tarefa Data Protection. O diagnóstico novo não resolve
a falha e não estabelece sua causa sozinho. A saída 0 do processo do motor
não deve ser confundida com um guest saudável.

## Recompilação incremental e segunda observação

O patch incremental stage 2 acrescentou oito eventos para AESS/SSC. A
recompilação reutilizou a árvore de diagnóstico verificada e preservou o
binário anterior e seu receipt. O novo SHA256 é
`300d1e63f75e345bba75862d3f8ebeda8edffd3b3ccffb9d2f6c11b58a0da95d`.
Foi criado outro clone independente do mesmo checkpoint sintético, sem
reutilizar discos de uma VM ativa.

| Observação stage 2 | Resultado |
| --- | --- |
| Execução do guest / auditoria posterior | 15,40 s / 15,52 s |
| AESS operações / completions | 17.195 / 17.195 |
| Wrapping UID aproximado do upstream | 17.055 chamadas observadas |
| AESS invalid_parameters | 0 eventos marcados como inválidos |
| SSC comandos / completions | 218 / 218 |
| SSC comando de recarga de metadata `0x06` | 157 chamadas |
| SSC operações de backing | 356, todas com retorno de I/O 0 |
| Nove backings do clone | Hashes idênticos após encerramento |
| Boot / prontidão | Mesma falha de Data Protection; `ready=false` |

Está confirmado que o caminho aproximado de wrapping é usado e que os
handlers SSC acionam a leitura persistente nesse boot. Isso não prova que
os bytes sejam semanticamente corretos, que as chaves de arquivo sejam
reconstituídas ou que essas aproximações causem a recusa observada. A
ausência de erro de I/O e o completion AESS não substituem vetores
criptográficos independentes.

## Hipótese que precisa ser distinguida

O helper tenta abrir/truncar uma sonda persistida de classe C antes do primeiro
unlock. A classe C pode legitimamente recusar essa operação nessa etapa.
`kIOReturnNotPermitted` não comprova perda/corrupção de chave. Foi acrescentada
identificação explícita das falhas em open, write, fsync, read e comparação da
sonda; o helper atualizado compilou para iPhoneOS ARM64, mínimo iOS 14.0,
com `-Wall -Wextra -Werror`. Esse helper ainda não foi instalado ou executado
no guest. Não houve mudança da classe ou supressão da recusa.

A descoberta anterior de conteúdo em claro no backing persiste como um
bloqueio independente. Uma política de classe funcionando não comprova
cifragem inline. O contrato que falta inclui handoff SEP→AES do armazenamento,
wrapping de chaves de arquivo, descritores/contextos e unidades/IV/tweaks
compatíveis com esse firmware. A documentação pública descreve a arquitetura,
mas não fornece essa ABI: [Secure Enclave](https://support.apple.com/en-gb/guide/security/sec59b0b31ff/web).

## JEV e recompilação

Foi executado o gate **local** `JevControlPlane.desktop_admit`, usando o estado
real de `/api/ios/status`; ele recusou `DONE` sem evidência de prontidão.
Nenhum provedor remoto, modelo pago ou executor de desktop foi chamado.
Esse gate é supervisão de conclusão, não um oráculo de criptografia. O JEV
Ultrafast é voltado a elementos DOM e não fornece a implementação do hardware.

Compilar/recompilar o motor faz sentido: alterações de source são vinculadas a
um binário e comparadas no mesmo laboratório. Recompilar um aplicativo para
Simulator depende do código-fonte e de um target próprio; não transforma um
IPA de device num app de Simulator nem implementa emulação de iPhone.

## Evidências e validação

- [Build](../artifacts/validation/ios-storage-diagnostic-engine-build-v1-2026-10-14.json).
- [Trace](../artifacts/validation/ios-storage-protocol-trace-v1-2026-10-14.json).
- [Build incremental](../artifacts/validation/ios-storage-diagnostic-engine-stage2-build-v1-2026-10-14.json).
- [Trace AESS/SSC](../artifacts/validation/ios-storage-protocol-stage2-trace-v1-2026-10-14.json).
- [Comparação](../artifacts/validation/ios-storage-baseline-boot-v1-2026-10-14.json).
- [JEV local](../artifacts/validation/ios-jev-readiness-gate-v1-2026-10-14.json).
- [Contrato SEP/APFS e gates](ios-data-protection-contract-v1-2026-10-14.md).
- [Auditoria persistente](ios-storage-validation-contract-v1-2026-10-14.md).

Validação final: 265 testes Python e 13 testes JavaScript passaram; sintaxe
Python e `git diff --check` passaram. Os testes incluem coorte mutável,
processos filhos após timeout, macro de proteção inativa, preservação de
diretórios existentes e negativa de prontidão apesar de completions OK.
Os checks não comprovam funcionamento de iOS próprio. Após os experimentos,
Android e Apple Simulator continuavam ligados, o lab Android original estava
selecionado e as 500 capturas anteriores permaneciam disponíveis.

As alterações são locais, sem commit, push, deployment ou disponibilização de
um novo provider. Os labs Android e Apple Simulator existentes foram
preservados. Windows/Linux, iPad remoto, jailbreak e IPA físico não foram
validados por este experimento.
