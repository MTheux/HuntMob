# Controles iOS — validação local v1

14/10/2026. Worker macOS arm64; Apple Simulator iOS 26.0, iPhone 16 Pro. Não representa execução no emulador próprio ou Windows.

## Confirmado

- Fixture própria instalada e aberta; executável identificado por SHA256.
- Proxy exclusivo 127.0.0.1:18083, separado do Android; fixture opta pelo roteamento no seu URLSession. GET http://localhost:18089/huntmob/ping capturado com HTTP 200, visível na aba Proxy.
- Cadastro biométrico simulado e evento Face ID: fixture apresentou “Evento aprovado pelo iOS”. Não usa biometria real.
- Orientação landscape confirmada pelo readback de CoreSimulator. Retorno imediato a portrait permaneceu landscape: interface informa a divergência.
- Input e vídeo passam a vincular a sessão ao UDID selecionado. Socket abandonado só é removido quando pertence ao usuário, é socket e a conexão foi recusada.
- 49 testes focados passaram: worker, isolamento/porta do proxy, captura Android, UI, identidade e disponibilidade nativa.

## Limites

- Frida 17.23.3 encontrou o Simulator, mas attach falhou com ProcessNotRespondingError / unexpected early end-of-stream em iOS 26 e 27. Há botão experimental com erro explícito; conexão funcional não está validada. Sonda fixa de leitura, sem scripts arbitrários.
- Jailbreak não implementado. Nenhum exploit novo ou redução das proteções globais do Mac foi introduzido.
- Proxy não configura arbitrariamente outros apps, confiança TLS ou pinning. O teste não prova captura universal.
- Câmera, sensores, perfis de rede e DAST iOS permanecem indisponíveis.
- Runtime próprio continua bloqueado pela validação ANS/NVMe de armazenamento protegido. Simulator não executa IPA físico.
- Versões/modelos oferecidos são os instalados e compatíveis, sem alegação de suporte a iOS 11/15.

## Dependências

CoreSimulator/Xcode, idb-companion e cliente local; mitmdump; Frida com Simmy; driver oficial Appium CoreSim 1.12.0 em components/ios-controls. O driver usa o prebuild darwin-arm64 publicado; scripts de instalação bloqueados pelo npm não foram habilitados.

Referências primárias: https://frida.re/docs/ios/ ; https://github.com/frida/frida-core/tree/main/src/simmy ; https://github.com/appium/appium-ios .

Alterações locais, sem commit/push/deploy.
