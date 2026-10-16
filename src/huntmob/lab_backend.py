"""Lifecycle of the locally prepared, owned InsecureBank training backend."""
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

LOCK = threading.Lock()
LAB_APK = 'b18af2a0e44d7634bbcdf93664d9c78a2695e050393fcfbb5e8b91f902d194a4'


def supported_lab():
    from .lab_sessions import current
    lab = current()
    return lab.get('package_id') == 'com.android.insecurebankv2' and lab.get('apk_sha256') == LAB_APK


def listening():
    try:
        with socket.create_connection(('127.0.0.1', 8888), timeout=.3):
            return True
    except OSError:
        return False


def ensure_backend():
    """Start only the reviewed fixed backend, never an arbitrary command or target."""
    if not supported_lab():
        return {'ok': False, 'reason': 'Backend automático disponível apenas para este APK do laboratório InsecureBank.'}
    with LOCK:
        if listening():
            return {'ok': True, 'available': True, 'started': False, 'endpoint': '127.0.0.1:8888'}
        folder = Path.home() / '.huntmob/runtime/androlab'
        python = folder / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        if not python.is_file() or not (folder / 'app.py').is_file() or not (folder / 'upstream.json').is_file():
            return {'ok': False, 'reason': 'Backend AndroLab não preparado. Execute scripts/prepare_androlab.py neste host.'}
        log_folder = Path.home() / '.huntmob/logs'
        log_folder.mkdir(parents=True, exist_ok=True)
        log_path = log_folder / 'androlab.log'
        try:
            with os.fdopen(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as log:
                process = subprocess.Popen((str(python), str(folder / 'app.py')), cwd=folder, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return {'ok': False, 'reason': 'AndroLab encerrou durante a inicialização. Verifique o log local.'}
                if listening():
                    return {'ok': True, 'available': True, 'started': True, 'endpoint': '127.0.0.1:8888'}
                time.sleep(.1)
            process.terminate()
            return {'ok': False, 'reason': 'Backend não ficou disponível no prazo esperado.'}
        except OSError:
            return {'ok': False, 'reason': 'Não foi possível iniciar AndroLab neste host.'}
