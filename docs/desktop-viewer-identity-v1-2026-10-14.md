# Viewer desktop e identidade iOS — v1, 14/10/2026

## Uso

Selecione Android/iOS no HuntMob e clique **Abrir janela**. Há janela dedicada no navegador, abertura do app instalado pelo protocolo huntmob-viewer e downloads portáteis.

Pacotes locais em dist/viewer: macOS Apple Silicon (.app dentro do ZIP), Windows x64 (.exe com bibliotecas dentro do ZIP), Linux x64 (binário e bibliotecas dentro do ZIP). Extraia o pacote inteiro; não copie só o EXE. O viewer não inclui Android/iOS, ferramentas de pentest, firmware nem uma VM exportada. Ele conecta ao worker existente.

Abra HuntMob Viewer e informe http://127.0.0.1:8090/ para o worker neste computador, ou a URL HTTPS privada .ts.net para acesso pelo Tailscale. Em outra máquina, localhost aponta para essa outra máquina; use a URL remota. Worker ligado e Tailscale conectado continuam necessários. Fluxo do protocolo de abertura foi observado no Mac, passando plataforma iOS e UUID do dispositivo selecionado.

## Identidade

Em iOS → Perfil, a identidade observada é exibida completa, com Copiar identificador e Exportar identidade. O JSON preserva kind=simulator-uuid, source=Apple simctl e apple_physical_device_provisioning_supported=false. O identificador não comprova UDID físico, provisioning Apple ou aceite do backend da Claro. UDID físico observado continua na seleção USB da integração xtool; nenhum dispositivo físico foi validado nesta alteração.

## Validação

- 23 testes Python focados: downloads allowlist/tamanho, identidade e UI; 3 testes Node de URL/protocolo: 26 passaram.
- Viewer macOS arm64 executado. Janela exibiu tela Android e iOS; abertura pelo link do HuntMob passou platform=ios e UUID esperado. Não houve teste de desempenho nem de conexão remota pelo viewer.
- Três downloads verificados por HTTP local com tamanho e SHA256 comparados aos manifestos.
- Exportar identidade acionado pela interface; arquivo em Downloads lido com kind simulator-uuid e provisioning físico false.
- Windows e Linux empacotados; execução nesses sistemas permanece pendente. macOS Intel não foi empacotado.
- Pacotes ainda sem assinatura de distribuição/notarização. Nenhuma proteção do sistema foi desabilitada para executá-los. A execução local no Mac não estabelece distribuição sem alertas em outras máquinas.
- Página avisa se o UUID iOS selecionado mudar; isso é um guard de interface, não isolamento de controle entre usuários. Todos os viewers compartilham o worker e a seleção de lab existente. Não operar laboratórios diferentes simultaneamente no mesmo worker.

## Engenharia

Electron 44.7.2; @electron/packager 20.3.0, fixados. Sandbox/contextIsolation/webSecurity ativos; nodeIntegration remoto desativado; sem preload remoto ou IPC de shell. Destinos aceitos: loopback HTTP ou HTTPS do Tailscale, sem credenciais na URL. Popups e navegação para outra origem bloqueados; permissões negadas por padrão. IPC de conexão disponível somente na página local de configuração. TLS não é desativado.

Build:

```sh
cd components/desktop-viewer
npm ci --ignore-scripts
npm test
npm run package -- darwin
npm run package -- win32
npm run package -- linux
cd ../..
python3 scripts/package_viewer.py
```

O script de arquivamento recria o manifesto com execução pendente; validação de execução deve ser registrada separadamente após testar cada pacote. Artefatos são excluídos do Git, sem commit/push/deploy nesta alteração.

Referências: https://www.electronjs.org/docs/latest/tutorial/security ; https://github.com/electron/packager .

## Revisão — somente dispositivo e macOS nativo leve

Viewer oculta topbar, navegação, Workbench, menus de criação e links Proxy/Frida. Exibe tela, controles do dispositivo, zoom, teclado e Voltar/Home. Site permanece responsável pelas ferramentas e criação do lab.

Novo macOS arm64 usa AppKit/WKWebView do sistema, sem Chromium embarcado. Build `python3 scripts/build_viewer_macos.py`; bundle separado em build/viewer-native. Download Mac agora empacota esse bundle quando disponível. .app observado ~96 KB; ZIP observado 23.174 bytes. Vídeo iOS e ação Home foram validados pela janela nativa (tela inicial observada). Toque por coordenadas via automação encontrou erro de posicionamento da janela; não foi usado como prova de gesto validado nesta revisão. Windows/Linux continuam Electron, 157.788.211/122.890.197 bytes; clientes nativos leves nesses sistemas ainda pendentes.

Downloads têm Accept-Ranges, 206/416, ETag/If-Range e cache privado. HTTP real bytes=0-31 retornou 206 e 32 bytes corretos; ZIP Mac baixado e hash validado. Tamanho menor no Mac não comprova latência WAN nem velocidade garantida do download.
