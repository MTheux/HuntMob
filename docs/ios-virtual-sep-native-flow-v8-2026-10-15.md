# Fluxo nativo do perfil próprio — v8, 2026-10-15

O firmware SEP real passou a executar com o modelo experimental próprio.
Isso não reproduz a derivação secreta, o MPE ou a attestation de um iPhone
físico. A raiz por VM continua no Keychain; os nove backings pertencem somente
ao cohort novo e nenhum disco de cliente foi importado.

## Marcos confirmados

1. Core OwnMPE com 1.409 checks nativos, 200 checks independentes e sanitizers.
2. CPU SEP real do t8030 executando código privado, stores exclusivos e código
   modificado. O bypass de AF em ROMD foi reproduzido e corrigido, com probe
   de escrita stage 2 preservado. Nenhum guest EL2 foi ensaiado.
3. Cold boot real chegou a `SEP/OS is alive`, derivou os pares e executou
   latches de wrapping, authentication e subkey. A restauração original
   concluiu todas as seis chamadas com exit/signal zero.
4. Checkpoint `observation-20261015-123505`, 89,67 s, sem panic ou fault MPE;
   QMP flush/exit aceito. Recibo público:
   `artifacts/validation/ios-virtual-sep-native-restore-v1-2026-10-15.json`.
5. No boot normal seguinte, o helper executou o verificador original e só
   então entrou na preparação de Data. A mensagem de effaceable storage
   confirma a passagem dessa fronteira, pois o wrapper exige exit zero.

## Correções necessárias no fluxo

O helper encerrava o primeiro processo stock após 60 s, antes de terminar
o cold boot TCG. O prazo de `--restore+art` foi ampliado para 150 s, ainda
com supervisor externo limitado a 180 s. As chamadas agora registram somente
opção fixa e status de saída/sinal.

Ao retomar um Gigalocker existente, o helper também pulava o registro pelo
utilitário. O binário stock usa selector 44 para registrar o pathname a cada
boot, inclusive quando o arquivo válido já existe. O novo helper verifica o
alias `/mnt7` e mantém nome/device/inode/tamanho ao registrar. Shutdown, que
antes retornava exit 202, passou a retornar zero. O código nunca transforma
esse retorno de erro em sucesso.

O primeiro boot normal, `observation-20261015-124032`, encontrou outro defeito
do próprio motor: a operação `0x80` revogava todos os bancos inline. O firmware
repete `240 → 80 → 202` para derivar UID sem reprogramar os pares já publicados;
os comandos seguintes `206/8/88` falhavam e causavam panic AESS. KEYDISABLE
`0xb` não rejeita essas três palavras na implementação.

O patch incremental `sep-uid-control-preserve-inline.patch`, SHA
`a8478a1d286de44326793d3d455bc32aa418db438908251fd855facaf9cb564e`,
preserva os bancos/latches/epoch em `0x80`. `0x200`, full reset e erros reais
continuam revogando. A limpeza da chave explícita do caller em `0x80` permanece
uma política conservadora do modelo próprio, sem alegação de equivalência Apple.

O teste com dispositivos AESS/KEY/ANS reais reproduz a rejeição de `206` no
predecessor, e passa no candidato: oito sequências UID, mesmo envelope por
oráculo independente e leitura protegida do mesmo disco. Os testes também
mantêm a invalidação em `200`/reset e a recusa de chave explícita apagada.
Recibo: `artifacts/validation/ios-virtual-sep-mmio-v3-uid-control-2026-10-15.json`.

Candidato atual:
`634533750ec4389cc9f673dec2c8a0b4a3829836ad4072635973c30a93455c30`.
O KDF persistente `crypto/huntmob-virtual-sep.c` permaneceu inalterado; a raiz
e a associação do cohort não foram trocadas. O parser de diagnósticos passou
a reter os últimos 256 comandos e a contar todas as rejeições, evitando
ocultar erros após um lote longo de operações aceitas.

## Ainda sem validação

Atualização: a criação de Data encontrou uma recusa de formatação effaceable
em boot normal. A investigação e a correção do falso sucesso estão registradas
em [inicialização effaceable v9](ios-effaceable-initialization-v9-2026-10-15.md).
O ensaio em ramdisk ainda depende do estado de firmware ANS e não criou Data.
Ainda não há sonda Class C validada nesse perfil, scan do backing após essa
sonda, readback em cold boot ou bloqueio/desbloqueio. O achado histórico de
plaintext permanece aberto. SpringBoard, IPA, portabilidade e equivalência
com a segurança do SEP físico não estão demonstrados. Data Protection segue
habilitada e o runtime não foi promovido como disponível no produto.

Alterações locais, sem commit, push ou distribuição. Android e Apple Simulator
permanecem fora desse experimento.
