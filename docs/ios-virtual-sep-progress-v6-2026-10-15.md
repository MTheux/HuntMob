# HuntMob VirtualSEP v1 — progresso v6, 2026-10-15

O motor agora contém um modelo criptográfico próprio, opt-in e desligado por
padrão. Ele não reproduz a derivação secreta do SEP físico da Apple. O contrato
é explícito: uma raiz aleatória de 32 bytes por VM, mantida no Keychain do Mac,
separação de domínios e contexto por VM no KDF, publicação das chaves pelo
caminho AESS/KEY e consumo opaco pelo ANS. Não se fornece Kwrap/Kauth prontos
como substitutos do SEP neste perfil.

**O iOS próprio ainda não está pronto.** O problema histórico de conteúdo em
texto claro não está encerrado: falta validar um arquivo protegido produzido
pelo próprio iOS, persistência, boot normal e bloqueio/desbloqueio. SpringBoard
e IPA não foram validados. Data Protection continua habilitada na compilação;
o helper normal exige o verificador original, sem substituir falhas por sucesso.

## Evidência obtida

- Candidato com diagnóstico de comandos: `ad89280f8b2f40903f73fc280710e0469900a8c2d9f57253a91fc235b5bf7d9d`.
  Predecessor funcional: `4df0bea8b459c48cd18dc4aa200a1ad547eb9f61669a3ca145a79b28b6d4b0ce`.
  Motor anterior do laboratório preservado: `dd379dbe74a05fd1a333ad70953bba919b2477fff3b1facd143b29702dcc0a25`.
- Provider: 144 verificações nativas com raízes públicas, incluindo oráculo
  independente HMAC/AES, latches, pares de contextos, revogação e duas banks.
  Esse teste isolado simula a descoberta QCryptoSecret, explicitamente.
- Dispositivos reais do t8030 pausado, usando QOM e MMIO via GDB físico local:
  28 completions, 49 comandos AESS e 15 rejeições NVMe. Producer AESS, UID e
  envelopes coincidem com oráculo independente. ANS grava dois setores XTS de
  4096 bytes, usando IV de arquivo diferente do LBA. O disco inteiro de 16 MiB
  coincide com o ciphertext esperado. Outro processo lê o mesmo conteúdo após
  rederivar/publicar os contextos. Nenhuma CPU/OS foi executada nesse teste.
  Recibo: `artifacts/validation/ios-virtual-sep-mmio-v1-2026-10-15.json`.
- QOM real carrega raiz pública por `/dev/fd/N`, com pipe de tamanho reportado
  zero e EOF, sem arquivo de chave e sem valor em argv. O getter `data` fica
  vazio. Falta de FD falha de forma limpa. O Keychain real passou criação,
  lookup em novo processo, preservação em criação duplicada e recusa de
  entrega em FD de arquivo/terminal. Os testes removem apenas itens próprios.
- Erasure: 361 verificações ASAN/UBSAN no corpo exato das funções de segredo,
  com cast/lookup QOM simulados; cópias observadas são zeradas antes de free.
  Isso não equivale a instrumentar toda a memória do motor em execução.

## Firmware real com identidade privada

Foi criado um conjunto novo de nove backings, sem clonar o antigo armazenamento
com chaves globais. O filesystem público foi copiado do IPSW verificado, com
readback idêntico, e GPT reconstruído para setores de 4096 bytes. O ASR host
falhou e não é apresentado como restauração concluída por ASR.

O boot revelou e permitiu corrigir requisitos anteriores ao SEP:

1. Identidade do helper de boot precisa ser `com.apple.seputil`; stock seputil
   e verificador original foram preservados por hash.
2. A imagem pública contém apenas System. Foram criados xART, Hardware e
   Preboot novos com o formatter original do iOS, nos slots 3/4/5. O slot 2
   temporário foi reservado e eliminado pelo seu UUID, para Data ser criado
   depois pelo iOS protegido. Nenhum Data antigo, keybag ou Gigalocker foi
   importado.
3. O formatter exige entitlement xART no processo pai. Apenas o bootstrap
   temporário recebeu `com.apple.private.apfs.xart=true`; ele terminou em
   checkpoint e foi removido, restaurando o wrapper sem entitlement extra.
   Nenhum check do formatter foi alterado.
4. O firmware público de Preboot foi copiado para o novo volume real e
   verificado. A inicialização original do Gigalocker concluiu.

Com a raiz privada real da VM, o firmware executou comandos UID aceitos:
`0x240 → 0x202 → 0x240 → 0x202 → 0x200`. O comando seguinte `0x211` foi
rejeitado pelo modelo; depois `0x20b` foi aceito. A observação terminou no
limite, sem boot SEP normal, sem SpringBoard e sem arquivo Data validado.
A categoria anterior “other” foi substituída por diagnóstico de comando,
KEYDISABLE, contador e resultado; nenhum buffer, seed ou chave é registrado.

O contrato de `0x211` precisa ser identificado no consumidor antes de uma
implementação: nenhum ACK vazio ou supressão do erro foi introduzido.

Um checkpoint offline dos nove backings, manifesto e trustcache foi preservado
antes de repetir a análise, mantendo a mesma identidade e item do Keychain.
O helper de restauração agora distingue iniciar um Gigalocker novo de retomar
um único Gigalocker do mesmo perfil; continua recusando múltiplos lockers e
Data existente na preparação inicial.

## Limites e entrega

Arquivos e candidatos são locais, sem commit, push ou ativação como runtime
pronto no HuntMob. Android, Apple Simulator e os discos anteriores não foram
alterados. O perfil experimental usa Keychain macOS; não estabelece suporte
Windows/Linux, Secure Boot/attestation equivalentes ao iPhone ou jailbreak.
