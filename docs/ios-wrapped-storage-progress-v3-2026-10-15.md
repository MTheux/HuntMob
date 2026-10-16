# Armazenamento wrapped iOS — v3 — 15/10/2026

Continuação: [contexto SEP → ANS, diagnóstico no boot e lifecycle v4](ios-sep-context-progress-v4-2026-10-15.md).

Estado: **decoder e NVMe wrapped validados em fixture; contexto SEP nativo bloqueado**.
Alterações locais de pesquisa, sem commit/push/deploy. Firmware fixado em
iOS 14.0 beta 5 / 18A5351d, t8030/n104ap. Esta etapa não habilita o runtime
próprio para clientes nem instala IPA.

## Ciclo de vida das chaves: implementação e teste

O backend Nettle anterior liberava os contextos expandidos com `g_free`, sem
apagá-los. O patch `crypto-nettle-context-erasure.patch` adiciona destrutores
por tipo concreto: apaga toda a alocação, incluindo schedules de encrypt e
decrypt, chave de tweak XTS e IV, com stores volatile antes de liberar.
Não calcula tamanho a partir do tipo base e não altera a transformação.

O teste nativo compila o backend QCrypto real, instrumentando o allocator
somente nessa unidade de compilação. Inspeciona a alocação ainda viva antes
de chamar o allocator original; não lê memória liberada. O agente executou
o teste e o root repetiu independentemente:

- 46 combinações de algoritmo/modo; matriz de ciphertext idêntica ao baseline.
- 138 alocações/liberações: baseline 0/138 apagadas; patch 138/138 apagadas.
- Seis modos incompatíveis recusados e falhas de comprimento exercitadas.
- Nenhum erro de tracking; nenhum caminho de construtor libera contexto já
  preparado fora dos destrutores revisados.

O resultado cobre os contextos heap do Nettle. Não comprova apagamento de
stack/registers, outros backends ou revogação no SEP.
[Recibo](../artifacts/validation/ios-nettle-context-erasure-v1-2026-10-15.json).

## Cancelamento assíncrono: validação real

`scripts/verify_ans_io_abort.py` inicia um QEMU virt separado, sem rede, com
disco sintético temporário de 16 MiB. Uma leitura inicial ocupa o orçamento
do backend limitado por throttling; o guest publica uma leitura raw-XTS e
envia Abort por outra fila enquanto ela está pendente.

O controlador retorna `NVME_CMD_ABORT_REQ` (`0x0007`), preserva os 8192 bytes
do buffer DMA e mantém o disco inteiro idêntico. Esse ensaio valida
dinamicamente o caminho que antes havia sido revisado apenas estaticamente.
Não é um teste de revogação de keybag ou de acesso depois de lock do iOS.
[Recibo no candidato final](../artifacts/validation/ios-ans-async-abort-v2-2026-10-15.json).

## Build e regressão do caminho de dados

Candidato final desta rodada:
`45a7b5345de8ad1bceef6b8c53dd793aede1656b8d835cbed876d5bb5d25e075`.
Mantém a fonte de Data Protection fixada e o modo raw-XTS desativado por
padrão. O engine original e os experimentos anteriores são preservados.

Os 68 comandos reais do teste raw-XTS foram repetidos: cifra de duas unidades
4 KiB contra oracle independente, leitura original, novo processo no mesmo
disco sintético e 24 recusas com DMA/backing preservados. Os 268 testes Python
também passaram nessa etapa. Após a integração wrapped, passaram 269 testes.
[Build](../artifacts/validation/ios-crypto-lifecycle-build-v2-2026-10-15.json),
[NVMe](../artifacts/validation/ios-ans-unwrapped-integration-v3-2026-10-15.json).

## Produtor do envelope: fronteira confirmada

A extração dos apps SEP foi corrigida para reconstruir TEXT e DATA separados
pela tabela original do firmware. A cópia contígua anterior incluía regiões
do app seguinte como se fossem DATA. A análise atual usa esses segmentos e
os fixups de ponteiros, em projeto Ghidra privado, sem executar firmware
modificado ou exportar chaves.

No app `sks`, a entrada PFK de callback 9 chega à cadeia:

```text
0x10c6c → 0x2ab44 → 0x2a7e8 → 0x2a524 → 0x2a578
        → 0x311fc → 0x40318 → 0x40200 → serviço skgs, RPC 0x4e22
```

O wrapper fixa comprimento de entrada 32 e capacidade de saída 64. A rotina
`0x40200` constrói um pedido de 72 bytes: byte de comprimento em `+0`, modo
em `+4` e dados em `+8`; retorna o comprimento e os dados da resposta após
validar a capacidade. Esse caminho é separado da rotina `0x29c68`, que
produz wrap de 40 bytes. A função `0xe7ec` é predicado de classe, não um
ponteiro de contexto criptográfico — a passagem de registradores foi
conferida em instruções para evitar inferência errada do decompilador.

Esse transporte aceita até a capacidade informada, e não exige sozinho
comprimento final 64. A análise seguinte chegou ao handler SKG
`0x155dc → 0x14050 → 0x13238`, que configura AESS: RPC `0x4259=4`,
`0x4260=0x1b140`, `0x4258=5`. O resultado de 64 bytes e seu layout foram
estabelecidos no handler de leitura AESS `0xf2fc`, não inferidos da capacidade.

## Envelope e transformação reconstruídos

A operação 5 executa os comandos MMIO `0x206 → 0x8 → 0x88`. Compondo o
código original que programa esses comandos com as operações implementadas
no modelo fixado, o resultado é:

