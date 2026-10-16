# HuntMob OwnMPE v1 — progresso v7, 2026-10-15

O modelo experimental agora possui um consumidor real para os comandos ROM
`0x211/0x251`. Os dois inputs são carregados e latched antes da configuração
das regiões; o comando AESS `0x200` preserva esses latches. As cargas não são
tratadas como um ACK sem consumidor. O perfil permanece opt-in, com identidade
própria, e não reproduz a criptografia ou attestation do SEP físico da Apple.

## Implementação

- O core próprio deriva uma chave por região com SP800-108/HMAC-SHA256,
  usando ambos os inputs, VM ID, salt novo por boot, epoch e limites físicos.
  Cada linha de 64 bytes recebe AES-256-GCM, tag completa e geração esperada
  em estado privado. Falha de autenticação, limite ou contador invalida o
  cache; reset apaga inputs, ciphertext, tags, gerações e plaintext temporário.
- O SEP recebe caches ROMD privados e executáveis. Stores normais passam
  pelo callback de criptografia; a visão AP e a visão física completa de TZ0
  retornam ciphertext ou erro. Escritas externas são recusadas. A janela
  privada é limitada ao prefixo configurado, com erro no restante.
- Um bypass de callback na atualização automática de page tables foi
  corrigido: `arm_casq_ptw` não usa host atomic direto em um ponteiro obtido
  por leitura ROMD. O probe de escrita stage 2 original é preservado antes
  do desvio para o dispositivo. Stage 2 foi revisado por código; não foi
  ensaiado com um guest EL2 neste marco.
- O estado de memória retido/warm resume ainda não tem protocolo
  criptográfico implementado. Não se aceita estado de replay desconhecido.
  Isso é diferente de executar o firmware SEP de restauração em cold boot.

Host administrador, debugger e registradores SEP pertencem ao TCB. Não existe
proteção contra um administrador lendo o processo. Não há um bloqueio genérico
completo de dumps QMP. Migração/snapshot permanecem bloqueados para o perfil.

## Evidência

- Core congelado: 1.409 verificações C e 200 comparações independentes com
  HMAC/AES-GCM; ASAN e UBSAN sem diagnóstico. A biblioteca Nettle do sistema
  não foi recompilada com sanitizers. Recibo:
  `artifacts/validation/ios-virtual-mpe-core-v2-2026-10-15.json`.
- CPU SEP real do t8030 executou fixtures públicas pela janela privada:
  load/store, LDAXR/STLXR, alteração de código com nova execução e Access
  Flag de page table em ROMD. Uma segunda escrita na mesma linha confirma
  que a alteração permanece no estado canônico cifrado. As visões AP e
  física TZ coincidem e não expõem o código privado. Escritas AP não alteram
  essas visões. Nenhum firmware foi executado nesses fixtures.
- O defeito de AF foi reproduzido no predecessor `97b1b8f8969a0a8b`:
  AF aparecia no cache, mas sumia após RMW da mesma linha. O mesmo fixture
  passa com o guard PTW. Recibos `ios-virtual-mpe-af-prepatch-v1`,
  `ios-virtual-mpe-cpu-stores-v3` e `ios-virtual-mpe-cpu-af-v3` em
  `artifacts/validation`, datados de 2026-10-15.
- A regressão dos controladores AESS/KEY/ANS passou com 28 completions,
  escrita cifrada, leitura em processo novo e rejeições sem modificar disco
  ou DMA. Recibo `ios-virtual-sep-mmio-v2-mpe-2026-10-15.json`.
- Benchmark do core isolado no M4 Max: inicializar 32 MiB levou 68,7 ms;
  84 MiB, 108,6 ms; 1 MiB em stores de 8 bytes, 29,8 ms. Esses tempos não
  incluem TCG, callbacks ROMD, invalidar código ou boot. Não medem a fluidez
  do produto. Pico RSS de 292,2 MiB.

## Firmware privado e limite atual

O cold boot com raiz privada real no Keychain aceitou `0x211` e `0x251` e
inicializou 32 MiB primários e 83,75 MiB secundários. A primeira observação
de 60 segundos terminou por limite, sem panic ou rejeição MPE observados,
mas também sem `SEP/OS is alive`, checkpoint de restauração ou interface.
Observação: `observation-20261015-121653` no cohort privado
`virtual-sep-v1-52c79047-1d89-4a97-bf6b-cc2d6b9d742c`.

O candidato com contadores de progresso de memória é
`b9b41572fa03c920b50c519888a3a1a02040a88addb64da0f5a1f4ae0b02f218`.
Os contadores registram apenas região, fase e número de bytes escritos;
nenhum payload, seed, chave ou tag é registrado.

A observação seguinte, `observation-20261015-122049`, confirmou a transição
para firmware privado e a mensagem original `SEP/OS is alive`. O firmware
executou as sequências de derivação/publicação `201/205/281/204` e
`241/245/2c1/244`, todas aceitas pelo modelo. Não houve fault de memória MPE.
O AP fez panic por `boot task failure: data-protection` aos 71,65 segundos.
Isso não demonstra uso bem-sucedido das chaves pelo filesystem.

O helper anterior armava um timer de 60 segundos em cada processo stock;
seu primeiro comando começou aproximadamente 9 segundos após a VM e a
falha coincidiu com esse limite. Timeout é uma hipótese forte, ainda sem
status de término do filho naquela execução. Um wrapper novo, compilado
com o mesmo identificador e sem entitlement extra, registra somente opção
fixa e exit/signal, permitindo 150 segundos para `--restore+art` e 60 nas
outras chamadas. O motor externo continua limitado a 180 segundos. O
verificador stock e o Gigalocker da mesma identidade são preservados.

Com o prazo corrigido, `observation-20261015-122454` concluiu as quatro
operações de restauração/erase/commit/nonce, mas `gigalocker-shutdown`
retornou exit 202. Esse byte não determina sozinho o IOReturn completo.
A análise do utilitário original confirmou que o init precisa registrar
o pathname no kernel a cada boot, inclusive quando o arquivo já existe.
O helper pulava esse registro ao retomar. Foi corrigido para chamar o
utilitário stock, conferir o alias `/mnt7` e exigir o mesmo nome, device,
inode e tamanho antes/depois para o arquivo existente. Isso não implica
que o kernel não atualize conteúdo do arquivo durante o registro.

O novo boot `observation-20261015-123505` chegou ao checkpoint de
restauração em 89,67 segundos: init, restore+art, erase, commit-hash,
new-nonce e shutdown retornaram zero. SEP ativo, nenhum panic ou fault MPE,
QMP encerrou e descarregou os discos. Um checkpoint offline com onze
clones independentes e hashes/readbacks foi preservado antes de preparar
Data; nenhuma raiz do Keychain foi exportada. Recibo público limitado:
`artifacts/validation/ios-virtual-sep-native-restore-v1-2026-10-15.json`.

Data Protection continua habilitada e o verificador original não foi
substituído por sucesso. Ainda falta um arquivo protegido produzido pelo iOS,
persistência, boot normal, bloqueio/desbloqueio, SpringBoard e IPA. O problema
histórico de plaintext persistente permanece aberto. Alterações somente
locais, sem commit, push, distribuição ou promoção do runtime no HuntMob.
