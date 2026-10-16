# HuntMob — ferramentas e controles Android

Versão 1 · 2026-10-13 · implementação local, sem commit/push.

## Direção visual e referências

Base: identidade existente HuntMob (preto/vermelho), painel opcional e emulador centralizado. Referência dominante: widgets do Genymotion; organização modular de Beerus e separação entre execução e resultados de MobSF. Ícones SVG locais, uma grade de 24 px e traço consistente. Não foram importados código, marca ou assets desses projetos.

A pesquisa Refero retornou `NO_SUBSCRIPTION`; foram usados os guias de ícones e QA da skill e as referências do usuário.

| Decisão | Origem | Aplicação |
|---|---|---|
| Canvas preto, vermelho para seleção/ação | HuntMob existente | Preservar identidade do produto |
| Navegação de ferramentas com ícones e rótulos | Organização modular Beerus + guia de ícones | Grade responsiva, teclado, seção selecionada persistida |
| Barra de widgets junto ao device | Genymotion | GPS, rede, bateria, rotação, sensores e teclas |
| Resultado antes do console | Pedido do usuário + MobSF | Métricas, candidatos, cobertura, observações e testes pendentes |
| Falhas operacionais distintas de achados | Contrato HuntMob | Estado retornado do Android; candidato não equivale a vulnerabilidade confirmada |

Referências:
- https://github.com/hakaioffsec/beerus-android
- https://github.com/MobSF/Mobile-Security-Framework-MobSF
- https://docs.genymotion.com/features/basic_features/
- https://docs.genymotion.com/features/gps/
- https://developer.android.com/studio/run/emulator-console

## Controles implementados

`POST /api/device/control` preserva CSRF e autorização/aprovação do servidor. Só aceita ações fixas, perfis conhecidos e números finitos limitados. Confere o nome real do AVD contra o laboratório selecionado e serial; não recebe texto de shell. A operação é serializada com a troca de laboratório.

- GPS: ativar localização e enviar `geo fix`; longitude precede latitude. O app precisa de permissão e consumir GPS. Aceitação do comando não comprova consumo pelo app.
- Rede: Wi-Fi, dados móveis e offline alteram os rádios, preservando o proxy. Velocidade/latência normal, EDGE e LTE atuam na rede celular/ethernet emulada; não limitam Wi-Fi.
- Bateria: carga 0–100 e restauração com `dumpsys battery reset`.
- Rotação: retrato, paisagem e automática. Apps com orientação fixa podem ignorar a solicitação. Toque usa as dimensões do viewport real do Android.
- Sensores: vetor de aceleração em m/s², eixos −20 a 20, apenas no sensor emulado.
- Sistema: home, voltar, recentes, volume e acordar tela.
- Câmera: abre o aplicativo de câmera Android configurado no AVD. A fixture facial do navegador permanece separada e não injeta imagem no app.
- Screenshot, Proxy e Frida: atalhos para os fluxos existentes, sem abrir interfaces externas.

O painel apresenta leitura de bateria, rádios, localização habilitada, rotação, aceleração e perfil de rede. Comandos aceitos não são prova de vulnerabilidade nem de execução de um fluxo do aplicativo.

## DAST e Frida

O relatório visível em **DAST → Resultados DAST** inclui severidade, CWE, descrição, remediação e referências para cada candidato; os seis monitores detalham APIs avaliadas, métodos observados, hooks e próximos testes. Rede agrega hosts, HTTP/HTTPS, erros HTTP e falhas de conexão. JSON e HTML incluem observações e testes pendentes.

Lógica de negócio, autorização, ciclo de sessão, exposição de dados, injeção e configuração têm estados explícitos `not_assessed` nos testes manuais. Não há nota de segurança ou declaração de ausência de falhas baseada em monitor sem chamadas. Captura é do laboratório, sem atribuição exclusiva automática de cada fluxo ao processo do app.

O início DAST usa todos os seis observadores, independentemente da seleção parcial do Frida. Frida mostra monitores disponíveis, seleção rápida e recursos indisponíveis recolhidos; nenhum bypass adicional foi implementado neste trabalho.

## Validação

Mac local, Android 15/API 35, AOSP com root, `emulator-5556` e app laboratorial `com.android.insecurebankv2`.

- UI: menu, Frida, seleção dos seis monitores, ação GPS, rede offline/Wi-Fi, abrir câmera Android e regenerar relatório DAST.
- Offline: Wi-Fi=0, dados móveis=0 e tabela de rotas vazia. Rede restaurada depois do teste.
- GPS: console aceitou posição sintética e Android informou localização habilitada; consumo no app alvo não validado.
- Bateria: leitura confirmou carga 15%; simulação removida depois.
- Rotação: `lock 1`, seguida de `free`. App alvo mantém retrato.
- Aceleração: leitura confirmou `1:9.81:0`; vetor anterior restaurado.
- EDGE: 473600 bits/s, latência 35–200 ms. Perfil sem limite restaurado.
- DAST: relatório regenerado sobre sessão real persistida: 40 eventos, 6 requisições, 1 candidato CWE-319 para revisão. Não representa nova autenticação nem confirmação de impacto em produção.
- 134 testes, `node --check web/app.js` e `git diff --check` passaram.
- QA visual no viewport padrão e em 1280×800; override removido após teste.

Evidências locais: `artifacts/validation/device-controls-v1-2026-10-13.json` e `artifacts/validation/workbench-dast-1280-v1-2026-10-13.jpg`. Não validado em Windows, Android sem root, todos os apps, ou como equivalente integral ao MobSF.
