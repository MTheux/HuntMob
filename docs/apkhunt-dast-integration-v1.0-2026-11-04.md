# APKHunt no DAST do HuntMob · v1.0 · 2026-11-04

O APKHunt é um analisador **estático** de APK. Seu JSON pode fornecer pistas
para exercícios na sessão DAST, mas não prova execução, alcance ou impacto.
O HuntMob não instala nem executa o APKHunt, não incorpora seu código GPL-3.0 e
não consulta hosts extraídos do APK durante a importação.

## Fluxo do operador

1. Analise o APK autorizado no [APKHunt](https://github.com/Cyber-Buddy/APKHunt).
2. Localize o arquivo `*_report_<scan_id>.json` na pasta `reports` do APKHunt.
   No Compose oficial, a pasta fica no volume `apk_reports` em `/app/reports`.
3. No HuntMob, selecione o Android e o app vinculado ao APK. Na aba DAST,
   escolha o JSON em **APKHunt · Estático** e clique em **Importar relatório**.
4. Revise as pistas e exercite no app os caminhos relevantes. A correlação
   profunda continua exigindo sessão DAST observada e evidência REA do mesmo APK.

## Contrato de evidência

- O servidor confere `scan_metadata.package_name` e
  `scan_metadata.apk_sha256` contra o app e APK do lab selecionado.
- O JSON bruto é limitado a 8 MB. O snapshot guarda no máximo 200 pistas,
  com ID, título, severidade declarada, MASVS, CWE, arquivo relativo e linha.
- Snippets, descrições, segredos, SBOM e rotas do relatório original não são
  persistidos no HuntMob. O SHA256 do arquivo original identifica a fonte.
- Trocar o APK oculta a importação anterior. Reimportar outro relatório
  invalida uma correlação profunda anterior.
- Pista APKHunt isolada nunca pode ser classificada pela correlação como fato
  observado ou achado confirmado. A revisão humana permanece obrigatória.

## Limite de validação

O teste local cobriu importação HTTP, CSRF, aprovação explícita, identidade do
APK, redução de dados e classificação da correlação. A interface visual e a
execução de um scan APKHunt real ainda dependem de um lab Android disponível.
