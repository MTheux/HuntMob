# iOS próprio: restauração local e boot pelo disco — v1, 2026-10-13

## Resultado atual

O ASR nativo do macOS concluiu a restauração do filesystem em uma cópia
exclusiva do disco virtual. O kernel iOS montou essa cópia pelo disco e
iniciou launchd sem ramdisk. SpringBoard e instalação/abertura de IPA ainda
não foram validados: a inicialização termina em panic da ROM SEP ao carregar
o firmware para operação normal.

Nada foi ativado como novo runtime disponível na interface do HuntMob.
Android, Genymotion e Apple Simulator não foram alterados. As VMs de pesquisa
foram encerradas e todas as imagens de inspeção foram desmontadas.
Alterações locais, sem commit ou push.

## Comparações e evidências

- Auxiliar x86_64/TCG com EHCI: envio chegou a 100%; ASR do guest permaneceu em
  4%. Amostras de execução e observações de CPU/disco foram preservadas.
- xHCI: falhou na enumeração USB (`error -110`); não resolveu a restauração.
  O problema também consta do upstream: https://github.com/ChefKissInc/Inferno/issues/233.
- Motor iOS com TCG em uma única thread: envio chegou a 100%, ASR continuou em
  4%. Isso não confirmou uma causa exclusiva de concorrência.
- Integridade: extraído o DMG original e convertido para raw. Comparada somente
  a partição APFS, excluindo o envelope GPT de 17.408 bytes. Todos os
  7.695.577.088 bytes recebidos são idênticos; zero blocos de 1 MiB diferentes.
  Receipt: `artifacts/validation/ios-x86-image-integrity-v1-2026-10-13.json`.
- ASR do macOS 633.0.1 validou fonte e destino e registrou
  `Restore completed successfully` no clone privado
  `~/.huntmob/research/ios-vms/native-20261013-215607`.
  Log: `artifacts/validation/ios-native-asr-v1-2026-10-13.log`.

A cópia recebeu os ajustes gráficos do patcher upstream fixado anteriormente.
Os cinco serviços incompatíveis indicados pelo guia foram desativados na
cópia, preservando backup do cache. Logging privado não foi desredigido.

## Avanços no boot

1. Boot pelo disco chegou a launchd e falhou em `mount-phase-1` por faltar
   `/private/preboot/<boot-manifest-hash>/usr/standalone/firmware`.
   A árvore foi preparada com arquivos do filesystem original. O hash do
   diretório corresponde ao SHA384 do ticket do laboratório.
2. O boot seguinte chegou a `data-protection`, mas faltava o Gigalocker.
3. Um wrapper em shell foi rejeitado pelo loader e a tarefa opcional apareceu
   como ausente. Esse resultado foi identificado como inválido e revertido;
   não estabelece Data Protection funcional.
4. O helper próprio foi compilado como Mach-O iPhoneOS/arm64, mínimo iOS 14,
   e assinado ad-hoc para o laboratório. Não possui assinatura Apple. Usa o
   identificador exigido pela tarefa do loader. Sua execução foi observada.
   Ele chama o `seputil` do ramdisk original e, somente após sucesso, executa
   o verificador original. Qualquer erro bloqueia o boot.
5. A ferramenta em modo de inicialização espera xART em `/mnt7`; o sistema
   montava o volume em `/private/xarts`. Foi criado um alias dentro do guest.
   Os logs confirmaram criação do Gigalocker e reconhecimento pelo verificador
   original. Nenhuma chave ou conteúdo do arquivo foi exportado. A criação ocorreu
   em writes efêmeros do teste e não foi persistida no clone base.
6. O verificador procurou `sep-firmware.img4` no Preboot. Depois de fornecer
   o firmware preparado, o carregamento para operação normal terminou em
   panic da ROM SEP. A variante `sepi` também não concluiu esse carregamento.
   Esse é o bloqueio atual; a causa precisa de validação adicional.

O helper não desativa a tarefa de proteção nem substitui seu retorno por
sucesso. Mesmo assim, esse experimento não comprova equivalência de Secure
Boot, SEP, Keychain, Data Protection ou attestation com um iPhone físico.

## Código e reprodução

- `scripts/boot_ios_research.py`: perfis de auxiliar, seleção TCG, preflight de
  ferramentas, progresso do ASR separado do envio e falha explícita em panic.
- `scripts/run_ios_companion.py`: auxiliar x86_64 limitada, SSH em loopback,
  USB virtual por socket UNIX, sem passthrough físico.
- `scripts/boot_ios_installed_research.py`: aceita somente clone privado
  preparado, verifica componentes/motor, recusa imagem montada e observa boot
  por disco com writes efêmeros e duração limitada.
- `components/ios-device-lab/provisioning/init_storage.c`: helper de
  inicialização, com verificação original mantida e falha fechada.

11 testes de contratos do boot passaram; sintaxe Python e diff check passaram.
O helper C compilou com `-Wall -Wextra -Werror` para iPhoneOS/arm64. Esses
checks não estabelecem uma interface utilizável nem execução de IPA.

Estado consolidado:
`artifacts/validation/ios-native-runtime-status-v1-2026-10-13.json`.
Próximos requisitos: carregar SEP normal, preparar volume Data e completar
boot, validar SpringBoard e instalar/abrir a fixture própria. O IPA de UAT
não foi instalado nem testado.
