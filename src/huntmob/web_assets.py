"""Revisão determinística do conteúdo de web/.

Usada como build-arg (HUNTMOB_WEB_REV) do gateway Docker: quando o conteúdo de
web/ muda, a revisão muda, invalidando o layer COPY web — evita o buildx servir
markup em cache velho. Hash do conteúdo (caminhos relativos + bytes), estável
entre máquinas e independente de mtime. Stdlib apenas.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def web_revision(web_dir) -> str:
    web_dir = Path(web_dir)
    digest = hashlib.sha256()
    for path in sorted(p for p in web_dir.rglob('*') if p.is_file()):
        digest.update(str(path.relative_to(web_dir)).encode('utf-8'))
        digest.update(b'\0')
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]
