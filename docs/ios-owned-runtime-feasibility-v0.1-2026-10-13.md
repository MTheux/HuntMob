# HuntMob: runtime iOS próprio — avaliação v0.1, 2026-10-13

## Objetivo e estado

Executar um sistema iOS virtual e IPAs autorizados no HuntMob sem iPhone físico
nem serviço Corellium. Estado: pesquisa; nenhum boot de iOS de device foi
executado ou validado neste checkout. O Apple Simulator existente é outro
runtime e não demonstra compatibilidade com IPA de aparelho físico.

## Referências verificadas

- Corellium descreve CHARM como hypervisor proprietário e modelos de hardware:
  https://www.corellium.com/platform
- ChefKissInc/Inferno é um emulador Apple Silicon derivado de QEMU:
  https://github.com/ChefKissInc/Inferno
- eShard relata experimentos com iOS 14 em QEMU, dificuldades de GPU/Metal,
  renderização por software lenta e artefatos. Essa publicação não estabelece
  compatibilidade com versões atuais nem com o IPA solicitado:
  https://www.eshard.com/blog/emulating-ios-14-with-qemu

## REA e limites da investigação

Usar documentação pública, código aberto com licença revisada e comportamento
observável de uma instalação de referência autorizada. Não há instalação
Corellium autorizada disponível para inspeção neste trabalho. Não copiar
hypervisor, imagens, código ou ativos proprietários. Registrar fonte, revisão,
licença e hash antes de incorporar componentes. Firmware Apple não será
incluído na distribuição do HuntMob sem direitos de distribuição estabelecidos.

## Arquitetura proposta (teórica)

HuntMob UI -> RPC local validado -> worker iOS -> modelo de hardware Apple
e CPU -> sistema iOS -> app autorizado. Vídeo, entrada e evidências serão
adaptadores separados. Cada VM terá disco gravável próprio; monitor e canais
de controle locais privados; rede isolada e nenhuma exposição pública padrão.

Riscos: compatibilidade de firmware e arquitetura, renderização Metal/GPU,
assinatura e criptografia de apps, redistribuição de componentes, isolamento
do guest e custo de manutenção por modelo/versão. Mitigações: versões fixadas,
fixtures próprias, limites de recursos, matriz por build e hashes de artefatos.
Snapshot não será chamado funcional antes de teste de restauração.

## Etapas com critérios verificáveis

1. Revisar licença e fixar uma revisão do candidato; compilar e inventariar
   modelos/accelerators sem iniciar firmware. Registrar tempo e recursos.
2. Selecionar um único par modelo/versão documentado e firmware autorizado.
   Validar boot e SpringBoard em VM isolada, com logs e hash do firmware.
3. Validar vídeo, toque e reinício com fixture própria. Medir latência total
   e desempenho em movimento; abrir uma tela não equivale a fluidez.
4. Instalar e abrir IPA próprio compatível; registrar plataforma Mach-O,
   versão mínima, assinatura e eventual criptografia. Não presumir que o
   IPA do usuário é compatível antes dessa inspeção e teste.
5. Integrar lifecycle, vídeo, input e evidências ao HuntMob; disponibilizar
   apenas capacidades aprovadas por teste real. Depois ampliar versões/apps.

## Condições para entregar

Boot reproduzível, fixture instalada e aberta, entrada validada, captura com
hash, recuperação de falha e restauração de snapshot testadas. Sem essas
evidências, o provider permanece experimental/indisponível. Se o candidato
falhar nos requisitos, registrar a causa antes de investir em UI ou prometer
paridade com Android/Corellium. Rollback: parar apenas a VM de pesquisa e
voltar ao Simulator existente; não modificar os labs Android.

## Trabalho realizado nesta avaliação

Pesquisa de fontes primárias e definição de critérios. Nenhum firmware foi
baixado, nenhum emulador de terceiros foi executado e nenhuma capacidade
nova de executar IPA foi habilitada. Próximo incremento concreto: auditoria
de licença e build reproduzível do candidato, anterior ao boot experimental.
