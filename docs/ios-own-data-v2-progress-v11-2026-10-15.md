# Armazenamento do perfil próprio DATA-v2 — v11, 2026-10-15

Atualização posterior: a leitura Class C após novo boot passou em `173327`.
Veja [persistência v12](ios-post-keybag-persistence-v12-2026-10-15.md).
Os resultados abaixo preservam o checkpoint anterior a essa validação.

**Confirmado:** a nova coorte criou e montou Data nativamente, inicializou
o systembag com retorno zero e completou escrita, fsync e leitura de uma
sonda Class C. A varredura integral dos nove backings não encontrou o
marcador público da sonda. A leitura em outro boot ainda está pendente.

Esta é uma implementação de identidade e política criptográfica próprias.
Não valida UID/KDF, semântica dos bits ANS, antirollback ou attestation do
hardware Apple. A associação nativa do contexto está descrita no
[progresso v10](ios-sep-ans-context-v10-2026-10-15.md).

## Contrato e isolamento

O engine `ed75f41e695f118a1038967322413278701f8cafbfbac513daca2012f9980f64`
oferece opt-in nominal `huntmob-virtual-data-profile=v2`. O perfil define
os dois formatos exatos autenticados `0x1b040` e `0x1b140` como AES-128-XTS,
par de 32 bytes, unidades de 4096 bytes e tweak `LE64 || zero64`.
O word original inteiro continua no MAC; outros formatos são recusados.
O perfil antigo mantém a recusa de DATA para `0x1b040`.

A coorte `9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4` tem nove backings novos e
raiz nova no Keychain, sem importar chaves ou discos antigos. O KDF continua
o modelo VirtualSEP.v1, com fonte pinada inalterada. O manifesto vincula
perfil, UUID, engine, fontes e inodes. Raiz não é transportada por Python,
argv ou arquivo; o helper nativo usa pipe privado. Data Protection permanece
ativa. A coorte anterior, seu Data parcial e seus checkpoints foram preservados.

## Resultados nativos

| Etapa | Observação | Resultado |
| --- | --- | --- |
| Auxiliares APFS | `155458` | xART/Hardware/Preboot: três exits zero, 4,67 s |
| Restore SEP original | `155657` | seis etapas com exit/signal zero, 85,40 s |
| Inicialização effaceable | `160427` | query 0 → formatter stock 0 → query 1, 3,26 s |
| Novo boot sem formatação | `160519` | formatted 1 persistente, nenhum WRITE em ns6, 56,35 s |
| Data e sonda Class C | `160837` | ClassD 0, MKBCreateSystem 0, write/fsync/readback, 87,34 s |

As observações pertencem exclusivamente à nova coorte. Cada etapa terminou
sem panic, rejeição AESS, erro NVMe ou recusa do gate protegido, com QMP quit
aceito e processo encerrado em zero. A etapa Data registrou 50.579 comandos
AESS aceitos e dez contextos de requisições autenticados. Isso não equivale
a SpringBoard ou execução de IPA.

O novo Data recebeu UUID `2F4BDE84-276C-414B-839A-2B2E996C1BF6` no produtor
newfs. A identidade e o estado host de criptografia devem ser conferidos
antes da instalação do verificador frio; Data não deve ser montado no host.

## Varredura e limites

Após flush/desligamento, a varredura leu **34.369.523.712 bytes** dos nove
backings, com hashes e verificação de identidade/mtime antes e depois.
Não encontrou o canário ASCII de 64 bytes nem os 32 bytes de origem do
canário. O scan durou 16,79 s. Não imprimiu dados de disco ou chaves.

O verificador frio deve conter somente o digest esperado da sonda; embutir
o canário no binário instalado em System contaminaria a própria medição.
Ele deve abrir somente o arquivo existente, sem create/truncate, verificar
UUID, APFS/CPROTECT, classe 3 e autenticação desde o boot, distinguindo uma
recusa legítima antes do primeiro unlock de uma falha após unlock.

Ainda faltam cold read, classes aplicáveis sob bloqueio/desbloqueio,
SpringBoard, tela/controles e IPA. O achado histórico de plaintext continua
aberto; `native_ready=false`. Nenhuma promoção de produto, distribuição,
commit ou push foi feita.

## Recibos

- `artifacts/validation/ios-native-sep-ans-context-v1-2026-10-15.json`
- `artifacts/validation/ios-ans-own-data-v2-controller-v1-2026-10-15.json`
- `artifacts/validation/ios-wrapped-reference-c-v2-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-native-auxiliary-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-native-sep-restore-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-effaceable-persistence-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-native-probe-v1-2026-10-15.json`

Os testes públicos do controlador exercitaram ambos os formatos, oráculo
XTS, adulteração do MAC/formato, bank não publicado, revogação, reset,
imutabilidade do perfil e recusa de configuração inválida. O codec passou
866 verificações C. Esses testes complementam as evidências nativas acima.

## Correções do provisionamento

QMP e USB usam diretório temporário privado com caminhos curtos, evitando
o limite de UNIX sockets do macOS. Lock ativo bloqueia adapters de host.
Checkpoint exige ausência de erros inclusive durante o drain final.

Quando `diskutil` omite `Mounted`, a validação exige ponto de montagem,
inventory, HFS e igualdade real do device do diretório com o block device;
`Mounted=False` contraditório é recusado. A preparação interrompida foi
preservada e a retomada usou uma nova cópia pública, sem reformatar SEP,
recriar a raiz ou alterar SecureRoot.
