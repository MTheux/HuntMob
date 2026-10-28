"""Preflight das ferramentas externas que o HuntMob invoca.

Valida presença (no PATH) e versão de adb/emulator/sdkmanager/aapt/mitmdump/
jadx/apktool/frida, sem lançar quando algo falta. Stdlib apenas.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ToolStatus:
    name: str
    found: bool
    path: Optional[str]
    version: Optional[str]
    ok: bool
    min_version: Optional[str]
    required: bool


# (nome, args de versão, requerido). Requeridos: o essencial para subir o lab
# Android. Os demais são opcionais (estático/dinâmico adicional).
_TOOLS = (
    ('adb', ['--version'], True),
    ('emulator', ['-version'], True),
    ('sdkmanager', ['--version'], True),
    ('aapt', ['version'], False),
    ('mitmdump', ['--version'], False),
    ('jadx', ['--version'], False),
    ('apktool', ['--version'], False),
    ('frida', ['--version'], False),
)

_VERSION_RE = re.compile(r'(\d+\.\d+(?:\.\d+)?)')


def check_tools(which=shutil.which, run=subprocess.run):
    """Status de cada ferramenta. Nunca lança — falhas viram found/version vazios."""
    statuses = []
    for name, args, required in _TOOLS:
        path = which(name)
        if not path:
            statuses.append(ToolStatus(name, False, None, None, False, None, required))
            continue
        version = None
        try:
            proc = run([path, *args], capture_output=True, text=True, timeout=10)
            text = (getattr(proc, 'stdout', '') or '') + (getattr(proc, 'stderr', '') or '')
            match = _VERSION_RE.search(text)
            version = match.group(1) if match else None
        except Exception:
            version = None
        statuses.append(ToolStatus(name, True, path, version, True, None, required))
    return statuses


def exit_code(statuses) -> int:
    """0 quando toda ferramenta requerida está presente; 1 caso contrário."""
    return 0 if all(s.found for s in statuses if s.required) else 1


def format_table(statuses) -> str:
    lines = [f"{'ferramenta':<12} {'estado':<8} {'versão':<10} caminho"]
    for s in statuses:
        state = 'ok' if s.found else ('FALTA' if s.required else 'ausente')
        lines.append(f"{s.name:<12} {state:<8} {(s.version or '-'):<10} {s.path or ''}")
    return '\n'.join(lines)
