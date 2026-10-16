# Windows, identidade e emulador iOS — v1, 14/10/2026

## Implementado localmente

`scripts/connect-windows-worker.ps1` usa OpenSSH Client do Windows para
encaminhar exclusivamente 127.0.0.1 até a UI loopback do worker. Exige chave
de host previamente verificada, falha se o forward não abrir e não executa
comandos remotos. Não inicia automaticamente SSH, instala software nem
altera firewall. Ctrl+C encerra a conexão. Nenhuma senha é armazenada.

No worker, iniciar a UI normalmente em localhost. No Windows com SSH Client
e acesso autorizado ao worker:

```powershell
.\scripts\connect-windows-worker.ps1 -Worker usuario@worker-autorizado
```

Abrir http://127.0.0.1:8090 no navegador. O túnel pode pedir autenticação SSH.
Uma chave desconhecida será recusada; verificar sua fingerprint por canal
confiável antes de cadastrar em known_hosts. A conexão só funciona enquanto
a UI está executando no worker e o túnel está aberto.

Este launcher implementa acesso pelo Windows, não execução local do iOS.
Teste em Windows real, comportamento do browser e latência pela rede estão
pendentes. Não há PowerShell nem worker Windows disponível nesta validação.

`scripts/ios_readiness_report.py` é read-only: exporta estado do worker,
tipo/origem do identificador e disponibilidade do runtime próprio, sem
registrar tokens SSH ou blobs de firmware. Executar no checkout:

```bash
PYTHONPATH=src python3 scripts/ios_readiness_report.py
```

A API `/api/ios/status` inclui o mesmo objeto identity. O valor vem do registro
persistido de simctl, validado como UUID. Campos fixos rejeitam a equivalência
com provisioning físico e mantêm aceitação backend como não validada.

## UDID e acesso do aplicativo

É necessário distinguir registro Apple de dispositivo e whitelist no backend
do cliente. O UUID do Simulator não comprova um UDID de iPhone registrado.
Somente a equipe responsável pelo acesso pode confirmar qual identificador
é esperado e testar sua aceitação. Nenhum identificador será inventado para
simular registro/provisioning ou substituir o de outro dispositivo.

Referência: https://developer.apple.com/help/account/devices/register-a-single-device

## Emulador próprio: dependências ainda abertas

O checkpoint nativo inicializou SEP, keybag e classe C, mas seu dado sintético
persistiu em claro. A implementação do caminho ANS/NVMe ainda precisa:

1. Identificar o protocolo de keyslots/tags deste SoC virtual e o ponto onde
   o SEP programa o AES Engine, sem exportar chaves ou usar hardware físico.
2. Ligar essas operações ao DMA de leitura/escrita com a cifra, unidade,
   derivação e tweak/IV corretos para o firmware específico. Escolher uma
   cifra genérica ou cifrar o arquivo de VM no host não prova Data Protection.
3. Validar vectors independentes, isolamento de slots, rejeição de slots
   indisponíveis e apagamento/revogação; nunca retornar plaintext em fallback.
4. Repetir o teste persistente no conjunto completo de nove backings: canary
   ausente em claro, leitura após boot a frio, comportamento por classe sob
   bloqueio/desbloqueio e integridade após reboot.
5. Preparar os diretórios Data/Hardware do fluxo original, validar boot até
   interface e instalar/abrir a fixture de device. Só então habilitar provider.
6. Construir e testar o engine em Windows/Linux, incluindo USB virtual,
   display/input e persistência. A emulação TCG e a aceleração gráfica são
   requisitos separados da entrega de vídeo no navegador.

Não há implementação criptográfica integrada e validada após esta alteração.
O runtime próprio continua indisponível; a UI e o launcher não alteram isso.
Ver evidências em `ios-normal-sep-validation-v1-2026-10-14.md`.

Microsoft OpenSSH Client:
https://learn.microsoft.com/en-us/windows-server/administration/openssh/openssh_install_firstuse
