"""Owned Android pairs: original -> AOSP companion, exact APKs, separate data."""
from __future__ import annotations

import hashlib
import ipaddress
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .android_worker import AndroidWorker, PACKAGE_ID, _run
from .lab_sessions import LAB_LOCK, current, configure_graphics
from . import workspace_devices as devices

LOCK = threading.RLock()
JOBS = set()
MAX_APK_BYTES = 2 * 1024**3


def now():
    return datetime.now(timezone.utc).isoformat()


def checked_source(workspace_id):
    lab = current()
    if lab.get('id') != workspace_id:
        raise ValueError('O laboratório selecionado mudou. Retome o par neste workspace.')
    target = AndroidWorker()
    state = target.status()
    if not target.sdk or state.get('ownership_verified') is not True or state.get('properties', {}).get('sys.boot_completed') != '1':
        raise ValueError('Inicie o Android principal deste workspace antes de sincronizar.')
    return lab, target


def update(record, **changes):
    with LOCK:
        fresh = devices.owned(record['workspace_id'], record['id'])
        link = {**fresh.get('link', {}), **changes, 'updated_at': now()}
        fresh = {**fresh, 'link': link}
        devices._save(fresh)
        return fresh


def require_online(target):
    state = target.status()
    if state.get('ownership_verified') is not True or state.get('properties', {}).get('sys.boot_completed') != '1':
        raise ValueError('Identidade e boot do aparelho não confirmados.')


def apk_paths(target, package):
    if not isinstance(package, str) or not PACKAGE_ID.fullmatch(package):
        raise ValueError('Package ID inválido.')
    result = _run((str(target.sdk.adb), '-s', target.serial, 'shell', 'pm', 'path', package), timeout=15)
    lines = result.stdout.splitlines()
    if result.returncode or not 1 <= len(lines) <= 128 or any(not re.fullmatch(r'package:/data/app/[A-Za-z0-9_./=+@~-]+\.apk', line) or '..' in line.split('/') for line in lines):
        raise ValueError('O app não tem um conjunto de APKs de usuário válido.')
    paths = [line[8:] for line in lines]
    if len(set(paths)) != len(paths) or sum(p.endswith('/base.apk') for p in paths) != 1:
        raise ValueError('Conjunto de APKs duplicado ou sem base única.')
    return sorted(paths, key=lambda p: (not p.endswith('/base.apk'), p))


def remote_digest(target, path):
    result = _run((str(target.sdk.adb), '-s', target.serial, 'shell', 'sha256sum', path), timeout=60)
    value = result.stdout.split()[0] if result.stdout.split() else ''
    if result.returncode or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Não foi possível verificar o SHA256 instalado.')
    return value


def copy_app(source, target, package, expected_hash=None):
    """Install the original signature and split set; never launch or copy private data."""
    require_online(source); require_online(target)
    paths = apk_paths(source, package)
    command = (str(source.sdk.adb), '-s', source.serial)
    manifests = []
    with tempfile.TemporaryDirectory(prefix='huntmob-pair-') as folder:
        total = 0
        files = []
        for index, remote in enumerate(paths):
            size = _run(command + ('shell', 'stat', '-c', '%s', remote), timeout=10)
            if size.returncode or not size.stdout.strip().isdigit():
                raise ValueError('Tamanho do APK não verificado.')
            count = int(size.stdout.strip()); total += count
            if count <= 0 or total > MAX_APK_BYTES or shutil.disk_usage(folder).free < count + 512 * 1024**2:
                raise ValueError('Conjunto de APKs excede o limite ou o espaço disponível.')
            local = Path(folder) / f'{index}.apk'
            result = _run(command + ('pull', remote, str(local)), timeout=180)
            if result.returncode or not local.is_file() or local.stat().st_size != count:
                raise ValueError('Cópia do APK incompleta.')
            local.chmod(0o600)
            hasher = hashlib.sha256()
            with local.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            if digest != remote_digest(source, remote):
                raise ValueError('O APK mudou durante a cópia. Sincronize novamente.')
            manifests.append({'name': Path(remote).name, 'sha256': digest, 'size': count})
            files.append(str(local))
        if expected_hash and manifests[0]['sha256'] != expected_hash:
            raise ValueError('O APK original diverge do SHA256 vinculado ao lab.')
        require_online(target)
        args = ('install-multiple', '-r', '-t') if len(files) > 1 else ('install', '-r', '-t')
        installed = _run((str(target.sdk.adb), '-s', target.serial) + args + tuple(files), timeout=180)
        if installed.returncode or 'Success' not in installed.stdout:
            # Only a fixed error code is retained; installer output can include private paths.
            match = re.search(r'INSTALL_[A-Z0-9_]+', installed.stdout + installed.stderr)
            raise ValueError('Instalação recusada' + (': ' + match[0] if match else ' pelo Android') + '.')
    copied_paths = apk_paths(target, package)
    actual = sorted(remote_digest(target, path) for path in copied_paths)
    if actual != sorted(item['sha256'] for item in manifests):
        raise ValueError('O conjunto instalado não corresponde aos APKs originais.')
    return {'package_id': package, 'state': 'verified', 'apk_sha256': manifests[0]['sha256'], 'files': manifests, 'verified_at': now()}


