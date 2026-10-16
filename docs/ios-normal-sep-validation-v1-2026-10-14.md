# SEP normal — validação v1, 2026-10-14

## Resultado confirmado

O SEP de operação normal iniciou e o verificador original de Data Protection
concluiu no build iOS 14.0 beta 5 (18A5351d), modelo virtual t8030/n104ap.
A inicialização persistente do nonce removeu o bloqueio anterior. A criação explícita da chave D permitiu criar e montar Data protegido
(`newfs_apfs -A -P -o role=d`), sem o panic SEP `sks [nvilv]`. O keybag do sistema e a sonda de classe C concluíram no teste efêmero.
O bloqueio atual ocorre na tarefa mount-phase-2, e persistência/boot a frio
ainda precisam ser validados. Não há SpringBoard nem instalação de
IPA validados. Data Protection permanece exigida; seu funcionamento completo
não foi validado.

## Correção local

O motor tem `SEP_ENABLE_HARDCODED_FIRMWARE` ativo. Em `sep.c`, o firmware
selecionado por `sep-fw` é copiado para a memória usada pelo SEP. O launcher
do boot instalado ainda passava o arquivo `rsep`, mesmo após trocar o
arquivo no Preboot por `sepi`. Portanto, o experimento anterior não isolava
adequadamente o firmware de operação normal.

`scripts/boot_ios_installed_research.py` agora seleciona o arquivo `sepi`
também no argumento do motor, exige seu SHA256 previamente registrado e
registra esse hash no receipt. O launcher de recuperação continua com seu
arquivo original. Configurações inesperadas bloqueiam a execução.

## Teste real

Executado boot limitado a 60 segundos no clone privado
`native-20261013-215607`, com writes efêmeros, sem NIC e sem device físico.
O motor terminou em panic antes do limite. O log confirmou launchd,
inicialização do Gigalocker, execução do verificador original e entrada no
carregamento SEP normal. O panic continua sendo `SEP ROM boot panic`.

O diagnóstico local do buffer de panic, pelo parser publicado pelo próprio
autor em https://github.com/Cryptiiiic/SEPROMPanicDecrypt, retornou código
`0xE5` nos testes anterior e atual, com os mesmos endereços de ROM. Apenas
o código e os endereços de execução foram usados na análise; o buffer bruto
e o diagnóstico completo permanecem privados. Isso não identifica sozinho
a causa raiz. A hipótese atual é incompatibilidade do estado virtual de
inicialização do SEP, a confirmar. Nenhuma verificação da ROM foi removida.

Receipt privado do boot: `disk-boot-20261014-065610.json`.
Resumo sem buffer bruto: `artifacts/validation/ios-normal-sep-validation-v1-2026-10-14.json`.

## Checks e limites

19 testes dos launchers passaram, incluindo seleção de `sepi`, rejeição de
hash divergente e configuração inesperada. Sintaxe Python e diff check
passaram. Esses checks não comprovam um runtime iOS funcional.

Alterações locais, sem commit ou push. Nenhum runtime experimental foi
habilitado no produto. O clone foi preservado e a VM do teste terminou.

## Observação do estado no panic

O launcher recebeu `--diagnose-sep-state`, limitado ao mesmo clone, motor e
ROM fixados. Usa um debugger por socket UNIX privado. O breakpoint observa
o local conhecido do código `0xE5`; não substitui instruções da ROM. A leitura
é limitada aos flags de boot e ao cabeçalho do firmware preparado, sem ler
chaves, buffers de entropia, mailbox ou dados de aplicativos.

O teste `disk-boot-20261014-071203.json` observou:

- criptografia de memória habilitada;
- modos production e secure ativos;
- flags de boot inicializados;
- solicitação de debug da ROM desativada;
- cabeçalho IMG4 na memória física idêntico ao do arquivo `sepi` preparado.

Depois de retirar o breakpoint e liberar os três clusters de CPU, o panic
voltou a ocorrer. Isso exclui a ausência do cabeçalho preparado nesse local,
mas não confirma a integridade do payload inteiro ou a causa raiz do panic.
Os patches do motor upstream continuam os mesmos já documentados; nenhuma
verificação adicional foi removida neste diagnóstico.

Tentativas iniciais de observação que falharam ou mantiveram clusters
parados não estabelecem ausência do panic nem boot funcional. O launcher
agora retorna falha quando a observação não conclui. O goal permanece ativo:
boot/interface/fixture e melhorias do fluxo ainda estão pendentes.

## Comparação com envelope cifrado no laboratório