```text
C32  = AES-256-CBC(Kwrap, IV zero, DEK32)
T16  = último bloco de AES-256-CBC(Kauth, IV zero, C32 || zero12 || flagsLE32)
blob = flagsLE32 || zero12 || T16 || C32
```

O handler de leitura monta o cabeçalho, os 16 bytes finais da operação e o
ciphertext de 32 bytes cacheado. Isso identifica o framing e a composição do
modelo virtual. Não valida a derivação das chaves no hardware físico nem
substitui um roundtrip do firmware real. O caminho de wrap de 40 bytes é
distinto e não foi usado como implementação desse envelope.

Implementei `wrapped_reference.c/.h`, com autenticação antes de expor a chave,
campos reservados canônicos, comparação de tag sem saída antecipada, flag
restrita a `0x1b140` e temporários apagados. O root repetiu as 410 verificações
C contra oracle independente: framing, roundtrip, adulterações em todos os
64 bytes, comprimentos, autenticação, saída preservada e unwrap in-place.
[Contrato estático](../artifacts/validation/ios-wrapped-envelope-contract-v1-2026-10-15.json),
[teste C](../artifacts/validation/ios-wrapped-envelope-c-v1-2026-10-15.json),
[duas referências independentes](../artifacts/validation/ios-wrapped-envelope-reference-v1-2026-10-15.json).

## Integração wrapped no controlador

O patch `ans-lab-wrapped-xts.patch` integra o decoder ao caminho real NVMe de
teste, com opções independentes e desativadas por padrão. Um QCryptoSecret
explícito contém o par de contexto sintético; ele não é configurado no t8030
e não representa transporte ou persistência protegida pelo SEP.

Candidato final após essa integração e instrumentação dos roles:
`de3b13817f7cef9c52be3ff7ad5071cafa7a3e4bbc8279677a83b1ab34d95f66`.
O agente executou e o root repetiu 112 comandos reais em discos temporários
sintéticos de 16 MiB:

- Contexto correto: 59 comandos e cinco em novo processo, com ciphertext
  comparado byte a byte ao oracle e leitura dos dados originais.
- 26 operações adversariais na fase correta, incluindo adulteração de frame,
  SGL/FUSE e flags contraditórios; DMA e backing preservados após cada recusa.
- Modo padrão desligado, contexto ausente, autenticação/par incorretos e
  contextos de 63/65 bytes recusados por requisição.
- O teste raw de 68 comandos, o guard padrão e o abort assíncrono também
  passaram novamente nesse binário.

Limite criptográfico explícito: trocar somente Kwrap, preservando Kauth,
não é detectável por esse envelope; a integridade do par precisa ser garantida
pelo futuro provider. O secret sintético permanece carregado após reset do
controlador. Isso não comprova revogação de contexto SEP.
[Build final](../artifacts/validation/ios-wrapped-candidate-build-v1-2026-10-15.json),
[wrapped NVMe](../artifacts/validation/ios-ans-wrapped-integration-v1-2026-10-15.json),
[regressão raw](../artifacts/validation/ios-ans-raw-regression-v1-2026-10-15.json),
[abort](../artifacts/validation/ios-ans-wrapped-candidate-abort-v1-2026-10-15.json).

O recibo de build agora vincula explicitamente o hash dos arquivos revisados,
incluindo os arquivos novos que ainda não aparecem em `git diff`. O teste de
regressão modifica um codec untracked após o build e confirma que a validação
recusa o candidato apesar do diff vazio.

## Observação adicional do hardware

O patch `sep-key-control-categories.patch` observa somente famílias de
controle, sem valores de registradores, selectors, payloads ou chaves.
No clone exclusivo `native-storage-trace-20261015-key-control`, as seis
escritas foram classificadas como `other`, fora das famílias de inicialização
da ROM que o teste reconhece. Não houve LOAD/SEND nos pontos instrumentados.
Isso não estabelece uma transferência alternativa nem autoriza mapear o
bloco FKEY em endereço presumido.

O guard recusou quatro pedidos wrapped; o boot parou em Data Protection.
Os nove backings permaneceram idênticos e os logs ficaram dentro dos limites.
[Observação](../artifacts/validation/ios-sep-key-control-observation-v1-2026-10-15.json).

Depois de demonstrar os roles no código SEPD, a classificação foi ampliada e
executada em outro clone: duas seleções de wrapping, duas de autenticação e
duas de subkey. Portanto, a rota de seleção foi efetivamente observada. Esses
comandos não recebem bytes de chave: selecionam contextos previamente
derivados. Não interpretar a última janela KEY de entrada como esse contexto.
O boot continuou bloqueado no guard e os nove backings ficaram inalterados.
[Roles no boot nativo](../artifacts/validation/ios-native-key-role-observation-v1-2026-10-15.json).

## Gates que continuam pendentes

O bloqueio principal agora é a origem do contexto: a inicialização usa TRNG,
labels separados e comandos AESS `0x201/0x205/0x281/0x204` para o banco
primário. O modelo atual copia entrada e aplica XOR com placeholder; os
comandos normalizados 4/5 não possuem a derivação implementada. Não promover
esses slots a provider nativo, nem substituir as chaves por valores do host.

Faltam derivação e associação SEP/ANS validadas, reset/revogação e vetores
independentes do firmware. Depois vêm persistência APFS/SEP, lock/unlock, boot completo,
SpringBoard e instalação de IPA autorizado. Todos os recibos mantêm
`ready=false`; os testes raw e de apagamento não satisfazem esses gates.
