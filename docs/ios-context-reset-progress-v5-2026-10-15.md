# Reset e transporte do contexto experimental — v5 — 15/10/2026

Estado: **duas falhas corrigidas na controladora experimental e verificadas em
execução; derivação/associação nativas SEP → ANS continuam sem validação**.
Alterações locais, sem commit, push ou deploy. Os laboratórios Android e
Apple Simulator não foram reiniciados.

## Falhas reproduzidas antes da correção

O candidato anterior `cdca8412aba2eadff2708bfb2274157225d5b92c3f674e9da5b125b8f0da2179`
recarregava o contexto sintético do mesmo QCryptoSecret a cada requisição.
Resetar o controlador não invalidava essa autorização. O novo harness
`scripts/verify_ans_wrapped_reset.py` reproduziu três resultados incorretos:

1. Wrapped READ após CC.EN=0 e recriação das filas retornava sucesso.
2. Wrapped WRITE também retornava sucesso e alterava o backing temporário.
3. Uma leitura protegida comprovadamente pendente na entrada do reset
   entregava plaintext por DMA enquanto `nvme_ns_drain` processava callbacks.
   O teste confere sentinela e ordem submit → entrada do reset → completion;
   não presume que o pedido ainda esteja pendente apenas por usar um timer.

Separadamente, `scripts/verify_ans_protected_dma.py` mostrou que PRP1 apontando
para o UART MMIO do **guest virt** era aceito em raw e wrapped e alterava o
disco descartável. `nvme_tx` ignorava o MemTxResult dos helpers DMA; verificar
somente residual não detecta esse tipo de falha. Nenhum host MMIO, dispositivo
físico, IPA, imagem iOS ou dado de cliente foi usado nesses ensaios.

[Baseline de reset](../artifacts/validation/ios-ans-wrapped-reset-baseline-v1-2026-10-15.json),
[baseline de DMA](../artifacts/validation/ios-ans-protected-dma-baseline-v1-2026-10-15.json).

## Implementação no caminho real NVMe

Novo patch incremental: `components/ios-engine/ans-lab-reset-revocation-ram-dma.patch`,
SHA256 `db8d861fba0a073b3637f31654ba51a88c7f5dabcaa8f653941de065e350be63`.
Não modifica patches anteriores, firmware, Data Protection ou `nvme_tx` genérico.

- Geração por controlador e snapshot por requisição. Reset invalida a geração
  **antes** de drenar o backend. Completion antiga é abortada e não decripta
  nem copia plaintext para o guest.
- O reset inicial anterior ao primeiro EN bem-sucedido permite o primeiro uso
  da fixture. Depois de uma sessão ativa, o contexto wrapped fica revogado;
  reativar CC.EN não o autoriza novamente. Um novo processo/device pode
  carregar explicitamente a fixture pública de novo. Não existe rearm nativo.
- Raw continua independente: depois do reset, uma nova requisição com chave
  pública explícita recebe a geração atual. Overflow da geração recusa o uso.
- Todos os segmentos de dados são verificados como RAM comum antes do backend,
  inclusive para READ, e novamente antes da cópia final. MMIO, memória não
  mapeada, RAM device, ROM e caminhos CMB/PMR sem contrato são recusados.
- A transferência usa `attrs.memory=true`, verifica MemTxResult e residual;
  `address_space_access_valid` sozinho não aplica essa restrição de memória.
  Erro de transporte preserva `NVME_DATA_TRAS_ERROR`, sem transformá-lo em
  erro de mídia. Não há mutex mantido através de DMA.

O controle de geração acompanha o modelo atual de main loop/AioContext do
NVMe. O componente standalone do v4 não foi conectado artificialmente ao
firmware. Um provider SEP em outra thread e suporte a IOThread exigem um
protocolo de publicação próprio. Revogação não desfaz writes já submetidos;
o drain aguarda esses pedidos. O QCryptoSecret público continua sendo um
objeto do host, e não uma prova de apagamento ou custódia de chaves SEP.

## Resultado no candidato corrigido

Candidato `b813e98421b550ef3257ca64582fcc0322c7023e5741dec934feb011866151cb`.
Build anterior preservado junto às suas dependências; engine original intacto.
Data Protection continua ativa e os modos experimentais continuam desligados
por padrão. O root compilou e executou os ensaios:

