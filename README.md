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

### Docker (Android em Linux x86_64)

Em um host Linux x86_64 com Docker Compose v2 e `/dev/kvm` acessível:

```bash
./scripts/run-docker.sh
```

O comando constrói a imagem local, solicita o aceite interativo das licenças
oficiais do Android SDK, instala o emulador e a imagem AOSP Android 15 e inicia
o HuntMob em `http://127.0.0.1:8090`. A interface, o worker, o SDK, o proxy e o
motor de análise ficam no contêiner. SDK, AVDs e workspaces persistem em volumes
Docker; `docker compose down` não apaga os laboratórios. Para parar e retomar:

```bash
docker compose down
docker compose up -d
```

Esta modalidade exige KVM do host e usa imagem Android **x86_64**. No macOS,
inclusive Apple Silicon, e no Windows com Docker Desktop, a virtualização do
Docker não fornece a aceleração nativa necessária ao worker Android; use o
worker nativo dessas plataformas. O fluxo iOS depende de macOS/Xcode e não
roda neste contêiner. A imagem padrão não inclui MobSF ou Ollama externos;
integrações que dependam deles continuam opcionais. Não publique a porta 8090
na internet: o Compose a vincula somente ao loopback.

O contêiner pode ser construído e inicializado apenas após revisão dos termos
do [Android SDK](https://developer.android.com/studio#terms). A disponibilidade
do KVM e o boot de um AVD devem ser conferidos no host Linux; iniciar a página
web não demonstra que o Android iniciou.

### Execução nativa

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
PYTHONPATH=src python3 -m unittest discover -s tests -v
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

- O worker Android usa o Android Emulator e imagens oficiais do SDK. Genymotion
  é referência de comportamento e não é dependência de execução.
- iOS local usa Apple Simulator. O emulador iOS próprio permanece bloqueado na
  validação ANS/NVMe; nenhum provider Corellium está integrado.
- A arquitetura prevê uma UI em Windows/Linux com worker iOS remoto. O
  worker iOS implementado atualmente exige macOS/Xcode; execução iOS local
  em Windows e despacho remoto autenticado ainda não foram validados.
- Biometria, câmera, localização e sensores são fixtures de teste, não bypasses.
- Nenhuma execução contra aplicativo ou sistema sem autorização documentada.


## Um laboratório por aplicativo

“Novo lab” com APK cria um AVD separado, com userdata limpo e apenas o app alvo
como aplicativo de terceiro. Apps Android de sistema continuam presentes.
A sessão anterior é desligada e preservada em “Labs salvos”; retomar não reinstala
nem limpa seus dados. Só um AVD HuntMob ocupa a porta do worker por vez.

As configurações gráficas validadas do AVD base são herdadas pelos novos labs.
Workspaces JADX e snapshots de tráfego ficam separados por lab; novas capturas
recebem seu identificador de lab. O lab antigo permanece disponível como “Lab anterior”.
A lista de outros pacotes fica em uma seção avançada da aba Reverse.

## Motor de análise incorporado

A versão 0.2 inclui o motor de decompilação e seu próprio Java no pacote do worker.
A análise não procura `jadx` ou `java` no PATH e não baixa dependências durante o uso.
A interface apresenta “Analisar aplicativo” e verifica a integridade do motor.
Se o pacote estiver incompleto, a ação fica indisponível e pede a reinstalação do
HuntMob correspondente à plataforma, sem orientar o cliente a instalar JADX.

Os binários oficiais são fixados por versão/checksum em
`components/analysis-core/manifest.json`. O empacotamento é feito pelo mantenedor:

```bash
python3 scripts/build_release.py --target mac-aarch64
python3 scripts/build_release.py --target windows-x64
python3 scripts/build_release.py --target linux-x64
```

Cada wheel contém motor, JRE, licenças e interface. O instalador Python seleciona
apenas um wheel compatível com a plataforma. Os demais componentes do laboratório
(Android SDK, Frida e proxy) ainda têm seus próprios requisitos; esta incorporação
remove as dependências externas da decompilação.

Acesso pelo iPad/notebook via Tailscale: com a UI local ligada, execute `huntmob remote` em outro terminal. O gateway usa HTTPS privado, identidade do proprietário e o worker existente. Veja [operação e validação](docs/remote-ipad-tailscale-v1-2026-10-14.md). O proprietário precisa habilitar Serve/HTTPS quando solicitado pelo Tailscale; conexão real em iPad ainda não foi validada.

Janela desktop: selecione o dispositivo e use **Abrir janela** para o navegador ou para baixar o HuntMob Viewer portátil (.app no Mac Apple Silicon, .exe no Windows x64, binário Linux x64). O emulador continua no worker. Identidade completa e exportação estão em **iOS → Perfil**. Veja [validação e limites](docs/desktop-viewer-identity-v1-2026-10-14.md).

Avaliação local do Companion: com REA e Ollama `hermes3:8b` prontos, conclua uma
inspeção REA e use **Avaliar com modelo local** no Reverse. A revisão exige ação
explícita e permanece pendente de revisão humana. Veja a
[validação local e limites de plataforma](docs/companion-local-model-platform-validation-v1.0-2026-10-16.md).
