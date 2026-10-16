# Persistência após o keybag stock — v12, 2026-10-15

**Confirmado:** o perfil virtual próprio DATA-v2 persistiu e releu a sonda
Class C após outro boot. A observação `173327` concluiu montagem stock de
Data/Update/Hardware, inicialização original do keybag com exit/signal zero,
AFU 1→1 e leitura completa dos mesmos 64 bytes, com classe 3 e digest correto.
Durou 74,28 s; 17.211 comandos AESS, nenhuma recusa AESS/NVMe/gate/IO/MPE,
nenhum panic e QMP quit/exit zero. Uma revisão independente revalidou os
recibos e o classificador. A varredura posterior dos nove backings leu
34.369.523.712 bytes, sem o marcador público em ambos os formatos.

Esta aceitação cobre **um arquivo Class C preservado nesta coorte e engine
pinados**, sob identidade/KDF/política próprios. Não comprova derivação Apple
física, outras classes, bloqueio/desbloqueio, interface ou IPA. O achado
histórico permanece aberto e `native_ready=false`.

## Baseline frio

A observação `data-v2-observation-20261015-163037` durou 75,88 s. O verificador
stock de Data Protection terminou com sucesso. O leitor próprio montou
somente Data, em modo leitura, conferiu APFS/CPROTECT e o UUID exato
`2F4BDE84-276C-414B-839A-2B2E996C1BF6`. A API indicou AFU antes e depois,
mas abrir a sonda existente retornou EPERM. Nenhum conteúdo foi lido.

O retorno 1 do leitor provocou o panic de launchd:
`boot task failure: data-protection - exited due to exit(1)`.
Não houve erro NVMe, recusa do gate protegido, comando AESS recusado ou
fault MPE nesse ensaio. Isso não transforma EPERM em uma leitura validada.

## Causa de ordem confirmada

A inspeção do **System normal** foi somente leitura; Data permaneceu
criptografado, bloqueado e sem montagem no host. O hash de `/sbin/launchd`
normal é igual ao binário stock anteriormente analisado. A ordem é:

1. `mount-phase-1`;
2. `data-protection`;
3. `mount-phase-2`;
4. `init-with-data-volume` e demais tarefas intermediárias;
5. `keybag`.

O helper inicial estava dentro de `data-protection`, antes de retornar ao
launchd. Portanto ele executou antes de `keybagd --init`. O loader stock
carrega `/private/var/keybags/systembag.kb` e associa `/private/var`.
Montar somente `/mnt2` e observar AFU não comprova essa associação.

`Boot` vem da seção `__TEXT,__config` do launchd. O cache separado
`/System/Library/xpc/launchd.plist` não fornece um override dessa tarefa.
Nenhum launchd, SecureRoot ou verificador stock foi alterado nesta inspeção.

## Segundo boot e pré-requisito FactoryData

A observação `data-v2-observation-20261015-165040` durou 79,28 s. A tarefa
stock de Data Protection terminou, a migração da media key teve sucesso
e APFS recuperou a chave do mesmo Data UUID, montando `/private/var` com
`protect`. O boot parou antes de keybag: `mount-phase-2` retornou 66 porque
a origem ou destino do bind FactoryData não existia. Não houve recusa
AESS, NVMe ou do gate protegido. O leitor pós-keybag não executou.

A inspeção separada `data-v2-mount-contract-inspection-20261015-165806-d3701eaf`
montou sequencialmente System e o Hardware próprio, ambos somente leitura.
Conferiu UUID e dispositivo real; Data permaneceu bloqueado e sem montagem
no host. O destino System existe como diretório 0755 vazio. Hardware também
está vazio: o primeiro componente `FactoryData` está ausente.

O restaurador stock `restored_external`, build 18A5351d, cria precisamente
`FactoryData/System/Library/Caches/com.apple.factorydata` no Hardware, por
mkdir recursivo 0755, uid/gid zero, somente componentes ausentes. A rotina
não muda a classe de proteção nem copia conteúdo de calibração. Essa é a
preparação mínima a reproduzir antes do próximo boot normal; o erro de
mount continua sendo propagado, sem tratamento que finja sucesso.

