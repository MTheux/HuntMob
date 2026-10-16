"""Persisted per-app labs; switching never wipes an existing device."""
from __future__ import annotations
import json
import os
import re
import threading
import time
import subprocess
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

LAB_NAME = re.compile(r'^(?:huntmob_lab_[a-f0-9]{32}|huntmob_api35_arm64)$')
LAB_LOCK = threading.RLock()


def engagement_name(value=''):
    if not isinstance(value,str) or len(value)>120 or any(ord(char)<32 for char in value):
        raise ValueError('Identificador do engagement inválido.')
    return value.strip()


def root():
    return Path.home() / '.huntmob/labs'


def current():
    try:
        record = json.loads((root() / 'current.json').read_text())
        return record if LAB_NAME.fullmatch(record.get('id', '')) and record.get('state') != 'destroyed' else {}
    except (OSError, ValueError, TypeError):
        return {}


def save(record):
    folder = root()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in (record['id'] + '.json', 'current.json'):
        temp = folder / (name + '.' + uuid4().hex + '.tmp')
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
            json.dump(record, output)
        temp.replace(folder / name)


def inventory():
    records = []
    for path in root().glob('huntmob_*.json'):
        try:
            record = json.loads(path.read_text())
            if LAB_NAME.fullmatch(record.get('id', '')) and record.get('state') != 'destroyed':
                records.append(record)
        except (OSError, ValueError, TypeError):
            continue
    return {'labs': sorted(records, key=lambda item: item.get('created_at', ''), reverse=True), 'current': current()}


def switch(worker, record):
    from .android_worker import AndroidWorker
    from .screen_relay import SCREEN_RELAY
    from .dynamic_runtime import DYNAMIC
    state = worker.status()
    if state.get('state') in {'error','unauthorized'}:
        return {'ok':False,'reason':state.get('reason','O device atual não pode ser identificado com segurança.')}
    target = AndroidWorker(worker.sdk, avd_name=record['id'], root_mode=record.get('root_mode','root'), android_api=record.get('android_api',35))
    prerequisites=target.prerequisites()
    if not prerequisites.get('ready'):
        return {'ok':False,'reason':prerequisites.get('reason','Runtime do lab solicitado não está instalado; lab atual preservado.')}
    DYNAMIC.stop()
    SCREEN_RELAY.restart()
    from .codec_relay import CODEC_RELAY
    CODEC_RELAY.restart()
    if state.get('attached') or state.get('state') == 'device':
        stopped = worker.stop()
        if not stopped.get('ok'):
            return stopped
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            state = worker.status()
            if state.get('state') == 'offline' and not state.get('attached'):
                break
            time.sleep(1)
        else:
            return {'ok': False, 'reason': 'Current lab did not stop; preserved without switching'}
    if not current() and worker.avd_name == 'huntmob_api35_arm64':
        save({'id': worker.avd_name, 'package_id': '', 'legacy': True,
              'created_at': datetime.now(timezone.utc).isoformat()})
    save(record)
    started = target.start()
    if started.get('ok'):
        if record.get('root_mode', 'root') == 'root':
            enabled = target.enable_adb_root()
            if not enabled.get('ok'):
                return {**enabled, 'lab': record}
        verified = target.root_status()
        record = {**record, 'root_verification': verified}
        save(record)
        if not verified.get('verified'):
            return {'ok': False, 'reason': 'Android iniciou, mas o perfil de root não foi confirmado.', 'lab': record}
    return {**started, 'lab': record}


def create_lab(worker, package_id='', apk_sha256='', *, root_mode='root', profile_group=None, android_api=35, engagement=''):
    engagement=engagement_name(engagement)
    if type(android_api) is not int or android_api not in {30,31,32,33,34,35,36}:
        return {'ok':False,'reason':'Versão Android inválida. Escolha API 30 a 36.'}
    if root_mode not in {'root', 'stock'}:
        return {'ok': False, 'reason': 'Invalid root profile'}
    from .android_worker import AndroidWorker
    if not LAB_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'Another lab operation is in progress'}
    try:
        record = {'id': 'huntmob_lab_' + uuid4().hex, 'package_id': package_id,
                  'apk_sha256': apk_sha256, 'engagement':engagement, 'root_mode': root_mode, 'android_api': android_api, 'profile_group': profile_group or uuid4().hex, 'created_at': datetime.now(timezone.utc).isoformat()}
        target = AndroidWorker(worker.sdk, avd_name=record['id'], root_mode=root_mode, android_api=android_api)
        record['architecture']=target.architecture
        if not target.prerequisites().get('ready'):
            prepared = target.prepare_profile(root_mode)
            if not prepared.get('ok'):
                return {**prepared, 'stage': 'prepare', 'lab_created': False}
        result = target.create()
        if not result.get('ok'):
            return result
        configure_graphics(record['id'])
        return switch(worker, record)
    finally:
        LAB_LOCK.release()


