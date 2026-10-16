# Contrato de Data Protection do runtime próprio — v1 — 14/10/2026

Status: **bloqueado**. A revisão deste documento é read-only; a equipe executou
posteriormente os boots bounded em clone exclusivo descritos abaixo.
Escopo: guest próprio n104ap/t8030 (iPhone12,1), firmware de pesquisa iOS
14.0 beta 5 / 18A5351d. Não é uma declaração de compatibilidade com outros
firmwares. Revisão do motor local: Inferno
`cc4302a99167abec69b714cfd00c38caece7e7de`.

Continuidade em 15/10: o [progresso v3](ios-wrapped-storage-progress-v3-2026-10-15.md)
registra o formato do envelope reconstruído, decoder C e 112 comandos wrapped
em fixture. A derivação e associação do contexto SEP nativo continuam pendentes.

Atualização posterior: a [implementação v2](ios-storage-implementation-v2-2026-10-14.md)
registra a correção experimental da associação do systembag, o guard contra
I/O em claro, 68 comandos do protótipo raw-XTS e a observação AP AES/SEP KEY.
O suporte a chaves wrapped e a prontidão do runtime continuam bloqueados.

## O que já foi observado

O [registro de validação](ios-normal-sep-validation-v1-2026-10-14.md)
documenta chamadas stock de preparação do SEP, associação APFS/MobileKeyBag
e escrita/fsync/leitura de arquivo sintético com classe C. A
[auditoria persistente](../artifacts/validation/ios-storage-audit-v1-2026-10-14.json)
registrou nove backings estáveis e coincidentes com o receipt; o canary foi
encontrado em claro em `namespace-1.raw`. Portanto a evidência atual reprova
proteção de conteúdo persistido. A ausência do canary, isoladamente, também
não seria prova de uma implementação correta.

O boot histórico chegou à tarefa mount-phase-2 e terminou com exit 66. Não há
SpringBoard ou instalação/abertura de IPA comprovados no runtime próprio.

## Contratos ausentes no motor

