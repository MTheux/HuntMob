# Runtimes pendentes — progresso v1

14/10/2026. Trabalho local, sem commit/push. Os resultados abaixo não declaram concluídos os marcos de emulador iOS, IPA físico ou validação em outro sistema operacional.

## Entregue e verificado

### Preparação Windows/Linux

O worker usava `arm64-v8a` em todos os hosts, enquanto o bootstrap já tentava baixar x86_64. Agora ambos usam o mesmo contrato:

| Host | Imagem Android | Aceleração prevista |
|---|---|---|
| macOS Apple Silicon | arm64-v8a | HVF |
| macOS Intel | x86_64 | HVF |
| Windows x64 | x86_64 | WHPX |
| Linux x64 | x86_64 | KVM |

Windows/Linux ARM ficam bloqueados neste provider oficial. Não houve troca da arquitetura de nenhum lab existente. O ABI do config.ini é verificado antes de usar um AVD salvo incompatível. `bootstrap` Linux agora usa o SDK nativo, e não exige uma imagem Docker HuntMob ainda não publicada; Docker permanece opção de empacotamento.

A troca de root/stock também preserva a API selecionada, em vez de preparar ou criar implicitamente API 35 para um lab antigo.

Outro problema de primeiro uso: a preparação não instalava Build Tools/AAPT, necessário para identificar o APK. `bootstrap --install` agora inclui `build-tools;35.0.0`, mesmo quando emulador e imagem já estão presentes. Usa o Java incorporado quando seu pacote e hashes são válidos; não aceita licenças automaticamente. Falha/timeout de SDK Manager não é sucesso. `huntmob status` verifica o worker próprio em vez de depender da presença do Genymotion.

No worker Mac existente, `huntmob bootstrap` retornou ready=true, imagem ARM64 correta e AAPT presente. Matriz x64/ARM, preservação de AVD incompatível, instalação de Build Tools e timeout têm testes automatizados. **Isso não é execução Windows/Linux real.** Ainda precisamos de hosts desses sistemas para instalar, iniciar, tocar no device e capturar uma requisição.