def network_check(record):
    """Bounded TCP nonce between the two owned AVDs, no public forwarding or app traffic."""
    _, source = checked_source(record['workspace_id'])
    target = devices.worker(devices.owned(record['workspace_id'], record['id']))
    require_online(target)
    endpoints = []
    for device in (source, target):
        result = _run((str(device.sdk.adb), '-s', device.serial, 'shell', 'ip', '-o', '-4', 'addr', 'show', 'wlan0'), timeout=5)
        match = re.search(r'\binet (\d+\.\d+\.\d+\.\d+)/', result.stdout)
        if result.returncode or not match or not ipaddress.ip_address(match[1]).is_private:
            return {'state': 'pending', 'reason': 'Conecte os dois Androids ao Wi-Fi virtual para verificar a rede.', 'checked_at': now()}
        endpoints.append(match[1])
    port = 40000 + record['port']
    forwarded = False
    host_port = 36000 + record['port']
    destination, destination_port = endpoints[1], port
    transport = 'shared-emulator-wifi'
    if endpoints[0] == endpoints[1]:
        # Older guest images can still use isolated routers even on a recent Emulator.
        # Bind a temporary loopback-only ADB forward; never restart the original AVD.
        result = _run((str(target.sdk.adb), '-s', target.serial, 'forward', '--no-rebind', f'tcp:{host_port}', f'tcp:{port}'), timeout=5)
        if result.returncode:
            return {'state': 'pending', 'reason': 'Porta da ponte local indisponível. Nenhuma conexão existente foi substituída.', 'checked_at': now()}
        forwarded = True
        destination, destination_port, transport = '10.0.2.2', host_port, 'temporary-adb-loopback'
    nonce = ('huntmob-' + uuid4().hex + '\n').encode()
    listener = client = None
    try:
        listener = subprocess.Popen((str(target.sdk.adb), '-s', target.serial, 'shell', 'timeout', '7', 'toybox', 'nc', '-l', '-p', str(port)), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(.25)
        client = subprocess.Popen((str(source.sdk.adb), '-s', source.serial, 'shell', 'timeout', '5', 'toybox', 'nc', '-w', '3', destination, str(destination_port)), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        client.stdin.write(nonce); client.stdin.flush()
        time.sleep(.3)
        client.communicate(timeout=6)
        output, _ = listener.communicate(timeout=8)
        verified = client.returncode == 0 and nonce.strip() in output.splitlines()
    except subprocess.TimeoutExpired:
        verified = False
    finally:
        if listener:
            if listener.poll() is None:
                listener.terminate()
            listener.communicate(timeout=3)
        if client:
            if client.poll() is None:
                client.terminate()
            client.communicate(timeout=3)
        if forwarded:
            _run((str(target.sdk.adb), '-s', target.serial, 'forward', '--remove', f'tcp:{host_port}'), timeout=5)
    return {'state': 'verified' if verified else 'pending', 'protocol': 'tcp', 'source_ip': endpoints[0], 'target_ip': endpoints[1], 'port': port,
            'checked_at': now(), 'reason': ('TCP verificado via ponte ADB temporária.' if forwarded else 'TCP direto entre os aparelhos verificado.') if verified else 'TCP não confirmado. Confira o Wi-Fi e a versão do Emulator.',
            'transport': transport, 'isolation': 'shared-emulator-wifi' if not forwarded else 'host-loopback'}


def service_bridge(workspace_id, device_id, service_port=9000, access_port=19000, enabled=True):
    """Explicit TCP service on companion, reachable at localhost:access_port on original."""
    if type(enabled) is not bool or any(type(port) is not int or not 1024 <= port <= 65535 for port in (service_port, access_port)):
        raise ValueError('Informe portas TCP de 1024 a 65535.')
    with LOCK:
        record = devices.owned(workspace_id, device_id)
        if record.get('link', {}).get('kind') != 'root-companion' or record['id'] in JOBS:
            raise ValueError('Aguarde a sincronização do companheiro.')
        _, source = checked_source(workspace_id)
        target = devices.worker(record); require_online(target)
        bridge = record['link'].get('service', {})
        if bridge.get('enabled'):
            if enabled:
                raise ValueError('Desative a conexão atual antes de alterar suas portas.')
            release_bridge(record, source, target)
            return {'ok': True, 'device': update(record, service={'enabled': False}), 'reason': 'Conexão TCP desativada.'}
        if not enabled:
            return {'ok': True, 'device': record}
        host_port = 35000 + record['port']
        base = (str(target.sdk.adb), '-s', target.serial)
        result = _run(base + ('forward', '--no-rebind', f'tcp:{host_port}', f'tcp:{service_port}'), timeout=5)
        if result.returncode:
            raise ValueError('Porta local ocupada. Nenhuma conexão existente foi alterada.')
        reverse = _run((str(source.sdk.adb), '-s', source.serial, 'reverse', '--no-rebind', f'tcp:{access_port}', f'tcp:{host_port}'), timeout=5)
        if reverse.returncode:
            _run(base + ('forward', '--remove', f'tcp:{host_port}'), timeout=5)
            raise ValueError('Porta de acesso no principal ocupada. A ponte não foi ativada.')
        service = {'enabled': True, 'service_port': service_port, 'access_port': access_port, 'host_port': host_port, 'created_at': now(), 'transport': 'adb-loopback'}
        return {'ok': True, 'device': update(record, service=service), 'reason': f'No principal, 127.0.0.1:{access_port} encaminha TCP ao companheiro:{service_port}. O app precisa oferecer esse serviço.'}


def release_bridge(record, source=None, target=None):
    bridge = record.get('link', {}).get('service', {})
    if not bridge.get('enabled'):
        return
    target = target or devices.worker(record)
    source = source or AndroidWorker(avd_name=record['workspace_id'])
    host_port = 35000 + record['port']
    # Remove only mappings whose device and both endpoints still match our receipt.
    forwards = _run((str(target.sdk.adb), 'forward', '--list'), timeout=5)
    expected = f'{target.serial} tcp:{host_port} tcp:{bridge["service_port"]}'
    if expected in forwards.stdout.splitlines():
        _run((str(target.sdk.adb), '-s', target.serial, 'forward', '--remove', f'tcp:{host_port}'), timeout=5)
    if source.status().get('ownership_verified') is True:
        base = (str(source.sdk.adb), '-s', source.serial)
        reverse = _run(base + ('reverse', '--list'), timeout=5)
        if any(line.split()[-2:] == [f'tcp:{bridge["access_port"]}', f'tcp:{host_port}'] for line in reverse.stdout.splitlines()):
            _run(base + ('reverse', '--remove', f'tcp:{bridge["access_port"]}'), timeout=5)
    update(record, service={'enabled': False})


def release_workspace(workspace_id):
    for record in devices.records():
        if record['workspace_id'] == workspace_id:
            release_bridge(record)


def run_job(record, app_scope, network_only=False):
    try:
        if network_only:
            saved = devices.owned(record['workspace_id'], record['id'])
            apps = saved.get('link', {}).get('apps', [])
            state = 'ready' if apps and all(a['state'] == 'verified' for a in apps) else 'partial' if apps else 'failed'
            update(record, network=network_check(record), state=state, message='Verificação de rede concluída. APKs preservados.')
            return
        source_lab, source = checked_source(record['workspace_id'])
        target = devices.worker(record)
        update(record, state='preparing', message='Preparando Android AOSP API 35…')
        for operation in (lambda: target.prepare_profile('root'), target.create):
            result = operation()
            if not result.get('ok'):
                raise ValueError(result.get('reason', 'O Android não pôde ser preparado.'))
        configure_graphics(record['id']); devices._copy_display(record['workspace_id'], record['id'])
        checked_source(record['workspace_id'])
        update(record, state='booting', message='Iniciando o companheiro com dados próprios…')
        result = target.start()
        if not result.get('ok'):
            raise ValueError(result.get('reason', 'Boot não concluído.'))
        result = target.enable_adb_root()
        if not result.get('ok'):
            raise ValueError(result.get('reason', 'ADB root não confirmado.'))
        verification = target.root_status()
        if not verification.get('root_available') or not verification.get('verified'):
            raise ValueError('Perfil AOSP com root não confirmado.')
        with LOCK:
            fresh = devices.owned(record['workspace_id'], record['id'])
            devices._save({**fresh, 'root_verification': verification})
        apps = [source_lab.get('package_id')] if app_scope == 'selected' else [a['package_id'] for a in source.installed_apps().get('apps', [])]
        apps = sorted(set(a for a in apps if a and PACKAGE_ID.fullmatch(a)))
        if not apps or len(apps) > 100:
            raise ValueError('Selecione um app ou até 100 apps de usuário para sincronizar.')
        results = []
        for index, package in enumerate(apps):
            fresh_lab, _ = checked_source(record['workspace_id'])
            if any(fresh_lab.get(k) != source_lab.get(k) for k in ('id', 'package_id', 'apk_sha256')):
                raise ValueError('O app original mudou. Sincronize novamente.')
            from .dynamic_runtime import runtime_for
            if runtime_for(record['workspace_id'], record['id']).snapshot().get('state') in {'running', 'starting'}:
                raise ValueError('Encerre o DAST deste companheiro antes de sincronizar apps.')
            update(record, state='syncing', message=f'Copiando APKs · {index + 1}/{len(apps)} · {package}', apps=results, app_scope=app_scope)
            try:
                item = copy_app(source, target, package, source_lab.get('apk_sha256') if package == source_lab.get('package_id') else None)
            except (ValueError, OSError, subprocess.TimeoutExpired) as error:
                item = {'package_id': package, 'state': 'failed', 'reason': str(error) if isinstance(error, ValueError) else 'Cópia não concluída. Tente sincronizar novamente.'}
            results.append(item)
        selected = next((item for item in results if item['package_id'] == source_lab.get('package_id') and item['state'] == 'verified'), None)
        with LOCK:
            fresh = devices.owned(record['workspace_id'], record['id'])
            # Invalidate a previous binding if the selected app could not be verified this time.
            devices._save({**fresh, 'package_id': selected['package_id'] if selected else None, 'apk_sha256': selected['apk_sha256'] if selected else None})
        update(record, state='checking-network', message='Verificando TCP entre os Androids…', apps=results)
        try:
            network = network_check(record)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            network = {'state': 'pending', 'reason': 'Rede não confirmada. Use Verificar rede para tentar novamente.', 'checked_at': now()}
        verified = sum(item['state'] == 'verified' for item in results)
        update(record, state='ready' if verified == len(results) else 'partial', apps=results, network=network,
               message=f'{verified}/{len(results)} app(s) com APKs verificados. Contas e dados internos separados.')
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as error:
        update(record, state='failed', message=str(error) if isinstance(error, ValueError) else 'Operação interrompida. Retome o par para continuar; os dados foram preservados.')
    finally:
        with LOCK:
            JOBS.discard(record['id'])


def start(workspace_id, app_scope='selected', device_id=None, network_only=False):
    if app_scope not in {'selected', 'all'}:
        raise ValueError('Escolha o app selecionado ou todos os apps de usuário.')
    with LAB_LOCK, LOCK:
        source, primary = checked_source(workspace_id)
        if device_id:
            record = devices.owned(workspace_id, device_id)
            if record.get('link', {}).get('kind') != 'root-companion':
                raise ValueError('Este aparelho não é um companheiro com root.')
        else:
            record = next((r for r in devices.records() if r['workspace_id'] == workspace_id and r.get('link', {}).get('kind') == 'root-companion'), None)
        if record and record['id'] in JOBS:
            return {'ok': True, 'device': record, 'queued': True, 'reason': 'Criação ou sincronização já em andamento.'}
        if not record:
            if sum(r['workspace_id'] == workspace_id and devices.worker(r).status().get('state') != 'offline' for r in devices.records()) >= devices.MAX_DEVICES - 1:
                raise ValueError('Desligue um aparelho antes de criar o par. Limite de quatro ativos.')
            if shutil.disk_usage(Path.home()).free < 8 * 1024**3:
                raise ValueError('Libere pelo menos 8 GB para criar o companheiro.')
            record = {'id': 'huntmob_lab_' + uuid4().hex, 'workspace_id': workspace_id, 'port': devices._available_port(primary.sdk),
                      'platform': 'android', 'root_mode': 'root', 'android_api': 35, 'architecture': primary.architecture,
                      'created_at': now(), 'data_mode': 'clean', 'configuration_source': workspace_id,
                      'link': {'kind': 'root-companion', 'source_id': workspace_id, 'source_api': source.get('android_api'), 'state': 'queued', 'apps': []}}
            devices._save(record)
        from .dynamic_runtime import runtime_for
        runtime = runtime_for(workspace_id, record['id'])
        if not runtime.operation_lock.acquire(blocking=False):
            raise ValueError('Aguarde a operação DAST deste companheiro.')
        try:
            if runtime.snapshot().get('state') in {'running', 'starting'}:
                raise ValueError('Encerre o DAST deste companheiro antes de alterar o par.')
            if devices.worker(record).status().get('state') == 'offline' and sum(r['workspace_id'] == workspace_id and r['id'] != record['id'] and (r['id'] in JOBS or devices.worker(r).status().get('state') != 'offline') for r in devices.records()) >= devices.MAX_DEVICES - 1:
                raise ValueError('Desligue outro aparelho antes de retomar este par.')
            JOBS.add(record['id'])
            update(record, state='queued', message='Verificação de rede na fila…' if network_only else 'Preparação do par na fila…')
            threading.Thread(target=run_job, args=(record, app_scope, network_only), daemon=True, name='huntmob-root-pair').start()
        finally:
            runtime.operation_lock.release()
        return {'ok': True, 'device': record, 'queued': True}
