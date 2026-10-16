# Runtime próprio: persistência e boot inicial — v13, 2026-10-15

**Confirmado no laboratório local:** a coorte DATA-v2 releu a sonda Class C
preservada após reiniciar (`173327`) e depois executou o caminho normal de
inicialização (`175232`) com os programas originais restaurados. O segundo
ensaio chegou a `Early boot complete. Continuing system boot.` sem panic.
Não há SpringBoard, controles ou execução de IPA validados.

## Evidência nativa

- Leitura persistente: mesmo arquivo Class C/3, 64 bytes, AFU 1→1, metadados
  e digest correspondentes; `keybagd --init` original terminou com exit/signal 0.
- Boot normal: 180,1 s, 21 tarefas iniciadas até `launchd_cache_loader`,
  marcador stock de boot inicial e nenhuma tarefa reportada como falha.
- Nesse caminho: 22.143 comandos AESS; zero recusas AESS, NVMe, gate, IO ou
  fault MPE. Encerramento QMP aceito e exit 0, ao fim da janela do host.
- A captura QMP de 828×1792 mostra somente o logo do engine Inferno.
  O logo não é um frame do SpringBoard.
- Após esse boot, uma nova varredura dos nove backings leu 34.369.523.712
  bytes em 17,44 s. Nenhum dos dois formatos do marcador público apareceu;
  as identidades dos arquivos permaneceram estáveis durante a varredura.

O log normal também contém os retornos SEP `e00002e2`, `e00002f0` e
`e00002c2`. A causa e o impacto desses diagnósticos ainda não foram
estabelecidos. As contagens limpas do caminho ANS/AESS não autorizam afirmar
que todos os serviços SEP ou toda a proteção de dados funcionam.

## Alterações aplicadas

Os mesmos bytes originais do `keybagd`, Data Protection e trustcache foram
restaurados; o primeiro preservou seu inode. Foram retiradas somente as
três entradas dos auxiliares próprios do trustcache. Os seis volumes,
UUIDs, Root/KDF e engine permaneceram os mesmos. Data não foi montado nem
desbloqueado no host.

O stager agora adquire atomicamente o lock compartilhado antes da operação.
Um lock substituído não é removido no cleanup. Crash ou SIGKILL deixam o
lock/intent para auditoria explícita.

O status de pesquisa ganhou uma versão nova vinculada pelos hashes dos
dois recibos públicos. O loader aceita o avanço somente com os dois recibos
consistentes. Recibos antigos foram preservados. Todas as flags de runtime
pronto continuam falsas; a proteção completa continua pendente.

## Próximo diagnóstico de vídeo

**Confirmado por leitura do engine:** `-display none` não cria um frontend
com refresh periódico. O ADPv4 gera `OUTPUT_READY` no callback gráfico;
`screendump` aciona esse callback. Isso é uma dependência problemática do
display em modo headless. Ainda não prova a causa de o SpringBoard não
ter aparecido nesta janela.

Foi preparado um ensaio separado com o callback QMP existente, solicitando
até 10 atualizações/s e descartando os pixels intermediários em `/dev/null`.
O recibo registra a quantidade realmente aceita e a latência. O cliente
fecha antes do encerramento QMP e não modifica guest, cache, engine ou chaves.
O resultado nativo desse segundo ensaio deve ser registrado separadamente.

**Resultado posterior confirmado:** `180951` aceitou 1.629 chamadas de
refresh em 180,01 s, média de 4,13 ms e máximo de 65,1 ms por chamada no
host. O boot inicial passou novamente sem panic ou erros no caminho
AESS/NVMe/gate/IO/MPE. As capturas finais são idênticas por bytes e pixels.
Isso não fornece FPS de interface nem resolve o logo estático.
O [comparativo independente](../artifacts/validation/ios-own-data-v2-headless-refresh-comparison-v1-2026-10-15.json)
preserva essas limitações.

Não foi aplicado o FSPatcher: sua rota padrão também altera frameworks
de telefonia, e o stager antigo desabilita cinco serviços. Isso excede uma
mudança isolada no refresh e não permitiria atribuir o resultado a uma causa.

## Limites de aceitação

Aceitação atual: uma sonda Class C preservada, sob a identidade/KDF/política
próprios, mais o marcador de boot inicial stock. Os bytes chamados originais
vêm da imagem de pesquisa; não constituem prova da cadeia física de assinatura
Apple. O perfil não equivale a UID fundido, MPE ou attestation Apple.

Continuam sem validação: BFU, bloqueio/desbloqueio, outras classes, proteção
completa, SpringBoard, vídeo interativo, IPA, jailbreak/Frida e entrega
Windows/Linux/iPad. O achado histórico de plaintext permanece aberto.

## Recibos

- [Sonda Class C persistente](../artifacts/validation/ios-own-data-v2-native-cold-read-v1-2026-10-15.json).
- [Boot normal delimitado](../artifacts/validation/ios-own-data-v2-normal-boot-v1-2026-10-15.json).
- [Varredura posterior](../artifacts/validation/ios-own-data-v2-raw-probe-after-normal-boot-v1-2026-10-15.json).
- [Status de pesquisa v2](../artifacts/validation/ios-native-runtime-status-v2-2026-10-15.json).

O endpoint `/api/ios/status` com o código novo foi validado por HTTP 200
em um processo de teste local na porta 8099, já encerrado. O serviço
principal previamente aberto na porta 8090 não foi reiniciado neste ensaio.

Trabalho local. Sem commit, push, deploy ou promoção do provider iOS.
