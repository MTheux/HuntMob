# Processos da interface no runtime próprio — v14, 2026-10-15

**Confirmado no ensaio nativo `183446`:** o `keybagd --init` original terminou
com exit/signal 0, o boot alcançou seu marcador inicial stock e a coleta
temporária completou 24 snapshots. SpringBoard, backboardd e runningboardd
apareceram nos snapshots 1 a 23. Ainda não há interface utilizável ou IPA
validado; a captura continua idêntica ao logo do engine.

## Resultado observado

| Processo | Amostras | PID observado | Estado numérico |
| --- | --- | --- | --- |
| SpringBoard | 1–11 / 12–23 | 58 / 155 | 2 |
| backboardd | 1–11 / 12–23 | 61 / 152 | 2 |
| runningboardd | 1–23 | 32 | 2 |

O snapshot 0 precedeu o aparecimento dos três nomes. Houve 69 linhas de
processos permitidos. As mudanças de PID são evidência de transição de
instância observada; não demonstram crash, sinal, exit code ou sua causa.
O estado `p_stat=2` também não é um exit status nem comprova frames renderizados.

O ensaio durou 240,0 s, aceitou 2.176 callbacks de refresh e executou 22.487
comandos AESS. Não houve panic, recusa AESS/NVMe/gate/IO ou fault MPE nos
contadores instrumentados. QMP quit foi aceito e o engine terminou com 0.
A imagem final 828×1792 tem os mesmos pixels e bytes do logo anterior.
Os callbacks e sua latência no host não são FPS, latência de toque ou fluidez
do iOS. Outros diagnósticos de serviços SEP permanecem sem interpretação
comprovada; não se afirma que toda operação criptográfica passou.

## Instrumentação delimitada

O coletor próprio usou somente `sysctl`/`kinfo_proc` e filtrou exatamente
os três nomes. Emitiu apenas índice da amostra, nome estático, PID e estado.
Limites: buffer de 1 MiB, 24 snapshots a intervalos de 5 s, deadline de
120 s e alarm de 130 s. Não leu argv, ambiente, mapas/memória de processos,
conteúdo de crash, dados de aplicativos, keybags ou chaves.

Um wrapper temporário conferiu o programa original por hash e executou seu
init uma vez. Somente após exit 0 iniciou o coletor em grupo separado,
confirmado pelo parent. O parent retornou o resultado stock para o launchd
prosseguir. A rota normal do daemon permaneceu um `exec` do original.
SIGALRM foi definido como padrão e desbloqueado para os limites funcionarem.

O stock continuou exigindo UID0. Um arquivo do coletor com outro owner só
poderia passar com bytes/mode/link/identidade conferidos e System/APFS
readonly, UUID e dispositivo exatos. Nenhum launchd, cache de jobs, dyld,
SEP/ANS, KDF ou política de armazenamento foi alterado neste ensaio.
O trustcache recebeu somente os dois hashes dos auxiliares próprios.

## Restauração concluída

O consumidor verificou o recibo e os hashes dos logs, recompôs os contadores
e restaurou o programa stock pelo mesmo inode. O coletor foi removido e o
IM4P original do trustcache foi reposto por bytes. Os seis volumes e a
identidade criptográfica permaneceram os mesmos; Data não foi montado nem
desbloqueado no host. O estado final é `observed-original-restored`.

A verificação final confirmou ausência de lock e de disco anexado, com os
seis volumes preservados. A varredura posterior leu novamente os nove
backings, 34.369.523.712 bytes em 17,40 s, sem os dois formatos do marcador
público e sem mudança das identidades durante a leitura. Essa ausência
continua sendo uma verificação delimitada, não prova de criptografia completa.

Uma incompatibilidade de formato bloqueou inicialmente a restauração:
o recibo original omitiu `full_boot_validated`. O leitor foi corrigido para
esse único recibo, ligado ao nome e SHA256 exatos. Não se alterou o recibo;
`true`, `null` ou ausência de outros campos continuam rejeitados. Os futuros
recibos declaram as flags de validação explicitamente como falsas.

Antes do ensaio, um checkpoint privado COW preservou e verificou por hash
nove backings, manifesto e trustcache, em 29,82 s. Isso é um checkpoint
de pesquisa, sem exportação de Root; não é snapshot/migração de produto validado.

## Estado de aceitação

A leitura persistente de uma sonda Class C foi validada anteriormente em
`173327`, sob identidade/KDF/política próprios. O boot inicial e a presença
dos três processos agora têm evidência nativa. Proteção completa, BFU,
bloqueio/desbloqueio, outras classes, interface, controles e IPA continuam
sem validação. O achado histórico de plaintext permanece aberto, e
`ready=false`/`native_ready=false`.

O próximo diagnóstico precisa observar a saída real dos processos ou seu
caminho de renderização. Uma transição de PID não deve ser convertida em
crash confirmado. Não foram aplicados patches gráficos, flags de renderer,
alterações de privilégios ou pareamento automático.

## Evidência local

- [Leitura persistente Class C](../artifacts/validation/ios-own-data-v2-native-cold-read-v1-2026-10-15.json).
- [Boot inicial e limites](ios-own-runtime-early-boot-v13-2026-10-15.md).
- [Comparação do refresh](../artifacts/validation/ios-own-data-v2-headless-refresh-comparison-v1-2026-10-15.json).
- [Coleta de processos](../artifacts/validation/ios-own-data-v2-ui-process-metadata-v1-2026-10-15.json).
- [Varredura final](../artifacts/validation/ios-own-data-v2-raw-probe-after-ui-metadata-v1-2026-10-15.json).

Passaram 216 testes direcionados: 191 DATA-v2, 10 dos auxiliares de coleta,
6 do refresh e 9 do status de disponibilidade. `git diff --check` passou.
Trabalho local, sem commit, push, deploy ou promoção do provider iOS.
