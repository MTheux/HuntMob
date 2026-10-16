# Protocolo ANS do laboratório iOS — v1 — 2026-10-14

Escopo: inspeção estática do KernelCache autorizado iOS 14.0 beta 5,
build 18A5351d, n104ap/t8030, e teste de controlador em fixture própria.
Nenhum firmware, ROM, kernel ou checkpoint existente foi alterado.
A inspeção usou símbolos e instruções ARM64 do LLVM; Ghidra está disponível,
mas não foi necessário para estes métodos curtos. Não atribuir este resultado
à execução do REA/Ghidra.

Continuidade: [implementação v2](ios-storage-implementation-v2-2026-10-14.md)
inclui guard, integração raw-XTS desativada por padrão, testes reais do
controlador e observação posterior da ligação SEP/AES. Wrapped permanece
sem implementação validada.

Em 15/10, o [progresso v3](ios-wrapped-storage-progress-v3-2026-10-15.md)
acrescenta framing e decoder wrapped testados em fixture; a origem do contexto
no SEP nativo permanece bloqueada. As seções abaixo preservam a análise anterior.

## Proveniência

- KernelCache IM4P SHA256: `cfb260879625327b06d5549abc42a84daa86bebf6a894403aad7633ee94148a3`.
- Mach-O descomprimido SHA256: `524b91442ad73a225f8b86afbed26642fbc14a821647d972d3c52dfc4c431910`.
- Extração IM4P e LZFSE em diretório novo:
  `~/.huntmob/research/ans-abi-20261014/`.
- `protocol-evidence.json` registra hashes dos 16 trechos de disassembly;
  nenhuma chave de VM, buffer privado ou payload capturado foi registrado.

## Confirmado: o opcode 0xd8 não estabelece criptografia

`AppleNVMeRequest::BuildCommandTunnel(unsigned char, unsigned long long,
unsigned long long, unsigned int)` em `0xfffffff009340374` constrói o opcode
`0xd8` com CDW10 = primeiro argumento, CDW11–12 = segundo argumento,
CDW13–14 = terceiro argumento e CDW15 = quarto argumento.

`AppleNVMeController::ProcessTunnelCommand` em `0xfffffff00933c564` passa
modo 1, endereço físico do buffer de entrada, endereço físico opcional do
buffer de saída e tamanho de saída. Há chamadas a partir de métodos de NAND,
tempo do dispositivo, QoS e tabelas ANS. Trata-se de um transporte genérico.
Não há evidência suficiente para tratar as três chamadas observadas no boot
como preparação de keyslot ou transferência de chave.

## Confirmado: enquadramento de I/O protegido

Métodos inspecionados:

| Método | Endereço |
| --- | --- |
| `BuildCommandReadStruct(NVMeRWCommand*)` | `0xfffffff00933f878` |
| `BuildCommandWriteStruct(NVMeRWCommand*)` | `0xfffffff00933faa8` |
| `IONVMeController::SetSQEntry` | `0xfffffff009333c50` |

Os textos de assertion no próprio binário identificam `securityMode`,
`wrapped` e comprimentos de chave. Os métodos read/write usam a mesma lógica:

| Campo da estrutura do driver | Offset | Comportamento confirmado |
| --- | --- | --- |
| Ponteiro do material de chave | `0x30` | Fonte da extensão de criptografia |
| Comprimento | `0x38` | 32 para unwrapped; 64 para wrapped |
| `wrapped` | `0x39` | Verificado pelas assertions de comprimento |
| Unidade do offset usado como IV | `0x40` | `(bufattr_cpoff + adjustedOffset) >> 12`, copiado para comando NVMe `+0x38` |
| `securityMode` | `0x48` | Zero não acrescenta o marcador; valores 1–3 acrescentam marcador |

Quando `securityMode != 0`, o primeiro dword recebe `0x400` para wrapped
ou `0x800` para unwrapped. `NvmeCmd` é packed: opcode no byte 0, flags no
byte 1. Logo, o marcador é `cmd.flags & 0x0c`: `0x04` wrapped, `0x08`
unwrapped. A combinação `0x0c` é contraditória e deve ser recusada.

A extensão tem 64 bytes após o comando NVMe de 64 bytes:

- Unwrapped de 32 bytes: primeiro u32 zero; material de 32 bytes na extensão `+0x20`.
- Wrapped de 64 bytes: u32 inicial em `+0`; 16 bytes de origem `+0x10` em extensão `+0x10`; 32 bytes de origem `+0x20` em extensão `+0x20`.

`SetSQEntry` copia comando para SQ e extensão para SQ `+0x40`. O caminho
CG também copia a extensão para TCB `+0x40`. O controlador deste Inferno
usa `NVME_SQES=7` (entradas de I/O de 128 bytes), mas `nvme_process_sq`
consome apenas `sizeof(NvmeCmd)=64`; a extensão protegida é ignorada.
Não interpretar o u32 inicial como keyslot sem evidência adicional.

