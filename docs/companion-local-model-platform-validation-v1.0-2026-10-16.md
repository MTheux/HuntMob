# Companion local e validação de plataformas — v1.0 — 2026-10-16

Estado: implementação e verificação locais. Sem commit, push ou deploy remoto.

## Modelo no Reverse

O worker consulta apenas `127.0.0.1:11434` para detectar o modelo instalado
`hermes3:8b`. A conexão ignora proxies e redirects; modelos `:cloud` e endpoints
fornecidos pelo navegador não entram neste fluxo. A UI distingue REA pronto,
Companion preparado e modelo conectado.

**Avaliar com modelo local** exige ação explícita, CSRF, autorização e aprovação,
além de uma Evidence REA concluída para o workspace, run e SHA256 selecionados.
O prompt usa resultados estáticos limitados, sem APK binário, caminho do APK,
shell, toque no aparelho ou tráfego do app. Observações precisam citar Evidence
IDs da execução; a revisão fica como `needs_review` e
`independently_verified: false`. Jobs do modelo têm estado próprio e uma execução
interrompida não aparece como concluída após restart.

Validação: a chamada real ao Ollama respondeu com o modelo local. Em uma fixture
isolada, uma Evidence sintética produziu uma revisão `local-ollama` com uma
observação citada, ainda pendente de revisão humana. Nenhuma avaliação do
aplicativo de terceiro selecionado foi iniciada.

## Plataformas observadas

| Caminho | Evidência atual | Limite |
| --- | --- | --- |
| Android local | AVD salvo online; API 35, arm64; UI e captura responderam | Sem teste autenticado do app de terceiro |
| Apple Simulator no Mac | iOS 26.0 iniciou, fixture HuntMob visível; toque na UI elevou o contador de 0 para 1 | Exige build `.app` para Simulator; não valida IPA físico |
| iOS virtual próprio | API marcou `virtual_ready: false`, `state: blocked` | Interface, IPA e proteção completa pendentes |
| Viewer Windows x64 | ZIP existente com tamanho e SHA256 iguais ao manifesto; três testes de política passaram | Executável não foi rodado em Windows; pacote sem assinatura |
| Controle Windows → Mac | CLI descreve uma topologia possível | Despacho remoto nativo não validado; confiança marcada `theoretical` |

A inspeção visual foi feita no Edge na UI local, no painel Reverse e no canvas
do Simulator. O modelo apareceu conectado; o botão ficou desabilitado no app
selecionado porque não havia Evidence REA concluída para esta execução. A
ligação do modelo não promove análise estática a vulnerabilidade confirmada.

Validação autenticada depende de escopo vigente, ações permitidas e duas contas
de teste distintas. O endereço de alias recebido isoladamente não comprova
autorização nem fornece essas contas.
