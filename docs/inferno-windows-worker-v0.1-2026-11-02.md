# Inferno Windows worker v0.1 — 2026-11-02

## Estado

Inferno upstream declara suporte a Windows, mas não mantém um guia oficial
completo. O HuntMob trata Windows como worker experimental de pesquisa, não
como um Apple Simulator equivalente ou runtime iOS pronto.

Estados aceitos:

1. `toolchain-required`: MSYS2/WSL2 não foi encontrado.
2. `build-required`: toolchain encontrado; motor ainda não foi compilado e
   vinculado a um receipt.
3. `compiled`: binário fixado passou por revision pin, SHA-256, `--version` e
   inventário da máquina `t8030`.
4. `boot-validated`: somente depois de evidência independente de boot normal.
5. `app-validated`: somente depois de SpringBoard e fixture IPA autorizada.

Nenhum estado anterior pode ser promovido automaticamente para o seguinte.

## Probe no Windows

Na raiz do HuntMob, usando Python com `src` no path:

```powershell
$env:PYTHONPATH = "src"
python scripts/probe_ios_inferno_windows.py
```

O probe é read-only: não instala MSYS2/WSL2, não baixa firmware, não inicia
QEMU e não acessa dispositivos.

## Build nativo MSYS2

Depois de clonar o repositório fixado e instalar os pacotes UCRT64 revisados,
execute no PowerShell do worker Windows:

```powershell
.\scripts\build_ios_inferno_windows.ps1
```

O script recusa fonte suja e diretório de saída existente. Ele cria um worktree
no commit fixado, compila `qemu-system-aarch64.exe`, executa `--version` e
`-machine help`, exige `t8030` e grava SHA-256 no receipt. O receipt permanece
`ready: false`: essa etapa comprova somente o motor, não o boot do guest.

## Topologia prevista

- Native MSYS2: caminho preferencial para um futuro build Windows reproduzível.
- WSL2: alternativa experimental; preparação APFS continua separada e sem
  promessa de interface gráfica ou performance.
- Firmware Apple: fornecido pelo operador, nunca versionado ou distribuído.
- Receipts: `%LOCALAPPDATA%\HuntMob\research\ios-engine\build-receipt.json`.
- Fonte: `%LOCALAPPDATA%\HuntMob\research\Inferno`, no commit fixado em
  `components/ios-engine/upstream.json`.

## Gates pendentes

- receita de dependências MSYS2 reproduzível e revisada;
- compilação real em Windows x64;
- inventário `t8030` do binário `.exe`;
- restauração/boot com firmware legalmente obtido pelo operador;
- SpringBoard, input, framebuffer, rede e execução de fixture IPA;
- integração de receipts dinâmicos ao REA sem promover candidatos a achados.

Windows continua `experimental` até esses gates serem reproduzidos em um
worker Windows real.
