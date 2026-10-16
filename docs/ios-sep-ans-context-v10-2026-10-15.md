# Contexto SEP → ANS no modelo próprio — v10, 2026-10-15

Continuação: [Data nativo e scan do perfil próprio v11](ios-own-data-v2-progress-v11-2026-10-15.md).

**Confirmado:** o firmware SEP em execução no modelo de identidade própria
produziu envelopes que o ANS autenticou e desembrulhou pelo caminho nativo.
Isso valida a associação de contexto desse modelo; não valida a derivação UID,
o SEP ou a semântica de cifragem do hardware Apple.

## Causa e correção

O boot `observation-20261015-152107` identificou o word de formato autenticado
`0x0001b040`, com os doze bytes reservados zerados, nos quatro pedidos/retries
protegidos. O codec anterior aceitava exclusivamente `0x0001b140`.

A análise do produtor pinado confirmou que o word inteiro participa do MAC
e é transportado intacto pelo controlador ANS2. O caminho alternativo ANS2CG
com TCB separado não estava ativo. O codec agora admite exclusivamente esses
dois words, autenticando o valor original, sem máscaras ou normalização.
O formato é armazenado na requisição somente após autenticação e apagado
junto com a chave no término. Falhas não liberam plaintext.

O patch `ans-authenticated-envelope-data-gate.patch` mantém uma segunda
condição: o formato novo ainda é recusado para DATA no perfil antigo, antes
do mapeamento da transferência ou da submissão ao backend. Autenticar um
envelope não estabelece por si só o algoritmo DATA do hardware.

## Evidência nativa

No candidato `41963e2e3704bdae2d15f02d060a6f5ed6266f4d47b95c5aaabc9cc28160cda8`,
o boot `observation-20261015-153514` apresentou quatro resultados
`sq-context=accepted`, incluindo retries de dois CIDs. Todos foram seguidos
por `protected-gate=data-format-unsupported`, conforme o contrato do perfil
antigo. A raiz Keychain, o KDF, os nove backings e Data Protection foram
preservados. Nenhum byte de chave, MAC ou ciphertext foi exportado.

O volume não montou e o processo terminou em panic depois da recusa de DATA;
o launcher aceitou QMP quit. Portanto, esse boot comprova autenticação e
associação do contexto, não funcionamento do armazenamento protegido.

Recibos públicos:

- `artifacts/validation/ios-native-wrapped-format-v1-2026-10-15.json`
- `artifacts/validation/ios-native-sep-ans-context-v1-2026-10-15.json`
- `artifacts/validation/ios-ans-authenticated-format-data-gate-v1-2026-10-15.json`

O último recibo exercita dispositivos reais do modelo com CPUs pausadas e
fixtures públicas: ambos os envelopes correspondem ao oráculo independente;
alterar `0x100` sem novo MAC é recusado em ambas as direções; formato
desconhecido com MAC válido também é recusado. O formato legado mantém
write/read e ciphertext esperado. Todos os nove backings, DMA guards,
flush e desligamento foram conferidos. Isso não substitui o ensaio nativo.

## Próxima implementação

Um perfil nominal experimental DATA-v2 define sua própria política:
ambos os formatos exatos autenticados usam AES-128-XTS, par de 32 bytes,
unidades de 4096 bytes e tweak `LE64 || zero64`. Essa definição é do emulador
próprio, sem alegar que o bit `0x100` tem esse significado no hardware Apple.
Exige opt-in, manifesto versionado, identidade nova, nove backings novos e
vínculo ao engine compilado. Nenhuma migração implícita do perfil antigo.

Antes de qualquer promoção, faltam testes do perfil, criação APFS nativa,
write/fsync/unmount, scan do canário, cold read e revogação/bloqueio.
O Data parcial anterior e os checkpoints permanecem preservados.

**Ainda pendentes:** armazenamento protegido persistente validado,
SpringBoard, tela/controles, IPA e pentest iOS no runtime próprio. O achado
histórico de plaintext continua aberto e `native_ready=false`.
Mudanças locais, sem commit, push, deploy ou distribuição.