| Componente | Evidência de código no commit revisado | Contrato ainda necessário |
| --- | --- | --- |
| ANS t8030 | [`t8030.c`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/t8030.c#L1287) chama `apple_ans_from_node` | Mapear a ABI do controlador deste firmware, inclusive descritores e seleção de contexto criptográfico |
| Vendor MMIO | [`ans.c`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/block/apple-silicon/ans.c#L122) guarda writes em array; cria `TYPE_NVME` com `is-apple-ans` | Executar os efeitos definidos do hardware, não apenas ecoar registros |
| I/O NVMe | [`ctrl.c`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/nvme/ctrl.c#L1464) encaminha read/write por DMA ou block I/O; propriedade `is-apple-ans` só aparece na declaração neste arquivo | Transformar buffers no caminho correto, com keyslot/contexto, unidade e IV/tweak definidos pela ABI; não aplicar cifra genérica a todo o disco |
| SEP AESH / HDCP | [`sep.c`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/sep.c#L3042) trata comando como desconhecido, limpa ACTIVE e sinaliza completion; interrupt/PMGR identificam AES_HDCP | Limitação confirmada de HDCP, sem evidência de participação na criptografia de armazenamento; não tratar esse stub como causa ANS |
| SEP AESC | [`sep.c`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/sep.c#L3206) copia bytes de registros | Identificar sua função efetiva e ligação com o caminho de armazenamento; presença de um bloco de registros não prova execução |
| AESS keywrap | [`sep.c`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/sep.c#L2461) contém TODO explícito de correção do algoritmo | Vetores independentes de wrap/unwrap e semântica correta para comandos usados; não inferir sucesso pela ausência de panic |
| Modelo legado | [`nvme_mmu.c`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/block/apple-silicon/nvme_mmu.c#L124) comenta incrypto/outcrypto tags | Esses comentários não estabelecem a ABI do ANS t8030 ativo e não são uma implementação |

Os stubs SEP acima são limitações confirmadas em code review. AESH é marcado
como AES_HDCP pelo próprio source e não comprova ausência de cifra ANS.
Seu papel exato
na escrita que produziu o canary em claro permanece **precisa validar**. Não
foi estabelecido que substituir um desses handlers isoladamente corrigiria
o boot ou a criptografia.

## Ciclo esperado e limites de emulação

A documentação Apple descreve chaves por arquivo/extent, protegidas por
classes, entregues ao AES Engine que atua no caminho entre memória e
armazenamento. O SEP possui uma ligação dedicada com esse motor. Uma
implementação virtual precisa preservar essas relações e os estados de
disponibilidade; FileVault do host ou criptografia do arquivo da VM não
reproduzem as classes do guest. Fontes: [Data Protection](https://support.apple.com/guide/security/data-protection-in-apple-devices-sece8608431d/web)
e [Secure Enclave](https://support.apple.com/guide/security/the-secure-enclave-sec59b0b31ff/web).

O contrato de implementação precisa definir, com evidência deste firmware:

1. ABI de programação/remoção de contexto e seleção por operação ANS.
2. Relação entre chaves embrulhadas, slots do AES Engine e acesso autorizado
   pelo SEP. Identificadores podem ser registrados; bytes de chaves não.
3. Modo de cifra, tamanho/unidade de dados, endianess e derivação de IV/tweak.
4. Separação entre conteúdo protegido, metadados e operações sem contexto.
5. Tratamento de reset, slot inexistente/removido, erro, conclusão e flush.
6. Persistência coerente do conjunto de namespaces/SEP NVRAM/SSC e prevenção
   de migração ou snapshots que façam um slot revogado reaparecer.

Estas são exigências de projeto, não protocolos já identificados. Não se deve
preencher lacunas com AES/XTS/CBC arbitrários ou valores de retorno de sucesso.

### AESS: derivação UID não é o wrap do controlador NVM

O handler `aess_keywrap_uid` consome e produz 32 bytes. As operações normalizadas
`0x02`/`0x12` selecionam chaves virtuais UID e um contador, mas o source inclui
XOR do contador na chave e XOR de seed bits como aproximações. Esse nome de
função não demonstra uma implementação RFC 3394: o wrap padrão de 32 bytes
de material de chave gera 40 bytes, conforme [RFC 3394](https://datatracker.ietf.org/doc/html/rfc3394).

O [Security Target Apple iOS 14 publicado pela NIAP](https://www.niap-ccevs.org/MMO/Product/st_vid11147-st.pdf),
seção 8.3.1.1, descreve PBKDF2-HMAC-SHA256 seguido por encriptações repetidas
AES-CBC-256 com UID fixo, produzindo 256 bits. A descrição indexada foi lida;
o download direto retornou conteúdo sem assinatura PDF nesta revisão.
Ela apoia a família de derivação CBC, mas **não especifica** initial IV,
carry/reset de IV entre repetições, zero iterations, derivação por seed bits
ou mapeamento MMIO t8030. Não justifica substituir o XOR por uma hipótese
de firmware compatível.

Separadamente, a [política Apple corecrypto SKS publicada pelo NIST](https://csrc.nist.gov/CSRC/media/projects/cryptographic-module-validation-program/documents/security-policies/140sp4756.pdf),
Table 9, identifica wrap pelo NVM storage controller e unwrap/re-wrap da DEK
como AES-KW. Trata de ambientes iOS 14.2/sepOS do módulo especificado,
não de uma validação do ABI iOS 14.0 beta 5/t8030. A evidência não deve ser
fundida com as operações de derivação AESS de 32 bytes nem com o TODO que
especula CMAC em metade da saída.

Um componente isolado pode implementar CBC-256 sem padding com key/input/IV
e quantidade explícitos, repetir ciphertext como próximo input e manter uma
política explícita de carry/reset de IV. Os known-answer tests
[NIST SP 800-38A F.2.5/F.2.6](https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-38a.pdf)
comprovam a primitiva CBC e seu chaining dentro da mensagem; não fornecem
vetores UID t8030 nem selecionam a política entre repetições de comandos.
Até existir esse contrato, tal componente permanece isolado e não deve
alterar boot, seed bits, contador ou receipts existentes do motor.

Foi executada a [referência local da primitiva](../artifacts/validation/ios-aess-primitive-reference-v1-2026-10-14.json),
com os vetores públicos F.2.5/F.2.6: encrypt, decrypt e streaming em duas
partes passaram; oito comparações de repetição sintética (1/2/10/32 rounds,
carry/reset de IV) concordaram entre cryptography 44.0.3 e PyCryptodome 3.23.0.
As duas políticas de IV produzem saídas diferentes já em dois rounds. Isso
demonstra por que a família CBC não basta para escolher a ABI de repetição.
Nenhum material criptográfico do guest foi lido/exportado, nem engine
alterado. Os testes genéricos passaram; os gates de hardware e armazenamento
continuam falsos.

## Próximo experimento bounded

O experimento útil é **observação de metadados do caminho ativo**, com binário
instrumentado separado, em clone exclusivo do guest de pesquisa. Não é
repetir o mesmo boot sem hipótese nova nem alterar o checkpoint existente.

Registrar somente contadores e metadados allow-listed: classe/estado da
sonda própria, categoria do comando SEP, offset MMIO do controlador, opcode
NVMe, namespace, bloco/tamanho e contexto opaco quando conhecido. Valores de
registro, blobs, DMA buffers, keybags, chaves, nonces e payloads não entram
no log. Primeiro comparar escrita da sonda com e sem contexto observado;
nenhum desses resultados autoriza `ready=true`.

Pré-condições: caminhos exclusivos, hashes da origem, nenhum hardlink/symlink
para backings compartilhados, firmware/engine pinados, limite de tempo e
bytes de log, QMP privado, desligamento/flush e auditoria read-only posterior.
O resultado deve localizar uma sequência concreta de programação de contexto
e I/O ou registrar explicitamente que ela não foi observada. A instrumentação
não modifica firmware/ROM/kernel, verificadores, flags de proteção ou dados
do host. Os resultados da execução pela equipe estão na seção seguinte.

## Observação real do cold boot — clone exclusivo

Foram lidos independentemente os receipts e log do clone
`~/.huntmob/research/ios-vms/native-storage-trace-20261014/`:

- `trace-receipt.json`: engine SHA256 iniciado por `d77879c9`, patch diagnóstico
  iniciado por `123912d3`, 28,62 s de observação, writes efêmeros e backings
  inalterados conforme receipt. 2693 submissões e 2693 completions, todas com
  status NVMe `0x0000`; 18 acessos vendor MMIO; três admin opcodes `0xd8`
  atendidos pelo caminho não implementado; zero eventos no ponto de trace de
  transferência SEP. Não atribuir semântica criptográfica a `0xd8`.
- `boot.log`: o verificador stock terminou; Data foi montado; MobileKeyBag
  informou que o systembag já existia. Seguiu-se
  `apfs_unwrap_key: AKS unwrap_key failed, error = e00002e2`, encerramento do
  helper e panic de boot task data-protection, antes de novo roundtrip C.
- `disk-boot-20261014-220707.json`: comparação com engine baseline SHA256
  iniciado por `dd379dbe`, 14,03 s, `-snapshot`, sem novo patch do firmware;
  também registra `failed-data-protection`, panic e nenhum SpringBoard/IPA
  validado. Não é um sucesso de cold boot ou prova de nova criptografia.

Zero eventos significa **nenhum evento observado nos pontos instrumentados**,
não inexistência universal de transferências. Completion NVMe OK, saída 0 do
processo do motor e verificador stock completado não substituem o resultado
da tarefa de boot.

O código `0xe00002e2` corresponde a `kIOReturnNotPermitted` no header IOKit
local e no [source Apple XNU](https://github.com/apple-oss-distributions/xnu/blob/main/iokit/IOKit/IOReturn.h).
É uma recusa; o código isolado não diferencia bloqueio esperado, contexto
ausente, direitos insuficientes ou falha do modelo de keys.

Uma hipótese concorrente precisa ser preservada: o helper de preparação
abre o arquivo **existente** `.huntmob-protection-probe` com
`O_CREAT | O_TRUNC | O_RDWR` antes de autenticação do usuário no cold boot.
Esse arquivo havia sido atribuído à classe C. A política correta de classe C
pode recusar unwrap antes do primeiro unlock. O log atual não marca a syscall
exata nem o estado do keybag, portanto não comprova que a falha seja corrupção
de chave ou perda de um slot ANS. Alterar a classe para D ou ignorar esse erro
não seria uma validação equivalente.

O reset do motor limpa estado volátil AESS e SSC
([`sep.c:4434`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/sep.c#L4434),
[`sep.c:5599`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/sep.c#L5599));
o handler SSC de leitura de metadados recarrega seu material persistido para
o slot interno
([`sep.c:5429`](https://github.com/ChefKissInc/Inferno/blob/cc4302a99167abec69b714cfd00c38caece7e7de/hw/arm/apple-silicon/sep.c#L5429)).
Limpar estado volátil no reset, por si só, não estabelece um bug: é necessário
verificar se o protocolo de reconstituição/reautorização é acionado e correto.

Próxima hipótese bounded: instrumentar apenas marcadores da operação da
sonda e estados públicos permitidos de locked/unlocked/first-unlock, e
contadores/opcodes SSC de inicialização/leitura, sem payloads ou chaves.
Separar a operação de preparo inicial em guest vazio da verificação de
arquivo persistido após autenticação stock. O diagnóstico deve distinguir
recusa esperada antes do unlock, reconstrução de contexto faltante e erro
real de unwrap após unlock, mantendo a recusa e `ready=false`. Nenhuma dessas
hipóteses corrige a evidência independente de plaintext no backing original.

### Marcadores subsequentes: hipótese de pre-unlock não sustentada

Foi lido o log do clone exclusivo
`native-storage-trace-20261014-helper-baseline/boot.log`: `first-unlock state 1`,
`persisted probe protection class 3`, e recusa de open **read-only** com
Operation not permitted, acompanhada do mesmo erro AKS `0xe00002e2`.
Portanto a explicação anterior de apenas tentar ler antes do primeiro unlock
não corresponde ao estado público observado. Esse boolean não comprova que
o contexto individual da classe/DEK foi reconstruído corretamente. A próxima
investigação precisa distinguir estado público de unlock de unwrap/reconstituição
da chave persistida, sem revelar material de chave ou transformar a recusa
em sucesso.

### Componente XTS padrão implementado e testado

O novo [componente isolado](../components/ios-storage-crypto/README.md) utiliza
o objeto `crypto_cipher.c.o` efetivamente compilado no build QEMU/Nettle
existente. É uma implementação C de transformação AES-128-XTS, com request
limitado a unidades de 4096 bytes, número de unidade explícito, commit de
output somente após sucesso integral, e rejeição de parâmetros inválidos.
O selftest só admite vetores públicos/fixtures sintéticas.

Passaram known-answer IEEE Std 1619-2007 encrypt/decrypt, duas unidades de
4096 comparadas com oracle cryptography/OpenSSL independente, preservação
de output nas rejeições e rejeição de metades iguais. O receipt em
`build/ios-storage-crypto/receipt.json` registra hashes dos inputs e binary.
Não há controller ligado, wrapped key implementada ou firmware executado por
esse componente; `hardware_abi_validated=false` e `ready=false`.

A [documentação Apple](https://support.apple.com/guide/security/data-protection-overview-secf6276da8a/web)
especifica AES-128-XTS com duas metades de 128 bits para A9–A13. A ordem
das metades e o mapeamento do IV no guest ainda exigem evidência do firmware
pinado. O padrão codifica o inteiro da unidade em little endian, mas exclui
o mapeamento a blocos/posições do disco de seu escopo. A limpeza do contexto
expandido QCrypto ainda não foi validada; material de guest real permanece
fora do contrato deste protótipo.

### Adapter incremental ANS unwrapped — implementado, aguardando teste do device

O patch [ans-lab-unwrapped-xts.patch](../components/ios-engine/ans-lab-unwrapped-xts.patch)
é incremental aos patches diagnostics, diagnostics-stage2 e protected-io-guard.
Altera apenas `hw/nvme/ctrl.c` e `hw/nvme/nvme.h`. Foi produzido em cópia
exclusiva; `git apply --check` e compilação do translation unit com os flags
reais do build e header de trace gerado localmente passaram. Isso ainda não
é validação de uma instância do device.

A propriedade `apple-ans-lab-unwrapped-xts` é false por default. Quando
explicitamente habilitada, só aceita modo exato 0x08 em read/write com IOSQE
128 e extensão completa de 64 bytes. O prefixo desconhecido da extensão deve
ser zero nos fixtures sintéticos; a chave de 32 bytes vem de extension+0x20.
Usa a convenção padrão K1/K2 e unidade LE64 explícita de command+0x38.
Wrapped 0x04 e combinação 0x0c continuam rejeitados antes de block I/O.

O adapter limita namespaces NVM com LBA 4096, sem PI/metadata estendida,
zoned/endgroup, mptr, control ou flags adicionais; limita requests a 1 MiB e
rejeita overflow da sequência. Escrita copia DMA para bounce, cifra tudo e
só então submete ao backend. Leitura usa bounce e só copia ao DMA após
decifração completa. Completion/reuse limpam a chave do request; callback
limpa bounce; cancel/error não fazem fallback em claro. A limitação do wipe
do contexto expandido QCrypto continua expressa no patch.

O teste seguinte deve usar requests sintéticos reais do controlador, LBA
físico diferente da unidade IV, ciphertext independente no backing,
roundtrip completo e comprovação de backing/DMA inalterados em cada rejeição.
Compatibilidade das metades/IV com hardware Apple, wrapped keys, SEP e
Data Protection de firmware permanecem fora da comprovação deste adapter.

## Gates de aceitação

| Gate | Evidência exigida | Estado atual |
| --- | --- | --- |
| Protocolo | Descritores/comandos e semântica definidos para o firmware pinado | Ausente |
| Primitivas | Vetores de resposta conhecidos e independentes; negativos para slot inválido/ausente; reset remove estado volátil | Ausente |
| Roundtrip guest | Classe atribuída lida de volta, write/fsync/read idênticos | Observado para classe C; insuficiente |
| At rest | Inspeção dos backings flushados do clone, ciphertext associado ao I/O protegido e ausência de plaintext sintético | Reprovado no checkpoint |
| Boot a frio | Reabrir o mesmo conjunto de nove backings; readback após autenticação e classes corretas antes dela | Tentativa falhou antes do novo roundtrip C; unlock/readback não validados |
| Classes | A indisponível após bloqueio/purge e restaurada por unlock; C indisponível antes do primeiro unlock, mas permanece disponível ao relock; D não depende de passcode | Não validado |
| Revogação | Remoção/reset de contexto não permite reutilização; erro explícito sem fallback em claro; testes de flush/reorder | Não validado |
| Boot utilizável | SpringBoard vivo, display/input e fixture própria instalada/aberta com readback independente | Não validado |

A matriz de classes depende de código de bloqueio/autenticação real no guest,
com janela de descarte e configurações registradas. Exigir que classe C fique
indisponível em todo bloqueio seria um teste incorreto. Referência:
[Data Protection classes](https://support.apple.com/guide/security/data-protection-classes-secb010e978a/web).

## Papel de JEV e de recompilação

Foi lido o README e o AGENTS de `/Users/mftheux/jev-ultrafast`: é um agente de
operações sobre elementos DOM indexados; canvas, uploads e teclado arbitrário
estão fora do MVP. Não fornece protocolo SEP, emulação ANS, implementação de
cifras ou validação do armazenamento. Nenhuma API paga, browser ou executor
JEV foi acionado nesta revisão.

O controle desktop Draxen em
`/Users/mftheux/.codex/worktrees/rea-draxen/engine/engines/draxen_jev_desktop_loop.py`
verifica transições AX/hash e exige evidência declarada para DONE. Isso é útil
para confirmar uma superfície do workbench e impedir loops sem efeito, mas
não é um oráculo criptográfico. Uma mudança visual não comprova Data
Protection. Uma futura verificação de UI deve consumir os resultados locais
dos gates acima, sem promovê-los a partir de uma escolha do modelo.

Compilar/recompilar faz sentido depois de uma mudança de semântica do motor
ou instrumentação observável. Build bem-sucedido do mesmo código não resolve
stubs e não prova boot. Recompilar a fixture com source próprio também não
torna um IPA de iPhone em um build para Simulator. Os dois fluxos precisam
de receipts de source/binary e execução separados.

Trabalho desta revisão: inspeção read-only e este novo documento local; os
boots da equipe constam acima. Sem commit, push ou promessa de runtime pronto.
