# Perfis de laboratório — v1, 14/10/2026

Novo lab agora permite plataforma e versão. Android aceita API 30–35
(Android 11–15), preserva versão no registro e encaminha a seleção tanto
para lab vazio quanto upload. Cada versão/perfil requer sua imagem instalada;
APIs 31–34 foram verificadas em contrato, sem boot real nesta mudança.
Perfis com e sem root permanecem em dispositivos separados.

Para iOS, a API de catálogo usa runtimes e modelos instalados no Xcode. O
modelo é filtrado por min/max de runtime; o backend também recusa combinações
incompatíveis antes de criar/desligar o lab anterior. Nenhum runtime antigo
é inventado ou instalado implicitamente. iPhone 7/X não aceitam iOS 27 no
catálogo deste worker. Jailbreak permanece uma opção disabled: não há runtime
compatível validado e não é equivalente a desligar root do ADB.

Validação real: criado um novo iPhone 16 Pro com iOS 27 pelo modal, lab vazio,
perfil sem jailbreak; boot concluído e menu DEVICE visível. O Simulator anterior
foi desligado, mantido no CoreSimulator e seu registro privado foi preservado.
Android existente permaneceu ligado. Cada lab iOS usa socket de bridge próprio
para evitar encaminhar controles ao device anterior.

GPS: painel enviou coordenadas sintéticas 0,0 e simctl aceitou a operação.
Não comprova que outro app tenha recebido a posição ou concedido permissão.
Bateria: override do indicador 42 foi aceito e apareceu no readback da barra de
status. O painel declara que não modifica as APIs de carga/energia do app.
Home e captura permanecem disponíveis. Biometria, câmera, rede, rotação,
sensores, recentes, proxy e Frida não foram implementados neste perfil e
permanecem visíveis/desabilitados com indicação de indisponibilidade.

O runtime iOS próprio com IPA continua indisponível. Estas mudanças são no
perfil Apple Simulator e não validam jailbreak, criptografia ou execução de IPA.
60 testes focados, sintaxe JavaScript e diff check passaram. Trabalho local,
sem commit/push nesta execução.