Foi preparado um segundo clone COW exclusivo, `native-20261014-encrypted`.
O clone anterior foi preservado. Nele, o Preboot e o argumento `sep-fw`
usam um envelope com payload AES-CBC cifrado e keybag DER. A chave/IV de
payload foram geradas em memória e envelopadas com os valores sintéticos
do motor fixado. Nenhuma chave de iPhone ou do SEP do Mac foi usada ou
exportada. O envelope é exclusivo da pesquisa; não é firmware assinado
pela Apple para uso em hardware físico.

SHA256 do envelope:
`172f794c8ae94df08d8e74f7a620569576c7dad3a610d3975d420c7826cfbb63`.
O perfil `encrypted-lab` é opt-in no launcher, exige esse hash e mantém
o perfil anterior como default. Data Protection continua com sua tarefa
e verificador originais; nenhum patch adicional de ROM foi introduzido.

O boot sem debugger `disk-boot-20261014-071823.json` continuou em `0xE5`.
Assim, acrescentar um keybag não resolveu o bloqueio. A hipótese de ausência
do keybag como causa suficiente não foi confirmada.

A observação no retorno da avaliação IMG4
(`disk-boot-20261014-072228.json`) registrou código de retorno `0`, PC no
local esperado e instruções nesse local idênticas à ROM original. O motor
continua usando os patches upstream já documentados; retorno `0` aqui não
prova assinatura Apple válida ou Secure Boot equivalente a um iPhone.

No ponto de seleção do keybag, o registro de controle era `1`
(`disk-boot-20261014-072255.json`). Isso delimita o próximo diagnóstico:
acompanhar a etapa posterior de decifragem/handoff e a política do estado
virtual, sem remover o erro `0xE5` ou desativar a proteção. A interface iOS
e a instalação da fixture continuam não validadas. As VMs limitadas
terminaram e o clone de comparação foi desmontado antes dos boots.

## SEP ativo em restauração e teste a frio

Foi confirmado que o nonce normal está ausente antes da comparação do
firmware (`disk-boot-20261014-072843.json`). A comparação de nonce não é
atingida nesse caminho; não se tratava apenas de um valor divergente.

Em outro clone COW exclusivo (`native-20261014-restore-preload`), o helper
chamou o comando original `seputil --restore+art` com o pacote `rsep`.
O boot `disk-boot-20261014-073051.json` registrou `SEP/OS is alive`. Isso
valida o início de SEPOS nesse fluxo de restauração, não o boot normal.
O verificador original continuou obrigatório e falhou ao reinicializar
o Gigalocker já aberto pela restauração.

O helper passou a chamar o shutdown original do Gigalocker antes do
verificador. No teste `disk-boot-20261014-073306.json`, o Gigalocker
reinicializou corretamente, mas o loader recusou recarregar o SEP já ativo
(`0xe00002d5`, saída 5). Nenhum retorno foi convertido em sucesso.
Um teste intermediário terminou em data abort antes de launchd; ele não
foi usado para validar o helper.

Foi acrescentado um modo explícito de persistência somente para esse clone
de preparação. Ele exige origem conhecida, backing files independentes,
sem symlinks/hardlinks para a origem, e o perfil de restauração. O default
continua com writes efêmeros. Não foi aplicado ao clone anterior.

O comando original `--new-nonce` não concluiu em 60 ou 180 segundos.
Durante o teste maior, o QMP confirmou execução, sem panic; a chamada
continuou pendente. O supervisor encerrou a VM ao atingir seu limite.
Isso não estabelece sucesso de preparação. Os arquivos SEP NVRAM/SSC
continuavam sem bytes não-zero nas observações feitas após os testes.

Para o boot a frio, o arquivo opt-in de restauração foi renomeado e
preservado. O helper chamou somente o verificador original. O teste
`disk-boot-20261014-074217.json` confirmou Gigalocker inicializado, nonce
normal ainda ausente e novo panic da ROM. Ainda falta concluir a preparação
do nonce/ART e validar a operação normal. Data Protection não foi desativada
nem seu erro ignorado.

O launcher agora distingue SEP ativo, erro de proteção, panic, limite de
observação e boot não validado. Ausência de panic até o limite retorna
falha de validação. Sintaxe, 19 testes e compilação do helper iPhoneOS com
warnings como erros passaram. Não há SpringBoard ou IPA validados; todas
essas alterações continuam locais, sem commit/push.


## Estado apresentado no produto

O endpoint `/api/ios/status` agora inclui uma leitura limitada dos marcos
locais de pesquisa, separada do inventário Simulator. O novo leitor não
executa comandos, não expõe logs/caminhos/chaves e não aceita um receipt de
pesquisa como autorização para anunciar um provider funcional. Sem relatório
válido, o estado é indisponível. No estado validado neste worker, mostra boot
bloqueado, duas etapas observadas e proteção/interface/IPA pendentes.

