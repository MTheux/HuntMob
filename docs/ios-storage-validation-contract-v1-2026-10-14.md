# Contrato de validação do armazenamento iOS

Versão 1 · 2026-10-14

## Limite da auditoria atual

`validate_checkpoint()` é uma auditoria local somente de leitura de um checkpoint e de seu receipt. Ela percorre os nove backings, verifica os hashes declarados e busca a sonda sintética registrada no log. Ela não implementa ANS/NVMe, não inicia o guest e não comprova Data Protection.

O resultado mantém `ready=false` e `data_protection_validated=false` em todos os casos. Um roundtrip em memória, um hash consistente ou a ausência da sonda em claro não autoriza anunciar um emulador funcional. Campos adicionais no receipt, inclusive alegações de sucesso do motor, não alteram essa regra.

## Integridade da leitura

Receipt e logs têm limites aplicados à leitura real, além da verificação de tamanho. Os arquivos são abertos por descritor, sem seguir o último symlink quando o host oferece `O_NOFOLLOW`, e sua identidade e natureza regular são verificadas antes de consumir conteúdos. `O_NONBLOCK`, quando disponível, evita ficar bloqueado se um arquivo for trocado por um FIFO entre a inspeção e a abertura.

O fingerprint considera dispositivo, inode, tamanho, mtime e ctime. Os backings são comparados tanto no início/fim de sua leitura quanto após a leitura dos demais arquivos. Receipt, logs e inventário de logs também são reavaliados ao final. A busca da sonda preserva uma janela de bytes entre chunks, inclusive quando o chunk é menor que a sonda.

Esses controles detectam alterações observáveis durante a auditoria. Eles não substituem um snapshot imutável nem uma garantia do host contra um escritor malicioso: uma coorte que muda constantemente não pode ser certificada por inspeções sequenciais. Execute a auditoria sobre um checkpoint preservado, com o VM desligado, sem outros escritores.

## Semântica dos resultados

- `failed`: sonda encontrada em claro ou coorte divergente/instável.
- `not_proven`: evidências consistentes e sonda não encontrada, mas criptografia não demonstrada.
- `cohort_matches`: todos os nove hashes correspondem ao receipt e as evidências inspecionadas permaneceram estáveis.
- `evidence_stable`: fingerprints e inventário de logs permaneceram consistentes nas verificações efetuadas.

Hashes do próprio receipt indicam consistência; sem uma origem confiável independente, não autenticam quem produziu o motor, logs ou discos. A auditoria não imprime o valor da sonda.

## Evidências necessárias antes de promover um motor recompilado

Uma futura validação do motor precisará de uma origem verificável do source/build/binário e testes independentes do caminho real SEP → ANS/NVMe → APFS. Deve demonstrar algoritmos, unidades/tweaks e slots de chave compatíveis com o firmware por vetores conhecidos, rejeitar estado/chaves inválidos sem fallback em claro e associar a prova ao binário testado.

A prova no guest precisa incluir escrita persistente, shutdown/cold boot, leitura autorizada após desbloqueio e comportamento das classes aplicáveis sob bloqueio, revogação e perda de chaves. O status não pode ser liberado com flags fornecidas pelo próprio receipt ou com uma sonda de RAM. Criptografia do disco do host não substitui esses testes.

Boot normal até SpringBoard, tela/entrada e instalação/abertura de um IPA compatível são marcos adicionais. Devem ser validados separadamente; nem a auditoria de armazenamento nem a recompilação de um motor já existente os estabelecem.

## Verificação desta alteração

13 testes locais passam, incluindo sonda cruzando múltiplos chunks, ausência insuficiente para aprovação, mutação de um backing já lido, alteração do receipt, inclusão tardia de log, troca por symlink/FIFO, receipt malformado, versão booleana indevida e log acima do limite. Nenhum checkpoint real foi alterado ou relido neste trabalho.