def create_play_lab(worker, package_id='', *, android_api=35):
    """Prepare the official store image before switching; the user installs in Play."""
    from .android_worker import AndroidWorker, PACKAGE_ID
    if not isinstance(package_id, str) or (package_id and not PACKAGE_ID.fullmatch(package_id)):
        return {'ok': False, 'reason': 'Package ID do Google Play inválido.'}
    if type(android_api) is not int or android_api not in {30,31,32,33,34,35,36}:
        return {'ok': False, 'reason': 'Versão Android inválida.'}
    if not worker.sdk:
        return {'ok': False, 'reason': 'Android SDK indisponível neste worker.'}
    if not LAB_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'Outra operação de laboratório está em andamento.'}
    try:
        target = AndroidWorker(worker.sdk, root_mode='stock', android_api=android_api)
        prepared = target.prepare_profile('stock')
        if not prepared.get('ok'):
            return {**prepared, 'stage': 'prepare', 'lab_created': False}
        result = create_lab(worker, root_mode='stock', android_api=android_api)
        if not result.get('ok'):
            return {**result, 'stage': 'boot', 'lab_created': bool(result.get('lab'))}
        lab = result['lab']
        try:
            opened = AndroidWorker(worker.sdk, avd_name=lab['id'], root_mode='stock', android_api=android_api).open_play_store(package_id)
        except (OSError, subprocess.TimeoutExpired):
            opened = {'ok': False, 'reason': 'Play Store não respondeu. O Android foi preservado; retome o laboratório.'}
        return {**opened, 'lab': lab, 'lab_created': True, 'stage': 'store',
                'app_installed': False, 'requested_package': package_id}
    finally:
        LAB_LOCK.release()


def resume_lab(worker, identifier):
    if not isinstance(identifier, str) or not LAB_NAME.fullmatch(identifier):
        return {'ok': False, 'reason': 'Invalid lab identifier'}
    if not LAB_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'Another lab operation is in progress'}
    try:
        try:
            record = json.loads((root() / (identifier + '.json')).read_text())
        except (OSError, ValueError):
            return {'ok': False, 'reason': 'Saved lab not found'}
        if record.get('id') != identifier or record.get('state') == 'destroyed':
            return {'ok': False, 'reason': 'Invalid saved lab'}
        if current().get('id') == identifier:
            return {**worker.start(), 'lab': record}
        return switch(worker, record)
    finally:
        LAB_LOCK.release()


def configure_graphics(identifier):
    # New AVD userdata is independent; only validated graphics preferences are copied.
    avd_root = Path(os.environ.get('ANDROID_AVD_HOME', str(Path.home() / '.android/avd')))
    source = avd_root / 'huntmob_api35_arm64.avd/config.ini'
    target = avd_root / (identifier + '.avd/config.ini')
    if not target.exists():
        return
    values = {}
    if source.exists():
        for line in source.read_text().splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                if key in {'hw.gpu.enabled', 'hw.gpu.mode'}:
                    values[key] = value
    lines = target.read_text().splitlines()
    lines = [line for line in lines if line.split('=', 1)[0] not in values]
    target.write_text('\n'.join(lines + [key + '=' + value for key, value in values.items()]) + '\n')


def network_store():
    identifier = current().get('id')
    return root() / identifier / 'network.json' if identifier and identifier != 'huntmob_api35_arm64' else Path.home() / '.huntmob/run/network.json'


def change_root_profile(worker, mode, *, expected_lab_id=None):
    if not LAB_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'Another lab operation is in progress'}
    try:
        if expected_lab_id is not None and current().get('id') != expected_lab_id:
            return {'ok': False, 'reason': 'O laboratório selecionado mudou. Abra o controle Root novamente.'}
        return _change_root_profile(worker, mode)
    finally:
        LAB_LOCK.release()


