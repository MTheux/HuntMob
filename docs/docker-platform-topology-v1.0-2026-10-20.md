# HuntMob: alocação Linux, macOS e Windows

Versão 1.0 — 20/10/2026. Estado: desenho e primeira implementação de gateway; não representa suporte validado nos três sistemas.

## Objetivo e limite físico

O comando de instalação deve iniciar a interface e os serviços comuns no Docker em cada sistema. O emulador deve usar o acelerador do **host que o executa**. Um contêiner Linux do Docker Desktop em macOS ou Windows não ganha acesso ao Hypervisor.Framework nem ao WHPX do host. O Apple Simulator depende do macOS/Xcode. A experiência pode ter uma entrada Docker comum, mas não um emulador idêntico dentro do mesmo contêiner nos três sistemas.

| Host | Contêiner Docker | Worker Android | iOS Simulator | iPhone físico |
| --- | --- | --- | --- | --- |
| Linux x86_64 com KVM | Interface, coordenação, análise, dados; worker Android pode compartilhar o contêiner Linux com `/dev/kvm` | KVM, com boot ainda não validado neste repositório | Worker macOS remoto | xtool em worker com USB, ainda sem validação ponta a ponta |
| macOS arm64/x86_64 | Interface, coordenação, análise compatível com a arquitetura, dados | Processo nativo com Android Emulator e Hypervisor.Framework | Processo nativo com Xcode/CoreSimulator | xtool nativo; exige aparelho pareado |
| Windows x86_64 | Interface, coordenação, análise compatível com a arquitetura, dados | Processo nativo com Android Emulator e WHPX | Worker macOS remoto | xtool pode ser investigado separadamente; o adaptador HuntMob não foi validado no Windows |

Linux arm64, Windows arm64, GPU, iOS remoto e dispositivos físicos requerem validação própria; não são inferidos desta tabela.

## Estado atual do código

- `compose.yaml`, `Dockerfile`, `deploy/docker-entrypoint.sh` e `scripts/run-docker.sh` implementam somente o caminho Linux x86_64/KVM. O script interrompe a execução em macOS e Windows. O contêiner usa `platform: linux/amd64`, `/dev/kvm` e SDK Android x86_64.
- `src/huntmob/ui.py` atende a interface e executa diretamente `AndroidWorker`, `ios_worker`, proxy, vídeo, REA e arquivos locais no mesmo processo. Portanto, mover a UI para um contêiner e deixar o worker no host exige um contrato de comunicação novo. Publicar uma página em Docker sem esse contrato exibiria serviços como se estivessem disponíveis, mas perderia controle real dos dispositivos.
- `src/huntmob/android_worker.py` reconhece caminhos SDK de Windows e aceleradores HVF/KVM/WHPX. Isso é suporte de descoberta/planejamento, não prova de boot e fluxo completo em Windows.
- `src/huntmob/ios_xtool.py` já fornece enumeração USB, instalação IPA e abertura por Bundle ID no host. Sem iPhone pareado, o fluxo físico ainda não foi validado.
- `scripts/connect-windows-worker.ps1` abre túnel para um worker já ligado. Ele não instala nem executa um worker Windows.

## Primeira entrega: gateway Docker Desktop

`scripts/run-platform.py` inicia `compose.control.yaml` no macOS/Windows e um worker HuntMob nativo na porta 8092. O contêiner serve `web/` e encaminha `/api/*` para o host pelo endereço `host.docker.internal`. O segredo aleatório temporário é exigido pelo worker em **todas** as requisições e o gateway remove qualquer cabeçalho de segredo recebido do navegador antes de inserir o seu. A porta do navegador é publicada só em `127.0.0.1:8090`. `Ctrl+C` encerra os dois processos e remove o segredo temporário.

Esse gateway torna a entrada Docker operacional sem alegar que Android/iOS rodam dentro do Docker Desktop. O backend da API, a política, os jobs, a análise e a evidência **ainda são executados pelo processo nativo**. O worker escuta apenas em `127.0.0.1:8092`; no macOS, a comunicação a partir de `host.docker.internal` foi observada mesmo com essa restrição. O segredo temporário acrescenta autenticação entre os processos. A mesma rota deve ser validada no Windows; se falhar, o launcher encerra os processos em vez de anunciar sucesso. Uma futura separação em agentes com conexão de saída substituirá o gateway transitório. A existência do contêiner e HTTP 200 ainda não provam boot, tela, input ou IPA.

### Validação local em 20/10/2026

