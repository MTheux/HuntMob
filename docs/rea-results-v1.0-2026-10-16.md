# Saída REA no HuntMob — v1.0 (2026-10-16)

## O que a tela mostra

A resposta técnica do REA/JADX pertence à inspeção estática do APK selecionado. O resumo exibe pacote, versão, SDKs, classes, recursos, permissões e componentes com `exported=true` **explícito** no Manifest. Também aponta as declarações `debuggable` e `allowBackup` quando presentes. Esses são fatos extraídos do artefato, não findings confirmados.

O painel separa três estados: evidência REA observada, contexto Companion preparado e avaliação recebida de um agente/modelo. Conexão do modelo não equivale a avaliação executada. Quando uma avaliação existir, observações com Evidence ID, inferências e lacunas aparecem em grupos distintos com aviso de revisão humana e ausência de verificação independente.

O registro de evidências lista cada operação e seu estado. O JSON integral permanece em um segundo nível de detalhes para auditoria. Valores do APK e da resposta do modelo são inseridos como texto, sem interpretação como HTML.

## Limites

- `exported=true` explícito é uma contagem parcial. Defaults e intent filters variam por tipo de componente e versão Android.
- `debuggable=true`, `allowBackup=true`, permissões e componentes exportados requerem análise de contexto e teste autorizado antes de qualquer conclusão sobre impacto.
- Esta inspeção não executa o APK, não verifica o backend, não valida assinatura e não estabelece exploitabilidade.
- O Companion prepara o contexto; o modelo local só é acionado por comando explícito. A revisão gerada não vira finding automaticamente.

## Verificação local

- O endpoint de inspeções da execução selecionada retornou uma evidência `package` completa e nenhuma revisão/model job. A tela apresentou 2.992 classes, 555 recursos, 12 permissões e 6 componentes explicitamente exportados.
- Chromium local: resultado e navegação inspecionados em 1500 × 900 e 600 × 900; sem erro JavaScript ou overflow horizontal. O JSON bruto permaneceu fechado inicialmente.
- Entrada sintética com marcação HTML foi exibida como texto e não criou elemento HTML. A renderização de avaliação sintética separou observações, inferências e desconhecidos.
- `PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q`: 627 testes passaram.
- Alterações locais; sem commit, push ou publicação Git.
