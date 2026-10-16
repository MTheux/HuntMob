# Lateral de aparelhos e laboratórios — v1.0 — 2026-10-16

Estado: implementação local, sem commit, push ou deploy.

O inventário lateral agora mostra todos os aparelhos do workspace, com papel
principal/adicional, estado, API/versão, perfil root e serial/ID. O contador
descreve explicitamente aparelhos online neste laboratório; o Simulator avulso
do worker aparece em Outros dispositivos, separado desse total.

Os labs salvos são agrupados por package, preservando cada AVD. Variantes exibem
API, root/sem root e seis caracteres do ID, com identificador completo no título.
O grupo atual abre inicialmente e a variante atual recebe marcação visual e
aria-current. Retomar outro lab conserva a confirmação e o fluxo já existentes;
selecionar o lab atual não reinicia o aparelho.

A busca única filtra aparelhos e labs por package, plataforma, serial/ID, API e
perfil. Grupos compatíveis expandem durante a busca; há estado sem resultados.
O botão + abre Novo laboratório. Clicar em um adicional localiza sua tela e
move o foco de navegação, sem enviar toque ao aparelho. O worker fica no rodapé,
com detalhes recolhidos. Cabeçalho e rodapé permanecem acessíveis enquanto o
inventário/histórico rola.

Design: sistema HuntMob existente, preto/cinza, vermelho na seleção e verde
para online. Desktop com lateral de 280 px; drawer compacto em tela estreita.
Pesquisa Refero indisponível por assinatura; usados o screenshot atual e os
guias de foco/formulários do Refero Design. Decisões registradas no UI ledger.

## Verificação

- Browser Edge local: quatro aparelhos do laboratório e nove labs em quatro grupos.
- Busca API 30: dois labs. Busca Sem root: dois aparelhos e três labs.
- Termo inexistente: estado vazio. Limpar busca: inventário/grupos restaurados.
- Seleção do adicional emulator-5562: foco na tile e rolagem horizontal observados.
- Botão +: formulário Novo laboratório aberto e fechado, sem criar nada.
- Drawer em 900×900: abre sobre o workbench, com busca/worker fixos e corpo rolável;
  override de viewport removido ao terminar.
- 14 testes Node de sessão, geometria, vídeo e toque; 26 testes Python de UI/API aprovados.
- Sintaxe JavaScript e git diff --check aprovados.

Nenhum emulador foi criado, desligado, trocado ou apagado nesta repaginação.
Não foi testada retomada de outro lab, pois isso desligaria o atual. O backend
de dispositivos permaneceu intacto; o novo inventário usa seus dados observados.

Artefatos em artifacts/validation/device-sidebar-*-v1-2026-10-16.*.

Acabamento final: cartões adicionais e Simulator externo em duas linhas,
sem repetir o rótulo Adicional em cada item. O principal conserva rótulo
próprio. IDs curtos distinguem os dois iPhones Simulator do mesmo modelo.
