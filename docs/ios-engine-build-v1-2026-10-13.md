# Runtime iOS: build local v1 — 2026-10-13

Confirmado: Inferno revisão `cc4302a99167abec69b714cfd00c38caece7e7de`
compilado no Mac ARM, macOS 27.0.1/Xcode 27. Versão reportada:
`ChefKissInferno-1.0.0rc1_QEMU-10.2.2_10.1.3_hybrid`.

Executável local:
`~/.huntmob/research/Inferno/build-huntmob/qemu-system-aarch64`.
SHA256: `dd379dbe74a05fd1a333ad70953bba919b2477fff3b1facd143b29702dcc0a25`.

Inventário executado com sucesso: `--version`, `-machine help`, `-accel help`.
Modelos Apple reportados: `s8000` (iPhone 6s Plus), `t8030` (iPhone 11).
Accelerators do binário: TCG e HVF; aceleração do modelo Apple não validada.
Receipt completo: `artifacts/validation/ios-engine-build-v1-2026-10-13.json`.

Correções de build: inicializar submódulo mlib; instalar LZFSE; desativar
ParavirtualizedGraphics e VMAPPLE por incompatibilidade com API removida no
SDK 27. Patch reproduzível em `components/ios-engine/macos27-build.patch`.
Modelo APPLE_SOC permaneceu habilitado. Logs em `build-huntmob/configure.log`
e `build-huntmob/build.log` no checkout de pesquisa.

Limites: nenhum firmware de device preparado, nenhum boot iOS, SpringBoard,
gráfico guest, instalação de IPA ou snapshot testado. Nenhum provider novo
foi ativado na UI. Build não estabelece compatibilidade com o IPA solicitado.
O runtime Apple Simulator e os labs Android existentes não foram alterados.

Próximo marco: verificar o par modelo/build suportado pelo upstream e preparar
firmware autorizado para VM isolada; demonstrar boot antes de integração.
Critérios completos em `ios-owned-runtime-feasibility-v0.1-2026-10-13.md`.
O candidato permanece externo ao release enquanto licença e distribuição
forem avaliadas. Não é um hypervisor escrito do zero pelo HuntMob.
