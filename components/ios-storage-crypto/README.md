# Referência XTS de armazenamento — experimental

Este documento descreve o primeiro protótipo. O estado atual, incluindo o
decoder wrapped, o apagamento dos contextos Nettle e os limites do provider
SEP, está no [progresso v3](../../docs/ios-wrapped-storage-progress-v3-2026-10-15.md)
e no [lifecycle v4](../../docs/ios-sep-context-progress-v4-2026-10-15.md).

Implementação C da transformação **padrão** AES-128-XTS usando a implementação
QCrypto compilada no motor local. O CLI só executa vetores IEEE públicos e
fixtures sintéticas fixas; não recebe chaves, arquivos ou comandos de guest.
Não instala um controlador, habilita o modo ANS 0x08, desembrulha chaves ou
comprova Data Protection.

```sh
python3 components/ios-storage-crypto/build_selftest.py --authorized-synthetic-selftest
```

Requer o build local já existente em `~/.huntmob/research/Inferno/build-huntmob`,
compiler, GLib e Nettle compatíveis com seus objetos. Só escreve em
`build/ios-storage-crypto/`, produzindo `selftest` e `receipt.json`. Não recompila
o emulator, acessa backings ou inicia firmware.

## Contrato da primitiva

- AES-128-XTS: 32 bytes combinados, primeira metade K1/data, segunda K2/tweak.
- Tweak de 16 bytes. Na API de múltiplas unidades, encode LE64 do número
  explícito da unidade e complete com zeros; esse número **não é inferido de
  LBA**. Cada unidade de 4096 bytes recebe um novo tweak.
- Request de 1 a 256 unidades (máximo 1 MiB), sem overflow da sequência.
- Igualdade entre metades, parâmetros ausentes, comprimento inválido ou erro
  do provider rejeitam a operação. Saída só é copiada após sucesso completo.
- Bounce buffers próprios são limpos antes de free. A destruição do contexto
  expandido QCrypto não foi validada como zeroization; o provider atual usa
  `g_free`. Este protótipo continua restrito a material público/sintético.
- XTS fornece confidencialidade; não autentica ciphertext. Uma chave/tweak
  incorretos podem produzir plaintext incorreto sem erro criptográfico.

O teste IEEE de dois blocos foi obtido no source
[OpenSSL](https://github.com/openssl/openssl/blob/master/test/recipes/30-test_evp_data/evpciph_aes_common.txt).
O segundo oracle é um SHA256 calculado por cryptography/OpenSSL sobre duas
unidades sintéticas independentes. O caminho testado aqui é QCrypto/Nettle.

## Gate para futuro adapter ANS

Um adapter separado pode testar requests sintéticos unwrapped somente após
validar sua extensão de 64 bytes, IOSQE de 128 bytes, namespace com LBA 4096,
sem protection information/metadata estendida/FUSE/SGL, opcode read/write e
flags/contexto inequívocos. Deve rejeitar modo wrapped 0x04, modo desconhecido,
combinações incompatíveis e qualquer campo criptográfico sem contrato, antes
de alcançar block I/O. Nunca fazer fallback em claro para request protegido.

Ainda falta comprovar no firmware pinado qual metade da chave Apple é K1/K2,
qual campo fornece a unidade IV e como ela incrementa entre unidades. O padrão
não define o mapeamento a bytes de arquivo, extents ou blocos físicos. Dados de
reverse engineering do driver são candidatos a contrato; KAT da cifra não
os valida. Esses requisitos precedem conexão ao guest ou uso de chaves reais.

Referências: [Apple A9–A13](https://support.apple.com/guide/security/data-protection-overview-secf6276da8a/web),
[NIST SP 800-38E](https://csrc.nist.gov/pubs/sp/800/38/e/final),
[resposta do grupo IEEE hospedada no NIST sobre little endian](https://csrc.nist.gov/csrc/media/projects/block-cipher-techniques/documents/bcm/comments/xts/follow-up_xts_comments-ball.pdf).
