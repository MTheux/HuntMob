# iOS virtual: firmware e validação de boot v1 — 2026-10-13

## Estado validado

Confirmado no Mac ARM, macOS 27.0.1/Xcode 27: o motor Inferno
`cc4302a99167abec69b714cfd00c38caece7e7de` executou o kernel iOS 14.0 beta 5,
montou o ramdisk (`BSD root: md0`), iniciou launchd (`Darwin Bootstrapper`)
e chegou ao serviço de recuperação aguardando restauração. Não foi usado
iPhone físico, Corellium ou Apple Simulator nesse experimento.

Captura real do framebuffer: `artifacts/validation/ios-recovery-recovery-screen.png`.
Logs e hashes: `ios-recovery-boot.log` e `ios-recovery-receipt.json` no mesmo
diretório. O logo/barra de recuperação não estabelece SpringBoard utilizável.

## Firmware e dependências

- Modelo: T8030/iPhone 11, `iPhone12,1`/`n104ap`.
- Firmware: `18A5351d`, obtido do CDN oficial Apple, 5.507.405.643 bytes.
- SHA256: `706742ed60327a5247c29ccc5bf7e6ce9bbf11dd30a468f8f6fc9da76bdca96d`.
  Também corresponde ao checksum publicado pelo mantenedor na discussão
  https://github.com/ChefKissInc/Inferno/discussions/219.
- VM auxiliar Ubuntu 24.04 ARM com imagem verificada pelo SHA256 oficial.
  Ferramentas libimobiledevice compiladas a partir das revisões registradas
  em `ios-runtime-research-dependencies-v1-2026-10-13.json`.
- Dois perfis testados: SEP simplificado sem criptografia e ROM/firmware SEP
  emulados. Ambos chegaram ao ambiente de recuperação. O segundo usa ROM de
  coleção pública referenciada pelo guia, não um download do CDN Apple.
- O patcher gráfico foi compilado, mas ainda não aplicado a um sistema
  instalado. A fixture UIKit própria foi compilada para iPhoneOS/arm64 com
  mínimo iOS 14.0, mas ainda não instalada nem aberta.

Guia primário: https://chefkiss.dev/guides/inferno/.
Não distribuímos firmware, ROM, imagens pré-montadas ou material de chave.
Os artefatos de firmware permanecem no diretório privado de pesquisa local.
Este ambiente tem alterações de boot do upstream e não comprova equivalência
de proteção de dados, assinatura, attestation ou biometria com iPhone físico.

## Restauração

Tentativas com SEP simplificado, ajuste de temporização/SMP e SEP completo
chegaram a 100% de transferência do filesystem. Isso não confirmou instalação:
o guest permaneceu no ASR sem completar conversão/inversão da imagem nas
partições finais. Discos e logs foram preservados. Erros de leitura emitidos
após encerrar a VM explicitamente são consequências dessa interrupção e não
foram classificados como causa original.

A comparação inicial entre hashes de DMG e arquivo recebido não é uma prova
de corrupção: o DMG tem 5.155.389.281 bytes e a imagem APFS expandida tem
7.695.577.088 bytes. O receipt `ios-image-format-comparison-v1-2026-10-13.json`
registra essa limitação. Inspeção somente leitura confirmou um arquivo
intermediário `apfs_invert_asr_img`; as imagens de inspeção foram desmontadas.

A configuração completa com KASLR desabilitado conforme o exemplo do guia
também terminou sem completar a restauração: o host confirmou 100% de envio,
o guest permaneceu no ASR e o teste foi encerrado automaticamente pelo limite
de 900 segundos. Exit code zero do QEMU após o encerramento não é aprovação
do runtime. Não houve indicação de término da primeira etapa de restauração.
A VM auxiliar ARM é uma variação experimental do exemplo
upstream, que usa uma VM auxiliar x86_64; compatibilidade plena não foi
estabelecida por chegar ao serviço USB ou transferir o filesystem.

Ao desligar a auxiliar HVF, foram observados erros repetidos de leitura MMIO
em `0x10041020`/`0x10041024` e I/O reentrante no MemoryRegion `operational`.
Outra inicialização da auxiliar com ARM/TCG também registrou o aviso de I/O
reentrante e perdeu responsividade. Isso é evidência de um problema no caminho
da auxiliar/controlador USB, mas não confirma a causa original do bloqueio
do ASR nem que HVF seja o responsável exclusivo. A próxima comparação técnica
é a VM auxiliar x86_64 do exemplo upstream. Os experimentos foram encerrados;
discos, hashes e logs foram preservados. Android e Simulator não foram alterados.

## Implementação e verificação

`scripts/boot_ios_research.py`: seleção por hashes, extração limitada aos
componentes do manifest, discos exclusivos, duração limitada, áudio desligado,
guest sem NIC e QMP por socket privado. `--authorized-lab` é obrigatório.
`scripts/capture_ios_research.py`: captura por QMP com receipt e hash.
`scripts/build_ios_device_fixture.py`: build próprio mínimo para o primeiro
teste de instalação/abertura, com assinatura ad-hoc somente para o lab.

Cinco testes passaram: rejeição de build não suportado e de caminhos inseguros,
seleção/hash dos componentes, preservação de arquivos existentes e limites
dos discos/monitor do experimento. Checks de sintaxe e diff também passaram.
Os testes não estabelecem que o sistema completo executa IPAs.

## Critérios ainda pendentes

Restauração concluída; boot de disco; aplicação verificada dos ajustes gráficos;
SpringBoard; instalação/abertura da fixture; toque/rolagem; integração do worker
ao navegador. O IPA de UAT não foi instalado ou testado neste runtime. Nenhum
novo perfil de execução de IPA foi ativado no produto. Não há commit ou push.
