# HuntMob Proxy Workbench — v1.0 (2026-10-16)

## Entrega local

- Navegação lateral separa Dispositivo, Arquivos, Reverse, Frida, DAST, Proxy e Evidências. O Proxy pode ocupar a largura do workspace no desktop; o Android volta com um clique.
- O Proxy Android tem áreas de Histórico HTTP, Repetir requisição e Configuração e CA. O histórico oferece busca, host, método e status; selecionar uma linha abre o editor e a resposta capturada. O envio continua limitado ao lab atual pela API existente.
- A configuração de Burp exige um listener acessível no `127.0.0.1` do worker. O Android Emulator recebe `10.0.2.2:porta`. A UI distingue listener HuntMob de listener externo e confere se a rota do Android corresponde à porta selecionada. O histórico do Burp permanece no próprio Burp.
- O assistente de CA aceita somente um arquivo `.cer`, `.crt` ou `.pem` de até 1 MB pela interface, recusa PEM com chave privada detectável e envia o arquivo ao `Downloads/HuntMob` do Android escolhido. O botão de segurança abre os ajustes do Android. A instalação e a confiança são ações manuais e permanecem **não verificadas** até um teste HTTPS no app autorizado.

## Verificação nesta retomada

- `PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q`: 627 testes passaram.
- Chromium local em 1500 × 900: navegação, histórico, seleção para replay, foco de tela inteira e setup sem erro JavaScript. Em 600 × 900: navegação horizontal e setup sem overflow da página.
- Uma CA de teste descartável foi enviada pela UI ao Android 11 Google Play; a resposta indicou somente entrega em Downloads. O arquivo de teste foi removido do Android e do host. O botão abriu a tela de segurança do mesmo emulador. **Nenhuma CA foi instalada nem marcada como confiável** nesta verificação.
- A UI local foi reiniciada em `http://127.0.0.1:8090`. Alterações permanecem no worktree, sem commit ou push.

## Limites para pentest Android

- O HuntMob registra e repete requisições; ainda não implementa uma fila de interceptação ao vivo com Forward/Drop, nem substitui o Burp Suite.
- Apps Android que não usam a rota de proxy podem não aparecer. Apps com target API 24+ não confiam em CAs adicionadas pelo usuário por padrão; certificate pinning e configuração própria de TLS exigem verificação específica no app autorizado.
- O listener Burp externo e um fluxo HTTPS real com CA instalada não foram exercitados nesta retomada.
- A matriz Android 11–16 ARM64 e root para apps ainda exige validação por imagem/perfil. O Frida no Android 11 AOSP tinha falha conhecida nesta cópia; as demais combinações não são consideradas prontas por esta mudança de UI.
