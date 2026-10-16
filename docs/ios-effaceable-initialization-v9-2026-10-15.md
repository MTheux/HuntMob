# Inicialização effaceable do perfil próprio — v9, 2026-10-15

Continuação e bloqueio atual: [contexto SEP → ANS v10](ios-sep-ans-context-v10-2026-10-15.md).

O boot normal do modelo experimental passou pelo verificador original de Data
Protection e gerou chaves wrapped de mídia, mas não criou Data protegido.
O erro atual não demonstra falha do KDF: a gravação do keybag de 80 bytes
encontrou armazenamento effaceable ainda sem formato.

## Causa confirmada

No boot `observation-20261015-135921`, o kernel registrou
`format attempt from untrusted root`. O helper considerava apenas o status
zero do selector 4 e imprimia sucesso sem consultar o estado novamente.

A análise do kernel pinado SHA
`524b91442ad73a225f8b86afbed26642fbc14a821647d972d3c52dfc4c431910`
confirmou que a recusa por SecureRoot preserva o status zero da consulta de
plataforma, sem chamar o formatter. Selector 3 retorna o booleano real em um
scalar; seu status IOReturn é separado. O DeviceTree espera prefixo de raiz
`md`, publicado por XNU a partir da raiz real. UID root e entitlements não
substituem essa condição.

O dispositivo effaceable corresponde ao namespace 6/type 6, com 4 KiB nesse
perfil. O namespace 7/type 8 não é esse dispositivo. Não há evidência para
inventar headers ou preencher lockers manualmente.

## Correção e evidência nativa

`prepare_userdata_virtual_v1.c` não tenta mais formatar em boot normal.
Exige estado formatado antes de ClassD e consulta novamente depois dela.
O build temporário de observação para antes de ClassD/newfs e somente consulta
metadados. Wrapper e verificador stock foram mantidos.