O painel mantém os controles Simulator identificados explicitamente e
bloqueia ações incompatíveis com estado, seleção de arquivo ou autorização.
O atalho para Reverse foi verificado no navegador. A atualização não resolve
o nonce/ART nem substitui a validação do runtime solicitado.

## Avanço e bloqueio atual — 14/10/2026

A preparação persistente usa uma cópia isolada de todos os nove discos.
A sequência stock `--restore+art`, `--erase`, `--commit-hash --erase`,
`--new-nonce`, `--gigalocker-shutdown` concluiu e foi encerrada por QMP
no checkpoint. Receipt privado: `disk-boot-20261014-084603.json`.

Um novo clone desse conjunto passou pelo SEP normal e pelo verificador
original, mas voltou a apresentar `sks [nvilv]` na criação de Data protegido.
Receipt: `disk-boot-20261014-085107.json`. A notificação separada de erase
não resolveu o problema. Writes deste último teste foram efêmeros.

O teste sem `-P` criou Data, mas a sonda retornou classe de proteção 0,
mesmo após solicitar classe 3. Esse resultado foi rejeitado. A chamada
stock `MKBKeyBagCreateSystem` concluiu com a permissão mínima de keystore
no helper privado, mas isso não demonstrou proteção funcional. Não foram
adicionadas alterações de ROM/kernel para ignorar verificações.

O próximo teste precisa resolver a inicialização SKS do volume protegido;
classe correta, persistência e evidência de armazenamento protegido são
pré-requisitos antes de validar interface e instalação da fixture.

### Inicialização do armazenamento effaceable

A rotina original `format_effaceable_storage` usa AppleEffaceableStorage:
selector 3 consulta se há formato e selector 4 inicializa apenas se vazio.
O helper passou a reproduzir essa sequência sem limpar armazenamento já
formatado nem ler lockers. A primeira abertura retornou `0xe00002e2`.
A entitlement original restringe acesso a `AppleEffaceableStorageUserClient`;
a permissão dessa única classe resolveu a abertura.

O teste `disk-boot-20261014-085545.json` confirmou inicialização/estado
formatado, mas manteve `sks [nvilv]` durante criação protegida de Data.
Isso descarta a ausência dessa etapa como explicação suficiente.
A chamada stock de criação da chave D, identificada no restaurador original,
é o próximo experimento e fica restrita ao guest autorizado sem Data.

### Criação explícita da chave D — avanço confirmado

No teste `disk-boot-20261014-085634.json`, a chamada original
`MKBDeviceObliterateClassDKey`, restrita ao guest vazio sem Data, concluiu.
O formatter escreveu keybags APFS e criou metadados criptográficos de volume;
Data foi montado como encrypted. O panic `sks [nvilv]` não ocorreu.

`MKBKeyBagCreateSystem(NULL, "/mnt2")` ainda retornou -1. O driver registrou
selector 65 com retorno `0xe00002c2`. O helper recusou prosseguir e launchd
encerrou o boot pela tarefa data-protection. Isso não comprova proteção de
classes: a sonda de classe C não chegou a executar. O próximo trabalho é
validar os pré-requisitos dessa chamada, sem ignorar seu erro.

### Diagnóstico do mapeamento do keybag

A ABI de `MKBSetLogFunction` foi confirmada no callback original: recebe
uma mensagem C string. O helper registra apenas palavras textuais curtas;
valores numéricos, identificadores longos e conteúdo de chave não são
emitidos por esse callback.

O teste `disk-boot-20261014-085827.json` localizou a falha em
`KBMapVolume`: `APFSVolumePayloadGet` falha, seguido da associação do keybag
ao volume e de `KBMapDeviceBag`. Criar Data com `-A -E -P` depois da
inicialização da chave D também falhou nessa etapa
(`disk-boot-20261014-085923.json`). Não reapareceu o panic SKS anterior.
A criptografia de volume adicional não é solução suficiente.

Próxima investigação: parâmetros e pré-requisitos de `APFSVolumePayloadGet`
no MobileKeyBag deste firmware. A fonte pública de virtualização com kernel
macOS documenta um erro de keybag, mas não corresponde ao nosso guest com
kernel iOS e não justifica ignorar verificações:
https://nickb.website/blog/virtualizing-ios-on-apple-silicon

### Associação APFS e sonda de classe C — avanço confirmado

