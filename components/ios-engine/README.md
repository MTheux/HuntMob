# Runtime iOS experimental

Este componente registra uma base de pesquisa; não é um runtime iOS pronto.
Não está incluído no build de release do HuntMob. Nenhum firmware Apple é
distribuído. O Simulator continua sendo o único perfil iOS validado.

Fonte fixada em `upstream.json`. Checkout de pesquisa local separado:
`~/.huntmob/research/Inferno`. Build sem interface desktop, só aarch64-softmmu,
com seis jobs para limitar concorrência com os labs existentes.

## Reprodução no Mac ARM

Dependências usadas: Xcode CLI, Python, ninja, pkg-config, glib, pixman,
LZFSE, nettle e GnuTLS. Configure baixa subprojetos registrados pelo upstream;
preservar logs e revisões desses subprojetos para rastreabilidade.

```sh
git clone https://github.com/ChefKissInc/Inferno.git Inferno
cd Inferno
git checkout cc4302a99167abec69b714cfd00c38caece7e7de
git submodule update --init --depth 1 util/mlib
git apply /path/to/HuntMob/components/ios-engine/macos27-build.patch
mkdir build-huntmob
cd build-huntmob
../configure --target-list=aarch64-softmmu --disable-guest-agent \
  --disable-sdl --disable-gtk --disable-cocoa --disable-pvg --enable-lzfse \
  --enable-nettle --enable-gnutls --enable-slirp --disable-werror \
  --extra-cflags=-I/opt/homebrew/include --extra-ldflags=-L/opt/homebrew/lib
ninja -j 6 qemu-system-aarch64
```

`scripts/probe_ios_engine.py BINARY --output RECEIPT.json` verifica versão,
modelos e accelerators; não inicia guest. Não confundir accelerator disponível
no executável com aceleração comprovada para o modelo Apple.

No SDK Xcode 27, o adaptador opcional macOS ParavirtualizedGraphics falhou
com APIs removidas (`PGTask_t`). `--disable-pvg` evita esse componente no
build experimental; não comprova gráficos funcionais de iPhone.
O patch desativa a máquina macOS `VMAPPLE`, que exige esse adaptador e
causaria contradição no Kconfig. Ele mantém `APPLE_SOC` habilitado. Patch
local preservado; esse patch de build não altera implementação de kernel
ou firmware. Os experimentos abaixo usam alterações de boot feitas pelo
próprio upstream em memória e não validam segurança equivalente a hardware.

## Experimentos de boot

`firmware-recipe.json` registra o único build selecionado. A preparação e o
boot são locais, em diretórios privados `~/.huntmob/research/ios-vms`, com
discos novos exclusivos, sem NIC no guest e monitor QMP por socket UNIX.
`scripts/boot_ios_research.py` exige `--authorized-lab`, verifica hashes de
motor/IPSW e limita a duração. `--restore-session` usa apenas a VM auxiliar
local já preparada, gravando somente os novos discos desse experimento.

O patch `sep-sim-research.patch` habilita o caminho simplificado existente
no upstream, sem criptografia de dados: somente para pesquisa com discos
vazios; não valida proteção de dados de um aparelho real. O caminho completo
`--sep-emulated` usa outro executável, preservado no mesmo diretório de build
para manter os RPATHs, e ROM/firmware SEP preparados e fixados separadamente.
Ambos chegaram a launchd e ao serviço de recuperação. Isso não comprova
SpringBoard, instalação de app, serviços Apple nem equivalência com hardware.

`scripts/capture_ios_research.py VM_DIR` captura o framebuffer e registra
hash/estado QMP. Capturar o logo de recuperação não comprova UI utilizável.
Nenhum desses perfis foi anunciado como disponível para instalação de IPA
na interface do produto.

## Distribuição

Licenças GPL/AGPL e exceções por arquivo devem ser consideradas antes de
distribuir ou disponibilizar uma versão modificada. Branding tem restrições
separadas. Nenhuma incorporação de código proprietário Corellium ocorreu.
Esta nota não substitui análise de licença para lançamento do produto.

## Restauração local alternativa no macOS

A comparação x86_64 também ficou no ASR 4%, mas a integridade de toda a
partição APFS recebida foi confirmada. O ASR nativo do macOS restaurou o
filesystem em um clone exclusivo. O boot por disco iniciou launchd; agora
está bloqueado no carregamento SEP para operação normal, sem SpringBoard
ou IPA validados. Detalhes e limitações em
`docs/ios-native-restore-validation-v1-2026-10-13.md`.

O helper de armazenamento é próprio e ad-hoc, não assinado pela Apple;
executa a ferramenta e o verificador originais. O perfil não foi publicado
como runtime disponível. Firmware e imagens continuam privados e não
incluídos na distribuição.
