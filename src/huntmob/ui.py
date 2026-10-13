"""Loopback-first server for the HuntMob web workbench."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Type


LOOPBACKS = {"127.0.0.1", "::1", "localhost"}


def validate_bind(host: str, authorized_remote: bool) -> None:
    if host not in LOOPBACKS and not authorized_remote:
        raise ValueError("remote UI binding requires --authorized-remote")


def web_root() -> Path:
    root = Path(__file__).resolve().parents[2] / "web"
    if not (root / "index.html").is_file():
        raise FileNotFoundError("HuntMob web assets were not found")
    return root


def serve(
    host: str = "127.0.0.1",
    port: int = 8090,
    *,
    authorized_remote: bool = False,
    server_class: Type[ThreadingHTTPServer] = ThreadingHTTPServer,
) -> None:
    validate_bind(host, authorized_remote)
    handler = lambda *args, **kwargs: SimpleHTTPRequestHandler(  # noqa: E731
        *args, directory=str(web_root()), **kwargs
    )
    with server_class((host, port), handler) as server:
        print(f"HuntMob UI: http://{host}:{port}")
        server.serve_forever()
