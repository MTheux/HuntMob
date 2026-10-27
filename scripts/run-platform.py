#!/usr/bin/env python3
"""Run HuntMob with Docker ingress and the appropriate local device worker."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", "compose.control.yaml"]


def port_free(port: int) -> bool:
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def wait_worker(worker: subprocess.Popen, secret: str) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            raise RuntimeError("O worker nativo encerrou durante a inicialização. Confira ~/.huntmob/logs/platform-worker.log")
        request = Request("http://127.0.0.1:8092/api/client/ping",
                          headers={"X-HuntMob-Worker-Secret": secret})
        try:
            with urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("O worker nativo não respondeu na porta 8092")


def wait_gateway(worker: subprocess.Popen) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if worker.poll() is not None:
            raise RuntimeError("O worker nativo encerrou após iniciar o Docker")
        try:
            with urlopen("http://127.0.0.1:8090/api/client/ping", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("O gateway Docker não conseguiu alcançar o worker nativo")


def _confirm_sdk() -> bool:
    print("O Android SDK não está instalado neste worker.", flush=True)
    print("Posso baixar as ferramentas oficiais do Google e aceitar as licenças", flush=True)
    print("do Android SDK para preparar o emulador (download de alguns GB na 1ª vez).", flush=True)
    try:
        answer = input("Baixar e aceitar as licenças do Android SDK agora? [s/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"s", "sim", "y", "yes"}


def prepare_android_sdk() -> None:
    """Make the native Android worker ready on first run (one confirmation)."""
    sys.path.insert(0, str(ROOT / "src"))
    from huntmob.sdk_bootstrap import provision
    result = provision(_confirm_sdk)
    if not result.get("ok"):
        raise RuntimeError(
            (result.get("reason") or "Android SDK não preparado")
            + " Consulte o Início rápido no README."
        )


def run_desktop() -> int:
    if not port_free(8090) or not port_free(8092):
        raise RuntimeError("As portas 8090 e 8092 precisam estar livres")
    subprocess.run(["docker", "compose", "version"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    home = Path.home() / ".huntmob"
    home.mkdir(mode=0o700, exist_ok=True)
    logs = home / "logs"
    logs.mkdir(mode=0o700, exist_ok=True)
    prepare_android_sdk()
    with tempfile.TemporaryDirectory(prefix="docker-bridge-", dir=home) as temporary:
        secret = secrets.token_urlsafe(48)
        secret_path = Path(temporary) / "worker-secret"
        secret_path.write_text(secret, encoding="ascii")
        # The parent directory is private. Docker Desktop must read the mounted file.
        secret_path.chmod(0o644)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src") + (
            os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
        )
        environment["HUNTMOB_WORKER_SECRET_FILE"] = str(secret_path)
        command = [sys.executable, "-m", "huntmob.cli", "ui", "--bind", "127.0.0.1",
                   "--port", "8092", "--worker-secret-file", str(secret_path), "--public-port", "8090"]
        started = False
        worker = None
        try:
            with (logs / "platform-worker.log").open("a", encoding="utf-8") as output:
                worker = subprocess.Popen(command, cwd=ROOT, env=environment,
                                          stdin=subprocess.DEVNULL, stdout=output,
                                          stderr=subprocess.STDOUT)
            wait_worker(worker, secret)
            started = True
            subprocess.run(COMPOSE + ["up", "-d", "--build"], cwd=ROOT, env=environment, check=True)
            wait_gateway(worker)
            sys.path.insert(0, str(ROOT / 'src'))
            from huntmob.operator_auth import OperatorSession, write_access_url
            operator = OperatorSession(secret)
            access = write_access_url(operator, 'http://127.0.0.1:8090')
            print("HuntMob Docker: http://127.0.0.1:8090", flush=True)
            print(f"Endereço privado do operador: {access}", flush=True)
            print("Worker nativo conectado. Ctrl+C encerra os dois processos.", flush=True)
            while worker.poll() is None:
                time.sleep(0.5)
            raise RuntimeError("O worker nativo encerrou; o gateway será desligado")
        except KeyboardInterrupt:
            return 0
        finally:
            if started:
                subprocess.run(COMPOSE + ["down"], cwd=ROOT, env=environment, check=False)
            if worker is not None and worker.poll() is None:
                worker.terminate()
                try:
                    worker.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.wait(timeout=5)


def main() -> int:
    try:
        if platform.system() == "Linux":
            return subprocess.call(["sh", str(ROOT / "scripts" / "run-docker.sh")], cwd=ROOT)
        if platform.system() in {"Darwin", "Windows"}:
            return run_desktop()
        raise RuntimeError("Sistema operacional não suportado")
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"HuntMob não iniciado: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