## Confirmado: contexto wrapped e unidade do IV

O driver `IOEmbeddedNVMeBlockDevice::doAsyncReadWrite` verifica
`cpx_is_sep_wrapped_key` e exige `cpx_use_offset_for_iv` antes da rota
wrapped inline. Em `0xfffffff009317508` obtém o blob com `cpx_key`;
em `0xfffffff009317514`, comprimento com `cpx_key_len`.

Entre `0xfffffff009317520` e `0xfffffff009317530`, deriva:

```text
crypto_unit = (bufattr_cpoff(buffer_attributes) + storage_attributes.adjustedOffset) >> 12
```

Atribui wrapped no campo `+0x39` e `securityMode=1` em `+0x48`.
A unidade derivada é de 4096 bytes de offset de arquivo ajustado; não é
necessariamente o LBA físico. Os getters CPX do próprio kernel confirmam
flag SEP_WRAPPEDKEY=1 e USE_OFFSET_FOR_IV=4, coerentes com o
[código XNU 7195 publicado pela Apple](https://github.com/apple-oss-distributions/xnu/blob/xnu-7195.50.7.100.1/bsd/vfs/vfs_cprotect.c#L261).
O [VFS Apple](https://github.com/apple-oss-distributions/xnu/blob/xnu-7195.50.7.100.1/bsd/vfs/vfs_bio.c#L1419) descreve a propagação do offset de arquivo até o driver NAND.
`adjustedOffset` no [IOStorageAttributes público](https://github.com/apple-oss-distributions/IOStorageFamily/blob/main/IOStorage.h#L268) está no offset `0x10`, coerente com a instrução do driver. Esses snapshots públicos corroboram a leitura do binário; não são o código proprietário exato do driver desta beta.

A [documentação Apple de Data Protection](https://support.apple.com/guide/security/data-protection-overview-secf6276da8a/web) especifica AES-128-XTS para A9–A13, com chave por arquivo de 256 bits dividida em duas partes de 128 bits. Esta é evidência da família do algoritmo do A13; não valida a ordem das metades, a codificação do tweak nem o unwrap do blob de 64 bytes deste firmware. O campo de 16 bytes do blob não foi demonstrado como nonce, IV ou tag de autenticação.

## Confirmado: origem opaca do blob wrapped

`AppleKeyStore::fs_unwrap_key` (`0xfffffff008f65150`) e
`fs_unwrap_ek` (`0xfffffff008f66520`) encaminham a solicitação para
`unwrap_data` (`0xfffffff008f685b8`). Este seleciona
`__ipc_unwrap_pfk_data_v1` (`0xfffffff008f761c0`) ou
`__ipc_unwrap_pfk_data_v2` (`0xfffffff008f763c8`). O wrapper v1 envia o
opcode de callback 9. O codec `_code_ipc_unwrap_pfk_data`
(`0xfffffff008f7c334`) serializa/deserializa blobs; não executa o
unwrap criptográfico do conteúdo de 64 bytes em código AP.

`_return_ek` (`0xfffffff009093758`) propaga a resposta `aks_raw_key_s`:

| Campo da resposta externa | Offset | Destino confirmado |
| --- | --- | --- |
| Ponteiro do buffer | `0x00` | Deve corresponder ao destino `cpx_key` |
| Comprimento recebido | `0x08` | `cpx_set_key_len`, após limite de capacidade |
| Flags de resposta | `0x1c` | Bit 0 define `cpx_set_is_sep_wrapped_key` |

A função ativa `cpx_set_use_offset_for_iv(..., true)`. Esses offsets são
da estrutura externa da resposta AKS, não do interior do blob de chave.
Não demonstram que o u32 no início do blob seja keyslot, nem que os
16 bytes sejam nonce/tag. Não há evidência suficiente para decompor
64 bytes como RFC3394 de 40 bytes mais cabeçalho de 24 bytes.
O algoritmo e os campos dessa embalagem permanecem na fronteira SEP/AES
e precisam de contrato próprio, independente da cifra XTS de dados.

## Confirmado: notificação de wrapping e próximo entrypoint

A enumeração dos símbolos visíveis deste KernelCache não encontrou métodos
AP-facing `import_wrapping_key`, `get_wrapping_key` ou `change_wrapping_key`
nos controladores NVMe/SEP. Isso não exclui funções inlined, símbolos ausentes
ou uma linha dedicada interna ao SoC.

`AppleSEPControl::_cmsgAction` (`0xfffffff008b4c0ac`) despacha mensagens
de endpoint 0/tag 0 pelo opcode nos bits 16–23. A tabela de nove entradas
a partir de `0xfffffff008b4c2e8` identifica opcode `0x10` como destino
`0xfffffff008b4c264`, que chama
`AppleSEPManager::notifyWrappingActive` (`0xfffffff008b5ab30`).
Este método atualiza a propriedade `IsWrapping` e notifica estado booleano;
não transporta um buffer de wrapping key na chamada AP-facing.

Ambos os wrappers PFK v1 e v2 passam o callback opcode 9. Esse caminho
KEYS/KeyStore é o próximo entrypoint comprovado para produzir o blob de
chave de arquivo. `wrapping_key_*` do APFS opera sobre keybags; seu nome
não estabelece uma transmissão da chave efêmera ao AES inline.
Não foi confirmada uma rota alternativa SSKG/MONI/NVM para tal transmissão.

A [descrição Apple do AES Engine](https://support.apple.com/en-gb/guide/security/sec59b0b31ff/web) informa que a transferência SEP → motor AES ocorre por linhas dedicadas, indisponíveis para software fora do SEP. Portanto, a presença da notificação `0x10` pode comprovar readiness declarada pelo SEP, mas não comprova que a emulação implementou essas linhas ou carregou o motor de armazenamento. O opcode PFK 9 define o caminho do blob; não define a ABI interna da wrapping key.

## Correção defensiva implementável e testada

`components/ios-engine/ans-storage-protected-io-guard.patch`, incremental
após stage 2, recusa READ/WRITE com esses marcadores apenas quando
`is-apple-ans=true`, antes do mapeamento DMA e do backend. Retorna
`NVME_INVALID_FIELD | NVME_DNR` (`0x4002`). O evento de trace expõe apenas
queue/cid/opcode e modo 1, 2 ou 3. Nenhuma extensão ou chave é lida.

Este guard impede o fallback silencioso para plaintext no enquadramento
identificado. Não implementa criptografia e não estabelece proteção de todas
as variantes possíveis do firmware. O runtime continua indisponível.

`python3 scripts/verify_ans_protected_io.py --authorized-lab --engine <binary>`
compila fixture ARM64 própria com clang/llvm-objcopy, inicializa PCI e filas
NVMe em um novo QEMU virt e usa exclusivamente disco sintético temporário
de 16 MiB. Não depende de qtest (ausente neste Inferno).

Resultado confirmado em execução:

- Binário guard: clear WRITE/READ funcional; seis solicitações protegidas
  (READ e WRITE, wrapped/unwrapped/contraditória) recusadas com `0x4002`;
  buffer DMA inteiro de 4096 bytes preservado e backing exatamente preservado.
- Binário anterior `300d1e63f75e345b...`: mesmo teste com `--baseline`
  aceita as seis solicitações e grava plaintext sintético.
- Controle `is-apple-ans=false`: comportamento NVMe genérico preservado;
  solicitações com os mesmos flags continuam aceitas.
- Backing guard SHA256: `3674994cadaa78c15b4d968486cd67334c8f849de69b66d0ab806a536e53e653`.
- Backing baseline SHA256: `51bffe139fd504b154e4bff9730afc5f404b6f768cdc5a2e3e4e7c735ead20f1`.

## Ainda não confirmado

A codificação do tweak e a ordem das metades AES-128-XTS, validação do blob
wrapped, transporte de wrapping keys do SEP, keyslot/tag/revogação e vetores
independentes. A ausência de transferência
SEP no boot observado não prova que não exista em outros caminhos. A sonda atual no baseline sem guard reportou `first_unlock_state=1`,
metadata classe 3 e recusa de abertura readonly do arquivo. O estado observado
descarta apenas a hipótese de nunca ter ocorrido primeiro unlock nesse
contexto; não comprova disponibilidade de todas as chaves ou defeito do AES.
Evidência: [sonda readonly classe C](../artifacts/validation/ios-class-c-readonly-baseline-v1-2026-10-14.json).
A recusa de acesso não deve ser atribuída a este protocolo sem reprodução
independente.

Próxima implementação depende desses contratos; adicionar AES genérico ou
reclassificar sucesso do stub `0xd8` como criptografia não resolve o problema.

Referências primárias: [Inferno no commit inspecionado](https://github.com/ChefKissInc/Inferno/tree/cc4302a99167abec69b714cfd00c38caece7e7de),
[Linux apple NVMe](https://github.com/torvalds/linux/blob/master/drivers/nvme/host/apple.c),
[m1n1 NVMe](https://github.com/AsahiLinux/m1n1/blob/main/src/nvme.c),
[Apple — Secure Enclave e AES no caminho DMA](https://support.apple.com/en-gb/guide/security/sec59b0b31ff/web).
