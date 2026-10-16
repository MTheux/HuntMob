# Comparação de restauração iOS com auxiliar x86_64 — v1, 2026-10-13

## Objetivo e isolamento

Comparar a auxiliar ARM anterior com a arquitetura x86_64 do exemplo
upstream, usando o mesmo firmware iOS 14.0 beta 5 (18A5351d), motor iOS,
ROM/firmware SEP e ferramentas libimobiledevice fixadas. Os discos anteriores
permanecem intactos. Cada restauração usa um novo disco iOS; nenhum device
físico é conectado. Android e Apple Simulator não são modificados.

## Preparação confirmada

- Inferno `cc4302a99167abec69b714cfd00c38caece7e7de`, novo build x86_64-softmmu.
- Executável auxiliar SHA256 `d4764dd8498302551316ee6eaab2045e8bb9de24a183e120698afbdbc30b39da`.
- Ubuntu 24.04 amd64 oficial, SHA256 `6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2`, comparado ao SHA256SUMS do publicador.
- Linux x86_64 e acesso SSH local confirmados; senha SSH desativada.
- Q35/TCG, USB EHCI, comunicação com iOS por socket UNIX privado.
- SSH vinculado somente a `127.0.0.1:33227`; nenhum passthrough USB físico.
- Corrigido o volume da configuração cloud-init para `cidata`. A primeira
  imagem de configuração não era reconhecida e a rede não era preparada.

## Reprodução

Após preparar a auxiliar privada e suas ferramentas, executar:

```sh
python3 scripts/run_ios_companion.py --authorized-lab --seconds 1800
python3 scripts/boot_ios_research.py --authorized-lab --restore-session \
  --sep-emulated --companion-profile x86_64 --seconds 1800 \
  --ipsw ~/.huntmob/research/firmware/iPhone11,8,iPhone12,1_14.0_18A5351d_Restore.ipsw
```

Iniciar idevicerestore como serviço limitado na auxiliar e desconectar SSH
antes da transferência. O guia alerta para instabilidade USB e contenção
causada por conexões SSH. Isso é uma condição de teste, não causa confirmada
do bloqueio anterior.

## Correção de lifecycle confirmada

Uma inicialização durante o build das ferramentas chegou à recuperação, mas
reiniciou após o timeout de 120 segundos sem início de restore. O reboot
terminou com `t8020dart invalid lock state`; QEMU saiu com código zero.
Receipt: `~/.huntmob/research/ios-vms/boot-20261013-212123/receipt.json`.
Isso é distinto do ASR anterior: neste experimento o ASR nem iniciou.

O boot x86_64 agora exige `ready.json` da auxiliar com ferramentas verificadas
e o checksum do firmware. O serviço de restauração espera o device USB virtual,
e o diagnóstico separa progresso ASR, término da etapa 1 e sistema utilizável.
Um panic gera estado `failed-panic` e retorno não zero do supervisor.

## Resultado

As oito ferramentas fixadas compilaram com sucesso. O checksum do IPSW
também foi verificado dentro da auxiliar. Restauração iniciada no novo
`boot-20261013-213038`, sem SSH conectado. O supervisor registra observações
de transferência, ASR, alocação de disco e consumo de CPU em
`artifacts/validation/ios-x86-restore-observations-v1-2026-10-13.jsonl`.
Conclusão do restore e SpringBoard ainda pendentes; nenhuma instalação de IPA
ou disponibilidade de runtime de produto foi declarada.

Fontes primárias: https://chefkiss.dev/guides/inferno/companion-setup/,
https://chefkiss.dev/guides/inferno/running-restoring/,
https://cloud-images.ubuntu.com/releases/noble/release/SHA256SUMS.

## Atualização do resultado

EHCI x86_64 e TCG single no motor iOS não ultrapassaram ASR 4%. xHCI não
enumerou o USB. A comparação raw APFS confirmou integridade completa. O ASR
nativo do macOS restaurou um clone e o boot por disco chegou a launchd;
o bloqueio atual é o carregamento SEP normal. Consulte
`ios-native-restore-validation-v1-2026-10-13.md` para a evidência consolidada.
