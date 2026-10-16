# Contexto SEP → ANS — v4 — 15/10/2026

Continuação: [reset e transporte no controlador, com falhas reproduzidas e corrigidas — v5](ios-context-reset-progress-v5-2026-10-15.md).

Estado: **ciclo de vida implementado em componente independente; derivação e
associação nativas ainda sem validação**. Alterações locais, sem commit,
push ou deploy. Firmware de pesquisa: iOS 14.0 beta 5 / 18A5351d,
t8030/n104ap. O runtime próprio permanece indisponível.

## O que foi implementado

`components/ios-storage-crypto/ans_context_lifecycle.c/.h` mantém um par
sintético completo sob QemuMutex. Inicia indisponível; begin invalida e apaga
o par anterior, stage copia os 64 bytes juntos e publish exige a mesma
geração. Uma lease contém somente proprietário e geração. Revogação/reset
invalidam leases anteriores; overflow do contador encerra permanentemente
o contexto. Destroy recusa contextos com leases pendentes e exige que o
chamador já tenha parado os demais usuários.

Validação e callback ocorrem sob o mesmo mutex. Uma verificação seguida de
ação fora do mutex permitiria revogação no intervalo. Os callbacks só podem
executar trabalho curto, limitado e sem bloqueio, alocação ou reentrada.
O codec QCrypto executa fora desse lock: copia-se temporariamente o par sob
lock, faz-se unwrap e apaga-se a cópia. A mesma lease precisa ser validada
novamente junto da ação final. Não adquirir BQL/AioContext dentro do callback;
o chamador precisa respeitar a ordem de locks documentada no header.

O componente ainda **não está conectado ao controlador nem ao SEP**. A API
de stage é explicitamente sintética. Não mapeia controles KEY para arrays
de AESS, não importa chaves do host e não calcula uma KDF presumida.
Revogar não desfaz escritas já submetidas: drain/barreiras de I/O continuam
pendentes para a futura integração assíncrona.

## Verificação independente do root

- Harness nativo do lifecycle: 60 verificações, 5.000 publicações concorrentes,
  25.022 callbacks coerentes nesta execução, sem par misturado. Revogação
  concorrente só conclui após o callback protegido; leases antigas falham.
  O gancho para semear o contador em testes está ausente do objeto normal.
- Composição com o codec C/QCrypto real: 592 verificações determinísticas.
  Revogação após unwrap e antes de submissão/cópia final impede o callback;
  reset também impede a entrega. Par novo recusa lease/envelope antigos,
  e MAC inválido não chega à cópia final. Sentinelas permanecem intactas
  nas recusas e a cópia temporária do contexto é apagada.
- Os sentinelas desse segundo ensaio são **arrays locais**, não disco,
  controlador ou DMA físico. A contagem inclui verificações byte a byte;
  não representa 592 cenários independentes de iOS.
- 89 testes Python `test_ios_*.py` passaram, incluindo os novos testes de
  parsing. Texto desconhecido e `validated=1` no trace nunca promovem readiness.

[Lifecycle](../artifacts/validation/ios-ans-context-lifecycle-v1-2026-10-15.json),
[codec + lifecycle](../artifacts/validation/ios-ans-context-codec-v1-2026-10-15.json).

## Boot observado no candidato novo

O patch `sep-derivation-readiness-diagnostics.patch` acrescenta somente um
evento de metadados: fase, função classificatória e `validated=false`.
Não muda comandos, status, buffers ou contexto; não registra chaves,
nonces, bancos, payloads ou valores dos registradores. O build preservou
Data Protection e as opções wrapped/raw de laboratório desligadas por padrão.

Candidato: `cdca8412aba2eadff2708bfb2274157225d5b92c3f674e9da5b125b8f0da2179`.
Build anterior preservado; o engine original não foi substituído.

O root executou um clone exclusivo, sem rede e com escritas efêmeras,
limitado a 30 segundos. O engine encerrou em 14,60 segundos com panic
observado e falha de Data Protection. A auditoria posterior confirmou os
nove backings idênticos aos hashes anteriores; os logs ficaram no limite.

| Evento classificado | Ocorrências |
| --- | ---: |
| Programação de wrapping | 2 |
| Derivação não implementada de wrapping | 2 |
| Programação de autenticação | 2 |
| Derivação não implementada de autenticação | 2 |
| Seleção wrapping / autenticação / subkey | 2 de cada |
| Pedidos wrapped recusados pelo guard ANS | 4 |

As duas sequências observadas seguem programação → derivação ausente para
wrapping, programação → derivação ausente para autenticação, depois três
seleções. Esses nomes classificam o caminho do inicializador. Não demonstram
qual slot interno é transferido por cada controle KEY nem validade da chave.
O contador de erro AESS permanece zero porque o upstream sinaliza DONE mesmo
para esses comandos sem implementação; esse DONE não é evidência criptográfica.

[Build vinculado às fontes](../artifacts/validation/ios-sep-derivation-build-v1-2026-10-15.json),
[observação nativa](../artifacts/validation/ios-sep-derivation-observation-v1-2026-10-15.json).

## Fronteira que ainda impede a implementação nativa

O inicializador envia os pares MMIO `0x201→0x205` e `0x281→0x204`
para o primeiro contexto, e os respectivos comandos do segundo contexto.
O firmware analisado escreve os registradores e espera o hardware; não
implementa em software a transformação matemática dos comandos ausentes.
O caminho de reconfiguração AESSEP reutiliza contextos em cache; o startup
SKG gera novos contextos via TRNG. Não equiparar reconfiguração e criação
de nova geração, nem nomear o callback como reset/resume sem provar o caller.

O [upstream fixado](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/sep.c)
continua com XOR provisório na programação e TODO nas operações seguintes.
A investigação de histórico identificou sua introdução no
[commit original](https://github.com/ChefKissInc/Inferno/commit/03a55cbad4dd0610ab1d46467f4f0b0b150a4a9b);
os materiais examinados não forneceram um oracle compatível. Isso não prova
que inexista uma especificação em outra fonte.

A [documentação Apple](https://support.apple.com/guide/security/the-secure-enclave-sec59b0b31ff/web)
descreve chaves internas ao AES do SEP e transporte dedicado ao AES de
armazenamento, mas não especifica a matemática desses comandos. Um KAT
AES-CBC/XTS genérico não valida essa fronteira.

Para substituir a implementação provisória é necessário obter uma
especificação dos comandos e da origem dos controles KEY, um modelo
independente compatível, ou uma referência autorizada com entradas públicas
e método de comparação definido. Roundtrip contra o próprio placeholder
não atende esse requisito. Depois continuam pendentes associação nativa,
revogação/drain reais, persistência APFS, lock/unlock, SpringBoard e IPA.

Histórico anterior: [progresso v3](ios-wrapped-storage-progress-v3-2026-10-15.md).
