# Armazenamento iOS próprio — implementação v2 — 14/10/2026

Estado do produto: **bloqueado**. Alterações locais de pesquisa; nenhuma
publicação, instalação no worker ou declaração de suporte a IPA físico.

Etapa posterior: [wrapped e ciclo de vida v3](ios-wrapped-storage-progress-v3-2026-10-15.md).
Escopo fixado: Inferno `cc4302a99167abec69b714cfd00c38caece7e7de`,
t8030/n104ap, iOS 14.0 beta 5 / 18A5351d. Resultados não se generalizam a
outros modelos ou firmwares.

## Correção confirmada da associação do volume

O helper próprio confundia `MKBKeyBagCreateSystem` retornando `-4` (systembag
existente) com associação concluída. A análise do código original mostrou
que esse retorno não associa o volume ao bag. A versão atual interrompe a
preparação normal nesse estado e oferece um experimento explícito, restrito
ao firmware fixado, que chama a associação original.

O experimento exige build, módulo, fingerprints completos das duas funções
stock e filesystem com `MNT_CPROTECT`. Não carrega um bag substituto, não
desbloqueia o usuário e não modifica verificadores. A sonda existente é
aberta somente para leitura; a comparação escreve outro arquivo sintético
novo, criado atomicamente na classe C.

No clone exclusivo `native-storage-trace-20261014-map`, a associação original
terminou, a leitura do arquivo persistido de classe C passou, e o arquivo
novo completou escrita, fsync e leitura. Os nove backings permaneceram
idênticos após o boot com writes efêmeros. A tarefa de Data Protection não
falhou nesse ensaio; o boot ainda terminou em panic posterior.

Esse ensaio usou deliberadamente o engine anterior como controle negativo:
ele ainda permite I/O protegido em claro. Portanto comprova a correção da
associação no helper, **não** criptografia de armazenamento nem boot completo.
Evidências: [associação original](../artifacts/validation/ios-class-c-stock-association-v1-2026-10-14.json),
[comparação anterior sem associação](../artifacts/validation/ios-class-c-fresh-comparison-v1-2026-10-14.json).

## Recusa de I/O protegido sem implementação

O candidato `22092b277d5a5c7c64ef68e9ce476a60a145d3aa72dab72dd76314ebe366faef`
recusa read/write Apple ANS com flags wrapped, unwrapped e contraditórias
antes do backend/DMA. Seis operações reais do controlador em um guest
baremetal sintético foram recusadas com `0x4002`, preservando DMA e o arquivo
de disco inteiro. Operações claras e o controlador NVMe genérico passaram.
O controle negativo aceitou as mesmas operações e gravou texto claro.

No boot próprio com esse guard, o driver recebe a recusa e Data Protection
permanece bloqueada. Esse é o comportamento esperado enquanto a transformação
wrapped não existe. Não se deve remover a recusa para apresentar um boot
como protegido.

Evidências: [guard real](../artifacts/validation/ios-ans-guard-integration-v1-2026-10-14.json),
[controle negativo](../artifacts/validation/ios-ans-baseline-integration-v1-2026-10-14.json),
[boot com guard](../artifacts/validation/ios-ans-guard-boot-v1-2026-10-14.json).

## AES-XTS: primitiva e integração experimental

O componente `components/ios-storage-crypto` usa o backend QCrypto/Nettle
real e passou known-answer tests e comparações independentes com dados
públicos sintéticos, incluindo duas unidades de 4096 bytes. Isso valida a
primitiva padrão; não valida o formato de chave wrapped do firmware.
[Recibo da primitiva](../artifacts/validation/ios-xts-reference-v1-2026-10-14.json).

O patch `ans-lab-unwrapped-xts.patch` acrescenta um caminho experimental
desativado por padrão (`apple-ans-lab-unwrapped-xts=false`). Aceita somente
chave explícita sintética no descritor de 128 bytes, flags exatas `0x08`,
unidades de 4096 bytes e pedidos limitados a 1 MiB. Rejeita modos wrapped,
combinações, formatos e recursos não implementados. Leituras só chegam ao
DMA após a transformação; escritas usam um buffer separado antes do backend.