`observation-20261015-141502` terminou em 56,50 s por checkpoint, com QMP
quit aceito, SEP/OS ativo, zero panic, zero fault MPE e zero rejeições em 35
comandos AESS. A consulta retornou status 0/count 1/**formatted 0** e a cadeia
IORegistry terminou em `NS_06@6/AppleEffaceableBlockDevice`. O trace contém
um READ e nenhum WRITE no namespace 6. O backing de 4 KiB estava inteiramente
zerado após o desligamento.

Recibo público:
`artifacts/validation/ios-virtual-sep-effaceable-observation-v1-2026-10-15.json`.

## Preparação em ramdisk

Foi criada uma cópia independente do ramdisk HFSX público pinado, preservando
o original SHA `5eff57f37009c1d996d6de3d6a069029a855cdc978fd54af0977cac49b42689e`.
Um helper com escopo fixo exige build/modelo/UUID, raiz HFS `md0`, ausência de
Data e serviço único. Somente quando ainda não formatado, chama o formatter
stock uma vez e exige confirmação pela consulta na mesma conexão.

O launcher preserva a mesma raiz Keychain, KDF, firmware serving e nove
backings. Exige namespace 6 inteiramente zerado e registra a tentativa antes
de iniciar, impedindo repetição automática. Nenhum DeviceTree, SecureRoot,
nome de raiz ou gate foi alterado. Não chama restore+art, erase, ClassD,
newfs, nem lê lockers. Os servidores conhecidos de restore, KeyMaker e proxy
foram desativados somente nessa cópia; isso não prova ausência de toda escrita
automática por outros componentes do ramdisk.

Um checkpoint com os nove backings, manifest e trustcache foi clonado e teve
SHA completo conferido antes do ensaio. A primeira execução chegou a BSD
root `md0`, porém o helper recusou uma condição de escopo antes da formatação.
Namespace 6 permaneceu zerado, sem WRITE no trace. A revisão seguinte apenas
adiciona diagnóstico dos metadados da raiz; mantém todas as condições.

Os metadados reais mostraram `scope=0 type=hfs from=root_device on=/ rootfs=1`.
O kernel usa esse nome genérico mesmo para BSD root `md0`. A condição foi
corrigida para comparar `stat("/").st_dev` com `lstat("/dev/md0").st_rdev`,
exigindo block device real, HFS e raiz `/`. O caminho IOKit foi ajustado ao
install name versionado presente no ramdisk público. Nenhuma política de
confiança ou nome de raiz foi alterado.

`observation-20261015-142814` confirmou que o serviço não aparece mesmo após
20 segundos de consultas. O kernel informa `FW update not complete, create
dummy block device`; nesse ambiente de restore, o controlador não publica
os children completos. A análise do DeviceTree confirma namespace 6 com
um bloco de 4096 bytes, igual ao backing existente: não é preciso redimensioná-lo.
O contrato de estado de firmware do ANS precisa ser implementado e validado
antes de outra tentativa de inicialização. A preparação não formatou o
namespace e o runtime segue indisponível.

## Inicialização e persistência confirmadas

A revisão seguinte distinguiu o estado software mantido por `AppleNVMeUpdateUC`
dos registradores do modelo ANS. O utilitário original pinado
`nvmefwupdater --nvme enable-skip` oferece uma operação de online para um
controlador com firmware já carregado. Ela foi usada exclusivamente no modelo
virtual próprio: não comprova download, autenticação ou execução de firmware
ANS Apple. Nenhum MODESEL, campo Identify ou gate de confiança foi forçado.

Antes do ensaio, o candidato recebeu
`ans-virtual-namespace-format-guard.patch`, que recusa o caminho herdado C6/mode0
capaz de formatar o namespace 1 por suposição. Dois comandos foram recusados
com `0x4002` em fixture pública com CPUs pausadas; DMA e os 16 MiB completos
do disco permaneceram iguais após flush. Recibo:
`artifacts/validation/ios-virtual-sep-namespace-guard-v1-2026-10-15.json`.

`observation-20261015-144205` terminou em **7,44 s** no checkpoint, sem panic:
updater original exit/signal 0, serviço publicado, query `formatted=0`,
formatter stock status 0 e query posterior na mesma conexão **formatted=1**.
O trace contém dois WRITEs no namespace 6, uma chamada C6 e nenhuma chamada
de download/activate de firmware. Essa C6 não utilizou o mode0 bloqueado;
o ramo nonzero ainda era o ACK sem validação herdado e não deve ser apresentado
como implementação completa do protocolo. Um validador próprio da configuração
existente está em desenvolvimento para substituir esse ACK.

O boot normal independente `observation-20261015-144326`, **56,27 s**, passou
pelo verificador original, chegou a SEP/OS ativo e confirmou **formatted=1**
sem WRITE no namespace 6 ou rejeição AESS. Os dois processos foram desligados
por QMP com flush aceito. Recibos:
`artifacts/validation/ios-effaceable-native-initialization-v1-2026-10-15.json` e
`artifacts/validation/ios-effaceable-cold-persistence-v1-2026-10-15.json`.

O helper de preparação de Data foi retomado somente após esse checkpoint
frio, preservando wrapper/verificador stock e suas permissões. A instalação
do helper não equivale à criação ou validação de Data protegido.

O ACK nonzero herdado foi substituído, no candidato
`711c9d03908025c826dcbf76c98211c6afe5aaf566e4c0dbb991f212af2b78ed`,
por um contrato explícito do perfil próprio: C6/mode1 somente valida o layout
existente. O validador confere transferência integral somente de RAM, count,
IDs, tipos, capacidade real e geometria dos namespaces, rejeitando flags
desconhecidas e tail não zero. Ele não cria, formata ou redimensiona dispositivos.
O significado hardware Apple de mode1/flag0x20 não foi comprovado.

No binário exato, **30/30 checks públicos** passaram: três layouts válidos e
27 recusas, incluindo DMA inválido/MMIO e divergências de inventário.
Os nove backings permaneceram iguais ao baseline após inicialização e flush;
o namespace 1 inteiro tinha 16 MiB. A alteração automática do namespace 5 no
startup do device foi registrada separadamente. Recibo:
`artifacts/validation/ios-virtual-sep-namespace-validation-v1-2026-10-15.json`.
Essa evidência não equivale à execução do novo C6 por firmware Apple.

## Limites

Data protegido, sonda Class C persistente, scan posterior, cold read e
bloqueio/desbloqueio ainda não estão validados. O achado histórico de plaintext
continua aberto. SpringBoard e IPA continuam pendentes. Esse modelo próprio
não comprova equivalência com o SEP/MPE ou attestation de hardware Apple.

As mudanças são locais, sem commit, push ou distribuição. O runtime mantém
`ready=false`; Android e Apple Simulator não participam desses ensaios.