| Verificação | Resultado confirmado |
| --- | --- |
| Reset seguido de wrapped READ/WRITE | Ambos recusados com `0x4002`; backing preservado |
| READ pendente na entrada do reset | Aborted `0x0007`; 8192 bytes de DMA preservados |
| Nova leitura raw após reset | Aceita com chave pública explícita; plaintext esperado |
| MMIO/unassigned no primeiro ou segundo PRP, READ/WRITE, raw/wrapped | 16 pedidos recusados com `0x0004`; sentinelas e backing inteiro preservados |
| Regressão wrapped | 112 comandos, incluindo novo processo, passaram |
| Regressão raw | 68 comandos passaram |
| Abort assíncrono | Status `0x0007`, sem entrega de DMA e sem alteração do disco |
| Guard padrão e NVMe genérico | Guard Apple preservado e fluxo genérico inalterado |
| Testes Python iOS | 90 testes passaram |

Os testes NVMe usam processos virt sem rede e discos temporários de 16 MiB,
com ciphertext comparado a oracle independente. O ensaio de DMA inclui uma
primeira página válida e segunda inválida para detectar cópia parcial antes
da recusa. Não valida remapeamento concorrente de IOMMU, VF/SR-IOV ou provider
SEP. As contagens de comandos não são cenários independentes de iOS.

[Build](../artifacts/validation/ios-ans-reset-ram-build-v1-2026-10-15.json),
[reset corrigido](../artifacts/validation/ios-ans-wrapped-reset-fixed-v1-2026-10-15.json),
[DMA corrigido](../artifacts/validation/ios-ans-protected-dma-fixed-v1-2026-10-15.json),
[wrapped](../artifacts/validation/ios-ans-wrapped-reset-regression-v1-2026-10-15.json),
[raw](../artifacts/validation/ios-ans-raw-reset-regression-v1-2026-10-15.json),
[abort](../artifacts/validation/ios-ans-abort-reset-regression-v1-2026-10-15.json),
[guard](../artifacts/validation/ios-ans-guard-reset-regression-v1-2026-10-15.json).

## Boot nativo e estado do produto

O mesmo candidato foi executado em outro clone exclusivo do checkpoint de
pesquisa iOS 18A5351d, sem rede e com escritas efêmeras. Encerrou em 14,60 s
com panic/falha de Data Protection. Os nove backings permaneceram idênticos.
As quatro chamadas de derivação sem implementação continuam observadas,
seguidas da seleção dos contextos; quatro pedidos wrapped continuam recusados
pelo guard. Nenhum provider SEP foi ligado e nenhum gate foi promovido.

O relatório local de disponibilidade agora identifica derivação/associação
SEP/ANS como bloqueio, com data 15/10/2026. O histórico da validação que
encontrou texto claro permanece aberto. O código do status foi atualizado;
o serviço em execução não foi recarregado. Simulator ativo não equivale a
runtime próprio pronto.

[Observação nativa](../artifacts/validation/ios-native-reset-ram-observation-v1-2026-10-15.json),
[status local](../artifacts/validation/ios-native-runtime-status-v1-2026-10-15.json).

## Investigação da derivação: KAT público delimitado

Foi encontrada uma referência primária adicional: os testes AES-SKG do
[corecrypto da Apple, em commit fixado](https://github.com/apple/corecrypto/blob/9612a959abb6eac0aac3ee6a7245c46365c9d81b/cc_fips/src/fipspost_post_aes_skg.c).
As constantes públicas coincidem com os testes de startup SKS no firmware
18A5351d analisado. O rastreamento estático desses testes chegou a SKG
`0x4e84`, carregamento explícito de chave AESS `0x20b` e CBC `0x89/0x8a`.
Esse caminho não passa por `0x205/0x204` nem pelos controles KEY 4/5.
Portanto, não é uma referência para a derivação ou associação faltante.
Não foram invocados testes no device nem copiados os vetores para o projeto.

Continua necessário estabelecer a transformação dos comandos AESS e a origem
dos controles KEY por referência independente antes de implementar a associação
nativa. Depois faltam persistência APFS/SEP, lock/unlock, SpringBoard e IPA.
Histórico: [v4](ios-sep-context-progress-v4-2026-10-15.md).
