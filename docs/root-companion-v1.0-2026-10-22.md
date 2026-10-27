# Companheiro Android com root — v1.0 — 2026-10-22

## Fluxo

1. No laboratório Android online, clique em **Companheiro com root**.
2. Escolha o app selecionado ou todos os apps de usuário.
3. A criação ocorre em segundo plano. O original permanece ligado; uma seta apresenta o progresso.
4. Clique na seta para revisar cada cópia, verificar a rede, configurar uma conexão TCP ou selecionar o companheiro no DAST.

O companheiro usa AOSP API 35 com ADB root. O original pode usar outra API: comparar este par não isola apenas a variável root. API 30 arm64 / Frida 17.23.3 permanece bloqueado por incompatibilidade registrada no runtime. Magisk para apps é um controle separado.

## Apps e dados

São instalados os APKs originais, incluindo splits e assinaturas. O SHA256 de cada arquivo é conferido na origem, no arquivo temporário e na instalação de destino. O app selecionado também precisa corresponder ao hash vinculado ao lab. Nenhum app é aberto pela sincronização. Contas, sessões, Keystore, permissões e dados privados não são copiados. Arquivos temporários são removidos ao terminar. Falhas por app são exibidas; uma cópia não comprova funcionamento em AOSP sem Google Play Services.

## Rede

A verificação envia um nonce TCP entre os dois AVDs identificados. Havendo IPs Wi-Fi distintos, tenta conexão direta. Para imagens com roteadores separados e IPs iguais, usa um forward ADB temporário em loopback e o remove ao terminar. Não é um teste do tráfego do aplicativo.

A conexão TCP opcional encaminha `127.0.0.1:19000` no principal para um serviço na porta `9000` do companheiro, com portas configuráveis entre 1024 e 65535. Usa ADB reverse e forward em loopback, sem substituir mappings existentes. O serviço precisa existir no aplicativo; a seta não sincroniza ações ou autenticação. Desative a conexão no mesmo diálogo antes de alterar portas.

A Wi-Fi compartilhada do Emulator não representa isolamento exclusivo por workspace. Ver [documentação Android](https://developer.android.com/studio/run/emulator-networking-interconnect) e [protocolo ADB](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/services.md). Um daemon ADB antigo de outra ferramenta pode recusar forwards com mais de um aparelho; use o daemon do SDK atual. Nenhum daemon é reiniciado automaticamente pelo fluxo.

## DAST e evidências

A seleção de aparelho define o runtime, o serial, o forward Frida, os eventos, as capturas e o relatório. Cada companheiro tem armazenamento próprio e só aceita o app cujo conjunto foi verificado. Nenhuma sessão inicia ao criar o par. Hashes são conferidos novamente antes de instrumentar o companheiro.

Proxy e correlação profunda REA/AI continuam disponíveis no principal; não são atribuídos automaticamente ao companheiro. Exportações e relatórios do companheiro indicam essa limitação. Interromper o worker preserva os AVDs; uma sincronização interrompida pode ser retomada pelo diálogo.

## Limites validados

Validação nativa em macOS arm64 com controle Docker e worker local. Linux e Windows usam os mesmos workers e verificações de arquitetura, porém não foram executados nesta entrega. O limite permanece quatro aparelhos ativos por workspace. Downloads de imagem exigem SDK/licenças previamente preparados; licenças não são aceitas automaticamente.

## Verificação desta entrega

Em 2026-10-22 no worker Mac: companheiro API 35 online, ADB root confirmado, sete apps e 23 APKs/splits verificados. Teste TCP temporário e conexão configurável principal:19000 → companheiro:9000 confirmados com um nonce de teste. O processo do app original permaneceu com o mesmo PID durante criação e atualização. DAST permaneceu sem sessão; somente requisitos de conexão foram consultados. Passaram 178 testes focados (125 Python e 53 JavaScript), incluindo separação de aparelho, hashes/splits, respostas atrasadas, reserva de porta e limpeza de conexões. Não representa validação de todos os fluxos ou de um finding no aplicativo.
