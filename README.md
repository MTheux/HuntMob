# HuntMob

Laboratório portátil de análise mobile do ecossistema HuntBox/Draxen.

O projeto coordena runtimes Android e iOS e envia artefatos autorizados ao
REA para análise estática/dinâmica. O runtime nunca escolhe o alvo: toda ação
exige um engagement válido, pacote allowlisted e aprovação explícita.

## Arquitetura inicial

```text
HuntMob Control Plane
├── Android: HuntMob Worker + QEMU/HVF/KVM/WHPX + AOSP + ADB
├── iOS: Apple Simulator + vPhone adapter
├── Analysis: REA + Ghidra + JADX/Apktool
└── Evidence: receipts, screenshots, logs and hashes
```

## Início rápido

```bash
python3 -m huntmob.cli status
python3 -m huntmob.cli providers
python3 -m huntmob.cli capabilities
python3 -m huntmob.cli plan ios --controller-os windows
python3 -m huntmob.cli plan ios --controller-os linux --privileged-ios
python3 -m huntmob.cli runtime-plan pixel-lab --api 35 --arch x86_64 --worker-os linux
python3 -m huntmob.cli android status
python3 -m huntmob.cli android start --authorized --approve
python3 -m huntmob.cli bootstrap --install
python3 -m unittest discover -s tests -v
```

O comando `status` é somente leitura. Criação, inicialização e alteração de
dispositivos serão adicionadas atrás dos gates de autorização.

## Workbench UI

O protótipo navegável fica em `web/` e pode ser aberto sem dependências:

```bash
PYTHONPATH=src python3 -m huntmob.cli ui
```

Acesse `http://127.0.0.1:8090`. A interface demonstra o workspace unificado de
device, REA, Frida, proxy, evidências e fixtures. A webcam só é solicitada após
ação explícita. O reconhecimento facial usa Human 3.3.6 no navegador; o embedding
é mantido apenas em memória e descartado ao fechar a fixture.

O Frida Script Center aceita um package/bundle ID autorizado, seleção múltipla
de scripts e prepara um job worker-only. Scripts ativos continuam bloqueados até
aprovação humana e emissão do receipt de execução.

O servidor usa loopback por padrão. Exposição em VPN/Tailscale exige autenticação
no gateway e a confirmação explícita `--authorized-remote`; não exponha o servidor
de desenvolvimento diretamente à internet.

## Limites

- O runtime Android é próprio e clean-room. Genymotion é somente uma referência
  comportamental e nunca é dependência de execução do HuntMob.
- iOS local usa Apple Simulator; Corellium é o tier avançado e device clouds
  são opcionais para recursos que exigem hardware real.
- Em Windows/Linux, a UI funciona localmente e agenda iOS em um Mac worker,
  Corellium ou device cloud através de uma conexão privada autenticada.
- Biometria, câmera, localização e sensores são fixtures de teste, não bypasses.
- Nenhuma execução contra aplicativo ou sistema sem autorização documentada.

