# Cadastro, Workbench e loja — v2, 14/10/2026

## Confirmado localmente

- iOS mostra somente .app.zip ou lab vazio, Bundle ID e mensagens iOS. Play Store, SDK legado Android e root ficam ausentes. Opções de origem ainda não implementadas (Firebase/URL assinada) removidas do formulário em vez de prometer comportamento inexistente.
- iPhone 7/8/X disponíveis no catálogo observado do simctl. Seleção iPhone 7 com iOS 26 bloqueia criar e mostra intervalo observado iOS 10–15. iPhone 8 exige runtime iOS 11–16 neste catálogo. iOS 11–18 listados como runtimes compatíveis não instalados; não são executáveis disponíveis. Worker atual só tem iOS 26/27. Não foi instalado/validado runtime antigo nem prometida compatibilidade dele com este Mac.
- Android Play Store força perfil sem root Google Play, cria lab separado e abre com.android.vending via ação limitada ao device. Login e instalação reais continuam manuais no device; Não há formulário de credenciais Google no HuntMob; controles remotos encaminham a entrada para a tela do dispositivo.
- Abertura real da Play Store validada em AVD HuntMob stock existente, sessão temporária read-only porta 5580. Boot e comando de abertura retornaram sucesso. Nenhum login, download ou instalação de app da loja foi realizado. Sessão temporária encerrada e seleção/labs originais preservados.
- Rail duplicada/inativa removida; abas são a única navegação de ferramentas. Workbench recebe 60% da área; Frida divide alvo/biblioteca e execução/retorno nas áreas largas, com console limitado e execução visível ao rolar scripts. Layout menor mantém painel recolhível.
- 63 testes focados passaram (Android, loja, downloads/ranges, acesso remoto, iOS e UI); formulários iOS/Play Store, seleção iPhone 7 e layout Frida verificados no navegador.

## Ainda pendente

Execução de iOS antigo, jailbreak, Frida iOS funcional, câmera/sensores iOS, cliente Windows/Linux leve/validado, assinatura de distribuição e funcionamento do download sob rede WAN. Não confundir catálogo de opções com runtime instalado.

Mudanças locais, sem commit/push/deploy.

Layout Frida também verificado em 1024×768, com execução/retorno ao lado da biblioteca e painel recolhível; viewport restaurada. Captura desktop salva em docs/measurements/workbench-v2-2026-10-14.png. Console readback exibiu o recibo histórico das 17:39, não uma nova sessão executada nesta revisão. Gateway Tailscale reiniciado com suporte aos headers de cache/range; URL privada preservada.