No macOS arm64, `scripts/run-platform.py` construiu e iniciou `huntmob-huntmob-control-1`; o healthcheck ficou `healthy`, UI e `/api/client/ping` responderam 200 via porta 8090, e acesso direto à API nativa sem segredo retornou 403. O worker escutava somente em `127.0.0.1:8092`. A suíte local passou 629 testes Python e 28 testes Node. Android/iOS não foram iniciados nesta validação. Linux Docker/KVM e Windows não foram executados neste host.

## Arquitetura proposta

```text
Browser -> 127.0.0.1:8090 -> HuntMob control plane (Docker)
                                  |  UI, sessão, política, jobs, evidência
                                  |  canal autenticado com identidade do worker
                                  +-> host agent macOS -> Android/HVF, Simulator, xtool
                                  +-> host agent Windows -> Android/WHPX
                                  +-> worker Linux/KVM -> Android no Docker
                                  +-> worker macOS remoto -> iOS para Linux/Windows
```

O agente nativo deve iniciar conexão de saída com o control plane no loopback publicado pelo Docker. Esse canal precisa de autenticação mútua, pareamento explícito, escopo por job e expiração; não deve aceitar comandos só porque vieram de `host.docker.internal` ou de um cabeçalho HTTP. UI e agente devem compartilhar um contrato versionado para `status`, `start/stop`, `install`, `input`, `stream` e `evidence`. O servidor deve responder `unavailable` quando faltar o agente ou uma capacidade, sem simular sucesso.

Cada operação deve preservar engagement, allowlist de pacote, aprovação e recibo do HuntMob. Arquivos e segredos ficam no host de origem ou em volume privado conforme o job; upload, streaming e evidência devem ter limite de tamanho e associação à identidade do lab. O control plane não deve montar o socket Docker do host, usar `--privileged`, expor ADB publicamente ou publicar a UI fora do loopback por padrão.

## Sequência de implementação

1. Extrair das rotas de `ui.py` uma interface `WorkerProvider` com respostas versionadas. Começar com status e operações de leitura; manter o provider local atual para não quebrar Linux/nativo. O gateway acima é uma etapa transitória, não substitui esta separação.
2. Criar o agente nativo com pareamento e transporte autenticado, reconexão, timeouts e interrupção segura de jobs. Separar canais de controle, upload e vídeo.
3. Criar uma imagem multiarch para o control plane sem SDK/emulador Android. Usar `compose.control.yaml` em Docker Desktop, com porta 8090 somente em `127.0.0.1` e volumes privados. Manter o Compose Linux/KVM existente como perfil distinto.
4. Migrar ações por fatia vertical: Android status/boot/tela/input/instalação; iOS Simulator no Mac; xtool físico; proxy e análise. Cada fatia exige testes de contrato e validação em aparelho/runtime real.
5. Entregar launchers Mac, Windows e Linux que verificam Docker, acelerador e worker, iniciam o control plane e mostram capacidades observadas. O launcher não deve anunciar `ready` apenas porque HTTP 200 respondeu.

## Critérios de aceite

| Sistema | Prova mínima antes de anunciar suporte |
| --- | --- |
| Linux x86_64/KVM | `docker compose` inicia; `/dev/kvm` acessível; AVD autorizado inicia; tela e input reais; instalação em lab controlado; desligamento e retomada |
| macOS | Control plane no Docker Desktop; agente autenticado; Android HVF real e iOS Simulator vistos na mesma UI; tela, input, upload e recibos; reinício do Docker sem trocar identidade do lab |
| Windows x86_64 | Control plane no Docker Desktop; agente Windows autenticado; Android WHPX real; tela, input, upload e recibos; iOS marcado remoto/indisponível sem worker Mac |

Testes unitários e `docker compose config` verificam contrato e configuração, não substituem boot nem interação em dispositivo. Até essas provas, os modos Mac/Windows são **propostos**.

## Fontes da plataforma

- Google, Android Emulator Container Scripts: https://github.com/google/android-emulator-container-scripts — Linux/KVM; Docker Desktop em macOS/Windows não suporta esse caminho de aceleração.
- Android Developers, aceleração do Emulator: https://developer.android.com/studio/run/emulator-acceleration — KVM, Hypervisor.Framework e WHPX.
- Apple Developer, dispositivos simulados e físicos: https://developer.apple.com/documentation/Xcode/running-your-app-on-simulated-or-physical-devices — Simulator e dispositivo físico no Mac.
- Docker Docs, rede do Docker Desktop: https://docs.docker.com/desktop/features/networking/networking-how-tos/ — `host.docker.internal`; DNS não substitui autenticação do worker.
