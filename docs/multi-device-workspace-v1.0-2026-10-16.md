# Workspace com múltiplos aparelhos — v1.0 — 2026-10-16

Atualização: **Adicionar aparelho** agora aceita Android e iPhone. Android
pode herdar o perfil ou escolher root/sem root independentemente. O limite é
quatro aparelhos no total, incluindo o principal. O MCP ganhou criação iOS e
inspeções REA explícitas (12 tools). Ver
[native-device-profiles-v1.0-2026-10-16.md](native-device-profiles-v1.0-2026-10-16.md)
e [reverse-rea-companion-v1.0-2026-10-16.md](reverse-rea-companion-v1.0-2026-10-16.md).

O restante registra a primeira validação Android, antes desta ampliação.

O botão **+ Android** cria um aparelho adicional sem desligar o principal.
Herda API, perfil root/Google Play, arquitetura e configuração de tela/CPU/RAM
do AVD principal. Apps, contas, certificados e userdata não são clonados.
Até quatro Androids por workspace; não foi medido desempenho com quatro ativos.

Cada adicional tem AVD, userdata, porta ADB, socket de vídeo, decoder e fila de
gestos próprios. As ações levam `workspace_id` e `device_id`; a API não aceita
serial arbitrário. O worker confirma a identidade do AVD no serial. O canal
direto já verificado é usado durante o gesto sem consultas ADB por movimento.

Desligar conserva os arquivos e a porta do adicional. Retomar usa o mesmo AVD.
Os registros ficam em `~/.huntmob/workspace-devices`, separados do `current.json`
do laboratório principal. Trocar o laboratório principal não adota nem apaga
adicionais. A nova visualização usa WebCodecs; requer um navegador com suporte.
As ferramentas Reverse/Frida/DAST/Proxy da interface continuam no principal,
identificado como **Principal · ferramentas**. Os controles em cada adicional
são toque, teclado, Home, Voltar, Play Store quando compatível e start/stop.

A moldura acompanha o frame real, inclusive ao rotacionar: o content box tem a
mesma proporção do vídeo, com borda uniforme de 6 px. Android não recebe a
câmera decorativa do iPhone.

## MCP

**Conectar agente** mostra a configuração stdio para um cliente no mesmo worker.
O módulo `huntmob.device_mcp` se conecta apenas ao worker em loopback, sem usar
proxy ambiente nem seguir redirects. Não inclui CSRF ou credenciais na
configuração. O adapter usa a API do processo da UI para compartilhar os mesmos
registros e verificar os mesmos identificadores.

Tools: `devices_list`, `device_screenshot`, `android_create` e `android_power`.
As mutações requerem `approved: true`; start/stop são exclusivos dos adicionais.
Não inclui shell, execução de testes de segurança ou controle de apps por MCP.
O agente recebe capturas como imagem PNG, não caminhos locais nem logs de apps.
Somente protocolos stdio 2025-03-26 e 2024-11-05 são anunciados; o cliente precisa
aceitar um deles. Não houve configuração de um cliente externo nesta etapa.

Fontes oficiais do contrato implementado:
https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
https://modelcontextprotocol.io/specification/2025-03-26/server/tools

## Validação

Mac Apple Silicon, Android API 30 Google Play arm64; principal em emulator-5556
e adicional em emulator-5558. Testes de criação, isolamento de identidade,
reserva de portas, protocolo MCP e ciclo do canal de vídeo ficam em
`tests/test_workspace_devices.py`, `test_workspace_api.py`, `test_device_mcp.py`
e nos testes de regressão de worker/codec/cliente.

Resultado: 97 testes Python e 14 Node aprovados. Na UI, o toque no ícone da
Play Store abriu a loja apenas no adicional; principal permaneceu no launcher.
Desligar/retomar conservou o AVD e emulator-5558, enquanto emulator-5556 permaneceu
online. Reiniciar o servidor preservou ambos. O MCP stdio real negociou protocolo,
listou as quatro tools, observou os dois aparelhos e devolveu PNG 1080×2400 do
adicional. O encaixe observado foi tela 252×560 dentro de moldura 264×572,
com 6 px uniformes em cada lado, sem deformação do frame 648×1440.

Recibos: `artifacts/validation/multi-device-mcp-v1-2026-10-16.json` e
`artifacts/validation/multi-device-workspace-v1-2026-10-16.{json,png}`.

Limites: não valida iOS múltiplo, hardware USB, Windows nativo nem execução de
apps de terceiros. Aplicativos e contas precisam ser instalados/configurados
separadamente em cada aparelho. Mudança local, sem publicação.
