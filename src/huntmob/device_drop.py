"""Deliver an explicitly dropped host file to an owned, online Android AVD."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from .android_worker import AndroidWorker, PACKAGE_ID, _run
from .lab_sessions import current, save
from . import workspace_devices


def target(workspace_id: str, device_id: str) -> AndroidWorker:
    if current().get('id') != workspace_id:
        raise ValueError('O laboratório selecionado mudou.')
    if device_id == workspace_id:
        worker = AndroidWorker()
    else:
        record = workspace_devices.owned(workspace_id, device_id)
        if record.get('platform') != 'android':
            raise ValueError('Solte o arquivo sobre um Android.')
        worker = workspace_devices.worker(record)
    if worker.status().get('state') != 'device':
        raise ValueError('O Android escolhido está desligado.')
    return worker


def safe_name(encoded: str) -> str:
    name = unquote(encoded)
    if not name or len(name) > 180 or name in {'.', '..'} or '/' in name or '\\' in name or re.search(r'[\x00-\x1f\x7f]', name):
        raise ValueError('Nome de arquivo inválido.')
    return name


def deliver(worker: AndroidWorker, path: Path, name: str, *, primary: bool = False) -> dict:
    """Install an APK or push a regular file without replacing the selected AVD."""
    if not worker.sdk or worker.status().get('state') != 'device':
        return {'ok': False, 'reason': 'Android desconectado.'}
    if name.lower().endswith('.apk'):
        candidates = sorted((worker.sdk.root / 'build-tools').glob('*/aapt*'), reverse=True)
        aapt = next((item for item in candidates if item.name in {'aapt', 'aapt.exe'}), None)
        if not aapt:
            return {'ok': False, 'reason': 'Android build-tools (aapt) indisponível.'}
        metadata = _run((str(aapt), 'dump', 'badging', str(path)), timeout=30)
        match = re.search(r"package: name='([^']+)'", metadata.stdout)
        if metadata.returncode or not match or not PACKAGE_ID.fullmatch(match[1]):
            return {'ok': False, 'reason': 'APK inválido ou package ID ilegível.'}
        package_id = match[1]
        result = worker.install_and_launch(path, package_id)
        if result.get('installed') and primary:
            record = current()
            if record.get('id') == worker.avd_name:
                with path.open('rb') as source:
                    hasher = hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        hasher.update(chunk)
                    digest = hasher.hexdigest()
                save({**record, 'package_id': package_id, 'apk_sha256': digest})
        return {**result, 'ok': bool(result.get('installed')), 'kind': 'apk', 'filename': name, 'device_id': worker.avd_name}
    remote_name = re.sub(r'[^A-Za-z0-9._-]', '_', name)
    remote = '/sdcard/Download/HuntMob/' + uuid4().hex[:8] + '-' + remote_name
    mkdir = _run((str(worker.sdk.adb), '-s', worker.serial, 'shell', 'mkdir', '-p', '/sdcard/Download/HuntMob'), timeout=20)
    if mkdir.returncode:
        return {'ok': False, 'reason': 'Não foi possível preparar Downloads no Android.'}
    pushed = _run((str(worker.sdk.adb), '-s', worker.serial, 'push', str(path), remote), timeout=180)
    if pushed.returncode:
        return {'ok': False, 'reason': 'O envio para Downloads falhou.', 'error': pushed.stderr.strip()[:500]}
    if Path(name).suffix.lower() in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.mp4', '.txt', '.pdf'}:
        _run((str(worker.sdk.adb), '-s', worker.serial, 'shell', 'am', 'broadcast', '-a', 'android.intent.action.MEDIA_SCANNER_SCAN_FILE', '-d', 'file://' + remote), timeout=10)
    return {'ok': True, 'kind': 'file', 'filename': name, 'device_id': worker.avd_name, 'path': remote}
