# Reverse com REA e Reconstruction Companion — v1.0 — 2026-10-16

Estado: local, sem commit/push/deploy. Análise estática, sem chamadas aos backends
de apps, testes de exploração ou execução automática de modelo.

## Comportamento

Depois de preparar o Reverse, **Analisar com REA** oferece package/Manifest,
busca de classes, membros de uma classe, decompilação de um método (com índice
de overload explícito quando necessário) e referências de uma classe.
As operações usam o CLI REA real e retêm a Evidence completa. O resultado inclui
provider, digest, locations, confidence e limitações. Decompilar pelo JADX
integrado continua sendo uma etapa diferente de inspecionar com REA.

O pedido carrega workspace_id, package_id, run_id e SHA256. O servidor compara
todos com a seleção atual e o base.apk, copia um APK privado por job e confere
o digest devolvido pelo REA. Se a seleção, APK ou decompilação mudar durante a
execução, ela falha sem publicar resultado como vigente. Jobs anteriores são
preservados por execução. Após restart, jobs sem executor vivo aparecem
interrompidos, não concluídos.

Após uma Evidence REA concluída, **Aprofundar com Companion** prepara um ZIP com
contexto, evidências, objetivo, lacunas e a skill/referências verificadas. Não
inclui o APK nem copia toda a árvore decompilada. Estado explícito:
`awaiting_agent`. Esta preparação não equivale a uma avaliação feita por modelo.

O agente do usuário pode conectar o MCP exibido em **Conectar agente** e usar
`reverse_target` para descobrir o run/SHA atual, `reverse_inspect` para uma
inspeção offline aprovada, `reverse_jobs` para resultado e `reverse_context`
para carregar o contexto Companion. `reverse_record_review` permite devolver
uma avaliação ao Reverse: observações citam Evidence IDs desta execução;
inferências e lacunas ficam separadas. A UI recebe em “Atualizar avaliação do
agente”, sempre como precisa de revisão, sem confirmação independente. Não há shell arbitrário, input de aparelho,
execução de exploits nem operações de rede contra o aplicativo nessas tools.
Não foi conectado um cliente externo nesta etapa.

## Providers locais e proveniência

- REA core 6.0.0, checkout local em
  `/Users/mftheux/.codex/worktrees/rea-draxen/components/draxen-re-core`, HEAD
  `7d18b034f0965adf49d3355e1e459994678c273a`. CLI compilado existente.
- JADX headless MCP 0.7.1, release oficial do projeto, revision
  `5844800a486d2248fa949b74c9896285f5b54de2`, SHA256
  `6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75`.
- Companion 1.3.5, MIT, commit `9f88da88dcaa819217d58eb57fe84655cf8bac27`.
  Skill SHA256 `8c5c6002fb027cd71ed731d944ee9bb30e31997673dcdd986257648454660ec5`.
- JDK completo existente: Homebrew openjdk@25. O runtime Java embarcado usado
  pelo JADX CLI não executou a ponte Java source do REA neste teste.

Configuração privada do worker: `~/.huntmob/providers/reverse.json`, com
`rea_cli`, `jadx_jar` e `java_home` absolutos. Estes caminhos não são portáveis;
outro worker deve fornecer seus próprios providers/configuração. A interface
apresenta configuração necessária quando faltam. Não há npx/latest, download
de provider, cobrança ou atualização automática durante a análise.

O Companion foi instalado somente em `.runtime/skills`, com `--client generic
--integration off --skills-dir <HuntMob>/.runtime/skills`: ação explícita pelo
HuntMob, sem mudar a skill REA do Codex/Draxen. Plano --dry-run conferido antes;
--check retornou `verified`; update check retornou `disabled`. Backup/receipt em
`.runtime/.rea-reconstruction-companion-installer/`. A cópia de fonte clonada e
os binários locais ficam fora do Git. Não foi instalado um host/modelo de IA.

## Validação e limites

O adapter real produziu Evidence no APK de laboratório InsecureBank, SHA256
`b18af2a0e44d7634bbcdf93664d9c78a2695e050393fcfbb5e8b91f902d194a4`, em workspace
temporário isolado sem trocar o aparelho principal. Provider `jadx` 0.7.1,
Evidence `ev_33771b265ecc21b3a8702b5f1b129b565e686668d2cc3c64d80b38465dc9f711`.
O pacote Companion foi gerado e permaneceu `awaiting_agent`.

Artefatos: `artifacts/validation/rea-adapter-real-provider-v1-2026-10-16.json` e
`rea-companion-handoff-v1-2026-10-16.zip`. A UI renderizou os seletores/providers;
no app atual, os botões permanecem desabilitados até existir decompilação
registrada. Não foi executada análise REA do app de terceiro atual nesta etapa.

Cobertura: apenas base.apk. Splits, nativas, reflexão/carregamento dinâmico,
backend, equivalência funcional e vulnerabilidades exploráveis não foram
validados. Integração REA/Companion nesta versão é Android; análise IPA existente
continua separada. O provider Android deste REA usa subprocessos POSIX, portanto
não implica suporte local Windows; Windows pode consumir um worker compatível
quando o transporte remoto adequado estiver configurado e validado.

Fontes: https://github.com/morluto/rea,
https://github.com/1013503897/jadx-headless-mcp/releases/tag/v0.7.1,
https://github.com/ShadowSwaps/REA-Reconstruction-Companion.

Validação final: 122 testes Python e 14 testes Node aprovados. O cliente stdio
real negociou protocolo e consultou inventário e alvo atual; a avaliação de um
modelo externo ainda não foi executada.

Atualização local em 2026-10-16: Ollama `hermes3:8b` foi conectado por loopback
para revisão explícita de Evidence REA. A validação usou uma fixture isolada;
o app de terceiro selecionado não recebeu avaliação. Veja
[Companion local e validação de plataformas](companion-local-model-platform-validation-v1.0-2026-10-16.md).

Inspeções reais adicionais no mesmo APK de laboratório: inventário da classe
LoginActivity e decompilação do método onCreate (overload 0), com Evidence
própria e o mesmo digest. Artefatos rea-class-real-provider e
rea-method-real-provider-v1-2026-10-16.json. A decompilação de método permanece
classificada pelo REA como derived, sem prova de comportamento em execução.
