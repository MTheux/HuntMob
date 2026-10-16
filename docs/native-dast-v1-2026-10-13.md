# HuntMob DAST nativo — v1 — 2026-10-13

O fluxo ativo não usa MobSF, Docker, URL de scanner, API key ou upload para um serviço externo. O Android atual, o worker Frida do HuntMob, o proxy e o evidence store produzem os dados da sessão.

## Fluxo

Iniciar sessão DAST, exercitar o aplicativo, capturar screenshot quando necessário, encerrar e analisar. Também é possível analisar um snapshot de uma sessão em andamento. O relatório é persistido no laboratório atual e pode ser baixado em JSON ou HTML, com SHA256 no header de exportação.

## Análise implementada

- Cobertura dos seis monitores: TLS, biometria, integridade, WebView, criptografia e arquivos. Distingue observado, pronto mas não exercitado, API ausente, monitor não selecionado e ausência de evidência.
- Candidatos de transporte HTTP, campos de senha/header de autenticação em HTTP, ECB, DES/3DES e digest MD5/SHA1.
- Observações de algoritmos, bridges JavaScript, indicadores de integridade consultados e falhas operacionais de rede.
- Referências às requisições e aos eventos, package, SHA256 do APK, ID da sessão e hash da fonte analisada.
- Nenhum candidato vira finding confirmado automaticamente. Um hook ausente ou não exercitado não demonstra ausência de controle de segurança.

A avaliação é limitada às evidências capturadas. Pinning, autenticação/autorização, impacto de negócio, fuzzing e exploração não são validados automaticamente. O modo sem root continua exigindo um build preparado com Gadget.

## Migração

A integração MobSF saiu da interface e das APIs do aplicativo. O serviço local foi parado; arquivos, volume e laboratório antigo foram preservados. O código anterior está arquivado em artifacts/legacy/mobsf, fora do pacote executável. Android API30 não é requisito do fluxo nativo.

Os componentes de Frida e o runtime Android continuam sendo dependências locais; nativo significa execução e análise governadas pelo próprio HuntMob, sem serviço de scanner externo.