A escolha padrão K1/K2 e tweak LE64 continua hipótese de ABI Apple; esse
caminho não é habilitado em nenhum laboratório iOS. A limpeza dos buffers
temporários não comprova apagamento dos contextos expandidos do backend.
A integração do controlador foi executada pelo agente e repetida pelo root
no candidato `fca97c588704b09166f066836fbab6a8cbd7fb2caf2ddaa9bcb0ccc8ba31dcd3`:

- 68 comandos reais: oito com propriedade omitida, 55 com opt-in e cinco
  num novo processo usando o mesmo disco temporário de 16 MiB.
- Ciphertext de duas unidades coincide byte a byte com o oracle independente
  `cryptography`; o IV de arquivo difere do LBA físico.
- Leitura protegida recupera os 8192 bytes. O segundo processo recebe a chave
  sintética explicitamente novamente e apenas lê; o disco inteiro permanece
  idêntico ao resultado esperado.
- 24 pedidos inválidos recusados, com comparação de todo o DMA e leitura do
  backing após cada recusa: wrapped, combinação, extensão inválida/ausente,
  metadados, controle, SGL/FUSE, limite e overflow, entre outros.
- O guard padrão e NVMe genérico também passaram novamente no candidato final.

O ensaio encontrou e permitiu corrigir um erro real: namespace normal sempre
possui endurance group; a validação precisa exigir FDP desativado, não a
ausência desse ponteiro. Outro patch preserva status de abort após limpeza,
mas esse cancelamento foi revisado apenas estaticamente, sem ensaio de timing.

[Build final](../artifacts/validation/ios-ans-unwrapped-build-v1-2026-10-14.json),
[integração real](../artifacts/validation/ios-ans-unwrapped-integration-v1-2026-10-14.json),
[guard padrão final](../artifacts/validation/ios-ans-unwrapped-default-guard-v1-2026-10-14.json).

## Observação da ligação SEP/AES

O mesmo candidato inclui instrumentação categórica adicional, sem chaves,
registradores, selectors, IVs ou buffers no trace. No clone próprio exclusivo
`native-storage-trace-20261014-keyline`, foram observados 102 comandos AP AES,
17 seleções de chave software e 17 retornos de cipher iguais a zero.
No KEY_BASE do SEP, foram observadas seis escritas de controle; nenhum evento
de LOAD/SEND apareceu nos pontos instrumentados. Quatro pedidos wrapped foram
recusados pelo guard e o boot parou em Data Protection.

Isso confirma que pelo menos o caminho de controle dessa região MMIO foi
exercitado; não confirma a disponibilidade de uma wrapping key nem ausência
de outras interfaces de hardware. Todos os nove backings foram verificados
inalterados depois da execução efêmera, e os logs ficaram dentro dos limites.
[Observação](../artifacts/validation/ios-sep-aes-keyline-observation-v1-2026-10-14.json).

## Validação e continuidade

268 testes Python passaram; o build, os ensaios NVMe e a observação acima
foram executados. O engine original full-SEP foi verificado inalterado, e o
worker existente continuou com Android online, iOS Simulator ligado e 500
flows preservados. A API continua reportando runtime próprio bloqueado.

O [gate JEV local](../artifacts/validation/ios-jev-readiness-gate-v2-2026-10-14.json)
recusou declarar conclusão a partir desse estado. Nenhum modelo remoto ou
executor de desktop foi acionado. Recompilar o engine é parte do ciclo de
implementação; recompilar um IPA sem código-fonte não converte ABI de device
em ABI de Simulator.

## Bloqueio restante

Falta implementar e validar a ligação interna SEP → AES de armazenamento e
o processamento do blob wrapped usado pelo firmware. A notificação AP de
wrapping ativo não contém essa chave. Não existe autorização técnica para
adivinhar o layout do blob ou trocar a proteção por cifra do arquivo da VM.

Depois dessa integração, continuam necessários: auditoria persistente e
reinicialização, lock/unlock e revogação, boot até SpringBoard, tela/entrada,
instalação de IPA autorizado e validação dos controles. Nenhum recibo desta
etapa permite `ready=true`.
