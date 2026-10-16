# Root para apps no mesmo AVD — v1.0 (2026-10-16)

O controle **Root apps** usa o setup temporário para emuladores do [Magisk v30.7](https://github.com/topjohnwu/Magisk/blob/v30.7/docs/faq.md) no AVD AOSP userdebug já selecionado. O setup reinicia os processos Android; não cria outro AVD e não apaga os dados. Após reiniciar o emulador, é preciso ativá-lo novamente.

O worker obtém o APK oficial e `scripts/live_setup.sh` do commit fixado `e8a58776f1d7bdf852072ad0baa6eceb9a1e4aac`, confere SHA256 antes de executar e guarda cópias em `~/.huntmob/tools/magisk-v30.7/`. Requer rede na primeira ativação. O Magisk é [GPL-3.0](https://github.com/topjohnwu/Magisk/blob/v30.7/LICENSE).

**Escopo do estado:** “Root apps · ativo” confirma o daemon Magisk no AVD. Cada aplicativo ainda precisa solicitar `su` e receber autorização individual no Magisk. Isso não afirma que um app específico recebeu root. O antigo controle de ADB root continua disponível pela API `root-status`/`root-toggle`; são estados independentes.

**Validação local:** no AVD `huntmob_lab_77748c4ff83849ed821effbd84c421fd` (API 35, arm64), desativação e reativação mantiveram o mesmo nome de AVD. Um app de teste descartável, com UID próprio, obteve `uid=0` e contexto `u:r:magisk:s0` após permissão no Magisk. A permissão e o app de teste foram removidos após a validação. Nenhum teste de vulnerabilidade foi realizado no app de terceiro.