O preparo nativo `170707` terminou em 62,74 s: criou os cinco diretórios,
conferiu 0755/uid0/gid0 e UUID de Hardware, desmontou e chegou ao checkpoint
sem erros criptográficos ou NVMe. Helper e trustcache anteriores foram
restaurados, e o marcador próprio de preparo foi removido. O boot `170842`
ainda parou no mesmo bind, sem alcançar o handler keybag.

A inspeção somente leitura `171758-f9339a5b` confirmou que os cinco
diretórios **persistiram** após esse novo processo. O problema restante
não é a perda dessas pastas.

## Enumeração interrompida por Update ausente

**Confirmado no kernel pinado:** `DT_get_fstab_entries` termina a enumeração
ao não encontrar um role diferente de Data; devolve somente o prefixo já
construído. Na árvore servida, Update (role 192) vem antes de Hardware
(role 320). O log contém precisamente a falha de lookup de 192. Assim,
Hardware não é enumerado e o bind obrigatório posterior não encontra a
origem, mesmo com o volume e as pastas existentes.

A correção delimitada é acrescentar um volume auxiliar Update ao container
existente. A análise do `newfs_apfs` deste build confirma `-A` como append
ao container existente e **`role=p` como Update/192**. `role=u` corresponde
a User/2 neste binário e não deve ser usado. Não se deve modificar o parser,
ignorar o erro do bind ou reformatar Data.

Antes dessa operação, o scan repetível leu integralmente os nove backings:
34.369.523.712 bytes, zero ocorrências dos dois formatos do marcador,
identidades estáveis antes/depois, 17,04 s. Isso continua separado da
validação de leitura Class C após carregar o keybag.

## Ensaio pós-keybag delimitado

Os critérios abaixo foram satisfeitos em `173327`. Os ensaios anteriores
permanecem como evidência das causas corrigidas.

O novo leitor deve executar após a conclusão observada da inicialização
stock. O daemon regular usa argumentos diferentes da tarefa de boot;
ambas as rotas precisam permanecer funcionais. O ensaio deve exigir:

- o mesmo Data UUID, APFS/CPROTECT e systembag existente;
- execução original de `keybagd --init`, uma vez, com exit/signal zero;
- leitura somente da sonda já existente, classe 3 e 64 bytes, comparada
  pelo digest esperado, sem embutir os bytes da sonda no System;
- desligamento controlado, logs vinculados por hash e ausência de erros
  criptográficos inclusive durante o encerramento.

Não se deve chamar loaders por offsets, criar outro systembag, repetir
Class D/newfs, desbloquear artificialmente ou mudar a classe da sonda.
Uma recusa BFU continua sem comprovar a leitura persistente Class C.

## Evidências e limites

- `artifacts/validation/ios-own-data-v2-early-cold-baseline-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-stock-boot-contract-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-native-cold-read-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-persistent-class-c-probe-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-native-update-volume-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-mount-phase2-v1-2026-10-15.json`
- `artifacts/validation/ios-factorydata-directory-seed-contract-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-native-factorydata-v1-2026-10-15.json`
- `artifacts/validation/ios-factorydata-mount-contract-v1-2026-10-15.json`
- `artifacts/validation/ios-fstab-prefix-truncation-contract-v1-2026-10-15.json`
- `artifacts/validation/ios-stock-append-update-volume-contract-v1-2026-10-15.json`
- `artifacts/validation/ios-own-data-v2-raw-probe-after-factory-v1-2026-10-15.json`
- [Resultados de criação e varredura v11](ios-own-data-v2-progress-v11-2026-10-15.md)

Neste documento, stock/original refere-se aos bytes pinados da imagem de
pesquisa. Os CodeDirectories inspecionados são adhoc; preservar esses bytes
e identificadores não comprova uma cadeia de assinatura Apple em hardware.

O KDF e a política de armazenamento são do perfil virtual próprio. Não há
equivalência validada com UID/KDF, antirollback ou attestation do hardware
Apple. O achado histórico de plaintext permanece aberto. `native_ready=false`;
SpringBoard, interface e IPA continuam pendentes. Alterações locais, sem
commit, push, distribuição ou implantação.