Referências oficiais: [requisitos do host](https://developer.android.com/studio/install), [arquitetura e aceleração](https://developer.android.com/studio/run/emulator-acceleration).

### Diagnóstico no aparelho remoto

Em **Abrir janela → Validar este aparelho → Testar conexão**, o navegador faz três leituras no próprio worker e informa transporte e imagem exibida. **Baixar resultado** exporta JSON local. O relatório mantém toque, arraste, teclado e reconexão como não testados. Não coleta credenciais, URL completa ou user-agent completo e não cria finding.

Teste real em Edge/macOS: 3/3 respostas, mediana 3 ms, imagem Android H.264 visível. O JSON foi baixado e lido de volta. O contador registrou sete frames decodificados e o último frame tinha cerca de 13 segundos: tela estática não mede FPS ou fluidez sob interação. Não é medição iPad, Windows, WAN ou TLS externo.

- Os registros locais de diagnóstico foram excluídos do repositório público.

O gateway Tailscale e sua autorização continuam separados deste resultado. A validação real em outro aparelho depende de abrir o HuntMob nesse aparelho e executar tanto o diagnóstico quanto os controles manuais.

## Emulador iOS e armazenamento

Foi implementado `scripts/validate_ios_storage.py`. A leitura real do checkpoint existente verificou os hashes completos dos nove backings, incluindo namespace-1 de 32 GiB. Todos conferem com o receipt; a sonda sintética continua em claro em namespace-1. Resultado: failed, ready=false. Nenhuma VM nativa foi iniciada e nenhum desses discos foi modificado.

O leitor é incremental, verifica estabilidade dos arquivos e não publica o valor da sonda, chaves ou logs brutos. Ausência do canary nunca é convertida em prova de Data Protection. Testes cobrem limite de chunks, arquivo alterado, backing ausente/symlink e resultado negativo insuficiente.

```sh
PYTHONPATH=src python3 scripts/validate_ios_storage.py \
  --output artifacts/validation/ios-storage-audit-v1-2026-10-14.json
```

Saída 1 representa plaintext encontrado; saída 2 representa prova inválida ou insuficiente. Não há saída de sucesso que habilite o provider.

O upstream Inferno ainda aponta para `cc4302a99167abec69b714cfd00c38caece7e7de`. A revisão local confirmou `apple-ans → TYPE_NVME`, registros vendor armazenados sem tratamento criptográfico e o caminho de DMA sem associação funcional de chaves/tags. **Não foi implementada criptografia ANS/NVMe nesta passagem.** A dependência permanece: protocolo e implementação compatíveis com o SoC/firmware, vetores independentes, classes sob bloqueio/desbloqueio e persistência após boot a frio. Cifrar o arquivo no host não equivale a essa implementação.

[Auditoria de armazenamento](../artifacts/validation/ios-storage-audit-v1-2026-10-14.json). [Upstream](https://github.com/ChefKissInc/Inferno).

## Frida iOS — experimento delimitado

Foi criado um Simulator separado, iOS 26.0/iPhone 16 Pro, UUID `025A9DC8-646B-41C0-840F-95E5800DCBD3`, para a fixture própria `com.huntmob.ios.gadget.lab`. O app original não foi substituído.

O Gadget oficial específico para Simulator foi obtido com checksum de release:

| Versão | SHA256 do arquivo XZ |
|---|---|
| 17.23.3 | 62680b4f37243cc85d868a49466028e392795f4ffeeccb1003cf238f48fd9656 |
| 17.19.0 | b9cd3bf92a9e4bfd2744134c2c9420fd327219029362259cdb9fc621f475e23f |

O Mach-O inclui arm64 Simulator. A fixture foi compilada do Swift HuntMob com loader próprio e assinatura ad hoc local. Configuração: script fixo, QJS, code_signing=required, sem listener, sem hooks, sem bypass de segurança.

Comparações: 17.23.3 com carga inicial; sonda sem chamada NativeFunction; 17.19.0; 17.23.3 com carregamento depois de iniciar a UI. Nenhuma devolveu a sonda exigida. Houve crash EXC_BAD_ACCESS/SIGSEGV com FridaGadget carregado; isso não determina sozinho a causa raiz. Não foi removida nenhuma proteção do host para prosseguir.

O reprodutor está em `scripts/ios_gadget_research.py`, fora do pacote/provider de produto. Exige flag de fixture autorizada, impede substituir o app de um lab ocupado e não converte timeout em sucesso. Não foi adicionado botão que anuncie Gadget funcional. Frida genérico, jailbreak e IPA físico continuam não validados.

O Simulator de pesquisa foi desligado e preservado; foi retomado o original `958DC0B3-62DC-40F3-ACAF-D791E4FFD25F`, bundle `com.huntmob.ios.lab`. Android original e suas 500 capturas foram preservados.

Referências: [Gadget](https://frida.re/docs/gadget/), [release 17.23.3](https://github.com/frida/frida/releases/tag/17.23.3), [release 17.19.0](https://github.com/frida/frida/releases/tag/17.19.0).

## Versões antigas

Xcode 27 está instalado. O comando oficial recusou iOS 18.5 nas variantes arm64 e universal e iOS 17.5 universal como indisponíveis para download. O catálogo Apple ainda contém runtime 17.5, mas sua URL de download redirecionou para a página HTML `/unauthorized/` da Apple. Nenhum HTML foi tratado como DMG e nenhuma assinatura/verificação foi contornada. Não há runtime antigo instalado como resultado deste teste.

O [suporte publicado do Xcode 27](https://developer.apple.com/xcode/system-requirements) indica Simulator iOS 17 ou posterior. Modelos que exigem iOS 15/16 precisam de outro conjunto de host/Xcode/runtime compatível. Listar um iPhone 7/8 não resolve essa dependência. IPA físico continua exigindo um runtime de device compatível, atualmente não disponível no emulador próprio.

## Validação

244 testes Python e 13 testes Node passaram. Sintaxe Python/JavaScript e diff check passaram. Nenhum teste automatizado foi usado para declarar boot/criptografia, Frida iOS ou execução Windows/iPad concluídos.