def _change_root_profile(worker, mode):
    import hashlib
    from .android_worker import AndroidWorker, _run, PACKAGE_ID
    if mode not in {'root', 'stock'}:
        return {'ok': False, 'reason': 'Invalid root profile'}
    source = current()
    if not source:
        return {'ok': False, 'reason': 'Crie um laboratório primeiro.'}
    if source.get('root_mode', 'root') == mode:
        return {'ok': True, 'lab': source, 'root_verification': worker.root_status()}
    target = AndroidWorker(worker.sdk, root_mode=mode, android_api=source.get('android_api',35))
    if not target.prerequisites().get('ready'):
        return {'ok': False, 'reason': 'Imagem do perfil ausente. Prepare o runtime deste perfil antes da troca.', 'required_package': target.package}
    group = source.get('profile_group', source['id'])
    existing = next((item for item in inventory()['labs'] if item.get('profile_group', item['id']) == group and item.get('root_mode', 'root') == mode and item.get('android_api',35)==source.get('android_api',35)), None)
    if existing:
        worker.clear_proxy()
        resumed = resume_lab(worker, existing['id'])
        if resumed.get('ok') and existing.get('package_id'):
            launched = AndroidWorker(worker.sdk, avd_name=existing['id']).launch_app(existing['package_id'])
            return {**resumed, **launched}
        return resumed
    package = source.get('package_id', '')
    apks = []
    if package:
        if not PACKAGE_ID.fullmatch(package):
            return {'ok': False, 'reason': 'Invalid package'}
        listing = _run((str(worker.sdk.adb), '-s', worker.serial, 'shell', 'pm', 'path', package), timeout=10)
        locations = listing.stdout.splitlines()
        if listing.returncode or not 1 <= len(locations) <= 128 or len(set(locations)) != len(locations) or any(not re.fullmatch(r'package:/data/app/[^\s\x00]+\.apk', path) or '..' in path.split('/') for path in locations):
            return {'ok': False, 'reason': 'Não foi possível localizar o conjunto completo de APKs. Perfil atual preservado.'}
        bases = [path for path in locations if path.endswith('/base.apk')]
        if len(bases) != 1:
            return {'ok': False, 'reason': 'APK base não identificado. Perfil atual preservado.'}
        locations = bases + [path for path in locations if path not in bases]
        folder = root() / source['id'] / ('profile-apks-' + uuid4().hex)
        folder.mkdir(parents=True, mode=0o700)
        for index, remote in enumerate(locations):
            apk = folder / ('base.apk' if not index else f'split-{index}.apk')
            pulled = _run((str(worker.sdk.adb), '-s', worker.serial, 'pull', remote[8:], str(apk)), timeout=60)
            if pulled.returncode or not apk.is_file() or not apk.stat().st_size:
                return {'ok': False, 'reason': 'Não foi possível preservar todos os APKs. Perfil atual preservado.'}
            apk.chmod(0o600); apks.append(apk)
        if hashlib.sha256(apks[0].read_bytes()).hexdigest() != source.get('apk_sha256'):
            return {'ok': False, 'reason': 'Hash do APK divergente. Perfil atual preservado.'}
        manifest = [{'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size} for path in apks]
        (folder / 'manifest.json').write_text(json.dumps({'package_id': package, 'apks': manifest}))
        (folder / 'manifest.json').chmod(0o600)
    source = {**source, 'profile_group': group, 'root_mode': source.get('root_mode', 'root')}
    save(source)
    worker.clear_proxy()
    result = create_lab(worker, package, source.get('apk_sha256', ''), root_mode=mode, profile_group=group, engagement=source.get('engagement',''), android_api=source.get('android_api',35))
    if result.get('ok') and apks:
        installed = AndroidWorker(worker.sdk, avd_name=result['lab']['id']).install_apk_set(apks, package, legacy_sdk=True)
        if installed.get('installed'):
            return {**installed, 'lab': result['lab']}
        restored = resume_lab(AndroidWorker(worker.sdk, avd_name=result['lab']['id']), source['id'])
        return {**installed, 'source_restored': restored.get('ok') is True, 'reason': installed.get('reason', 'Instalação falhou.') + (' Perfil anterior retomado.' if restored.get('ok') else ' Retome o perfil anterior na lista de labs.')}
    if not result.get('ok') and current().get('id') != source['id']:
        restored = resume_lab(AndroidWorker(worker.sdk, avd_name=current()['id']), source['id'])
        return {**result, 'source_restored': restored.get('ok') is True}
    return result