A análise read-only do dyld cache original localizou `_KBMapVolume`
(0x1822bc210) e `_APFSVolumePayloadGet` (0x1b13f76dc). A consulta usa serviço
APFS, e o restaurador tem `AppleAPFSUserClient` na lista de classes permitidas.
Adicionar apenas essa classe ao helper privado mudou o resultado real.

No teste `disk-boot-20261014-090350.json`, o código APFS retornou 49154
(0xc002, sem cookie), permitindo o caminho stock de criação do cookie.
`APFSVolumePayloadSet` concluiu, a associação AKS concluiu e o keybag do
sistema foi inicializado. A sonda exigiu classe 3 (C), escreveu dado
sintético, fsync e leitura idêntica. Todas essas condições passaram.

O boot avançou até mount-phase-2 e falhou com exit 66. O teste utilizou
snapshot efêmero: não prova persistência, boot a frio, proteção de classes
sob bloqueio nem armazenamento cifrado confirmado em disco persistido.
Esses requisitos permanecem antes de declarar Data Protection funcional.
Não houve novo patch de ROM/kernel nem substituição de verificador por sucesso.

### Checkpoint persistente — proteção em disco não validada

Foi criado `native-20261014-protected-data-checkpoint`, copiando os nove
backings da preparação anterior. O launcher aceita persistência de Data
somente nesse tipo de clone exclusivo, com perfil serving, parent esperado
e sem hardlinks/aliases. O helper para após a sonda e desmontagem, e o host
encerra por QMP. Receipt `disk-boot-20261014-090555.json`: checkpoint,
exit 0, sem panic, writes persistentes.

`protected-data-proof.json` privado registra os SHA256 dos nove backings.
A busca read-only no namespace persistido encontrou o canary sintético em
texto claro. Isso contradiz a hipótese de proteção de conteúdo em disco:
classe C e roundtrip isolados não bastam. O canary não é chave/credencial.
Boot a frio e Data Protection funcional continuam não validados.

A próxima investigação é o caminho ANS/NVMe de criptografia do motor,
incluindo as tags incrypto/outcrypto em nvme_mmu.c; não será apresentado
um volume com conteúdo claro como armazenamento protegido.

### Caminho de armazenamento do motor — limitação encontrada

`t8030_create_ans` liga o modelo ao controlador `apple-ans`, não ao
`nvme_mmu` antigo. `apple_ans_vendor_reg_write` apenas guarda valores de
registro. O controlador cria `TYPE_NVME`; sua rotina de I/O encaminha
buffers a `blk_aio_pwritev`/DMA. Não foi encontrada transformação de conteúdo
por tags/chaves nessa rota. A propriedade `is-apple-ans` é declarada, mas
não há consumo adicional dela no ctrl.c revisado.

Isso, junto ao canary em texto claro no backing persistido, mostra que a
proteção anunciada pelo filesystem não comprova criptografia de conteúdo
nesse motor. Implementar o caminho de armazenamento criptográfico é um
pré-requisito restante; cifrar apenas o arquivo de VM no host não substituiria
as classes de proteção do iOS e não será usado como prova equivalente.
O painel agora descreve a falha de validação do armazenamento e permanece
indisponível. Testes de readiness mantêm ready=false mesmo se um receipt
inconsistente declarar proteção validada.

### Auditoria de bloqueio — 14/10/2026

O mesmo bloqueio foi revalidado em três turnos consecutivos: dado sintético
em claro no checkpoint persistido; análise do caminho ANS/NVMe; consulta do
upstream atual. `git ls-remote` confirmou HEAD Inferno cc4302a (igual ao
checkout). Não há atualização aplicável identificada. A busca não prova
inexistência universal de uma implementação; não foi encontrado artefato
compatível e validável para integrar neste ambiente.

Requisito pendente: implementação validada da criptografia inline ANS/NVMe,
com associação correta das classes e chaves virtuais e testes de persistência,
bloqueio/desbloqueio e reboot. Sem protocolo/implementação verificada, alterações
especulativas de cifras/tags não fornecem a evidência exigida. O goal fica
bloqueado nesta dependência, sem afirmar conclusão.

Auditoria do objetivo:
- SEP normal e keybag: observados nos testes privados.
- Classe C e roundtrip: observados, insuficientes para proteção funcional.
- Proteção de conteúdo persistido: falhou; plaintext encontrado.
- Boot completo, interface e instalação/abertura de fixture: não validados.
- UI de disponibilidade: API local informa ready=false e falha de proteção.
- Android/Simulator: processos existentes não foram alterados nesta auditoria.
- Trabalho: local, sem commit/push nesta execução.
