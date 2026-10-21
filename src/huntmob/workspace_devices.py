"""Explicitly addressed companion Androids; never replace the selected lab."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import re
import shutil
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .android_worker import AndroidWorker, _run
from .lab_sessions import LAB_LOCK, LAB_NAME, current, configure_graphics
from .codec_relay import CodecRelay
from .device_contract import describe, inventory

MAX_DEVICES = 4
RELAYS = {}
RELAY_LOCK = threading.Lock()
PRESENTATION_LOCK = threading.RLock()


def root():
    return Path.home() / '.huntmob/workspace-devices'


def _name(value):
    if not isinstance(value, str) or not LAB_NAME.fullmatch(value):
        raise ValueError('Identidade de aparelho inválida.')
    return value


def _save(record):
    folder = root()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = folder / (_name(record['id']) + '.json')
    temp = folder / (target.name + '.' + uuid4().hex + '.tmp')
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
        json.dump(record, output)
    temp.replace(target)


def records():
    result = []
    for path in root().glob('huntmob_lab_*.json'):
        try:
            record = json.loads(path.read_text())
            _name(record['id']); _name(record['workspace_id'])
            if record.get('platform')=='ios':
                if not re.fullmatch(r'[A-Fa-f0-9]{8}(?:-[A-Fa-f0-9]{4}){3}-[A-Fa-f0-9]{12}',record.get('udid','')) or not record.get('name','').startswith('HuntMob iOS Workspace '):continue
            else:
                port = record['port']
                if type(port) is not int or not 5558 <= port <= 5680 or port % 2:continue
            if path.stem != record['id']:
                continue
            result.append(record)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return result


def owned(workspace_id, device_id):
    _name(workspace_id); _name(device_id)
    record = next((r for r in records() if r['id'] == device_id and r['workspace_id'] == workspace_id), None)
    if not record:
        raise ValueError('Aparelho não pertence a este workspace.')
    return record


def worker(record):
    if record.get('platform')=='ios':
        from .ios_workspace import device
        return device(record)
    return AndroidWorker(avd_name=record['id'], root_mode=record['root_mode'],
                         android_api=record['android_api'], port=record['port'])


def relay(record):
    if record.get('platform')=='ios':return worker(record).video
    with RELAY_LOCK:
        if record['id'] not in RELAYS:
            def check(identifier):
                try:
                    saved = owned(record['workspace_id'], identifier)
                    return saved['port'] == record['port']
                except ValueError:
                    return False
            # Separate ADB forward per encoder; no shared global video socket.
            RELAYS[record['id']] = CodecRelay(owner_check=check, forward_port=28000 + record['port'])
        return RELAYS[record['id']]


def snapshot(workspace_id):
    _name(workspace_id)
    items = []
    contracts = []
    errors = []
    for record in records():
        if record['workspace_id'] != workspace_id:
            continue
        try:
            target = worker(record)
            state = target.status()
            serial = record['udid'] if record.get('platform') == 'ios' else 'emulator-' + str(record['port'])
            online = state['state'] == 'device' and state.get('properties', {}).get('sys.boot_completed') == '1' and state.get('ownership_verified') is True
            item = {**record, 'serial': serial, 'state': state['state'], 'online': online,
                    'ownership_verified': state.get('ownership_verified', False)}
            item['session_generation'] = relay(record).snapshot().get('generation')
            items.append(item)
            contracts.append(describe(item, state, relay(record).snapshot()))
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.TimeoutExpired):
            serial = record.get('udid') if record.get('platform') == 'ios' else 'emulator-' + str(record.get('port', ''))
            item = {**record, 'serial': serial, 'state': 'error', 'online': False,
                    'ownership_verified': False, 'session_generation': None}
            items.append(item)
            contracts.append(describe(item, {'state': 'error', 'ownership_verified': False},
                                      {'state': 'error', 'error': 'device_discovery_failed'}))
            errors.append({'device_id': record['id'], 'platform': record.get('platform', 'android'),
                           'reason': 'device_discovery_failed'})
    primary = current()
    primary_contract = None
    if primary.get('id') == workspace_id:
        state = AndroidWorker().status()
        primary = {key: primary.get(key) for key in ('id', 'android_api', 'root_mode')}
        primary.update({'serial': state.get('serial'), 'state': state['state'], 'platform': 'android', 'workspace_id': workspace_id})
        from .codec_relay import CODEC_RELAY
        primary['session_generation'] = CODEC_RELAY.snapshot().get('generation')
        primary_contract = describe(primary, state, CODEC_RELAY.snapshot(), primary=True)
    else:
        primary = {'id': workspace_id, 'state': 'not_selected'}
    normalized = inventory(workspace_id, primary_contract, contracts, errors)
    return {'ok': True, 'workspace_id': workspace_id, 'primary': primary, 'devices': sorted(items, key=lambda r: r['created_at']),
            'presentation': presentation(workspace_id),
            'max_devices': MAX_DEVICES, 'contract': normalized}


def presentation(workspace_id):
    path = root().parent / 'workspace-layout' / (_name(workspace_id) + '.json')
    try:
        value = json.loads(path.read_text())
        if not isinstance(value, dict) or not isinstance(value.get('devices'), dict): raise ValueError('Layout inválido.')
        return value
    except FileNotFoundError:
        return {'version': 0, 'devices': {}}


def _members(workspace_id, identities):
    _name(workspace_id)
    if current().get('id') != workspace_id: raise ValueError('O laboratório selecionado mudou.')
    if not isinstance(identities, list) or not 1 <= len(identities) <= MAX_DEVICES:
        raise ValueError('Selecione de um a quatro aparelhos.')
    # Validate the complete batch before the first mutation or native command.
    if any(not isinstance(identifier, str) for identifier in identities) or len(set(identities)) != len(identities):
        raise ValueError('Lista de aparelhos inválida.')
    result = []
    for identifier in identities:
        _name(identifier)
        result.append(None if identifier == workspace_id else owned(workspace_id, identifier))
    return result


def update_presentation(workspace_id, items):
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items): raise ValueError('Layout inválido.')
    with PRESENTATION_LOCK:
        _members(workspace_id, [item.get('device_id') for item in items])
        clean = []
        for item in items:
            if set(item) - {'device_id', 'label', 'position'}: raise ValueError('Campo de layout inválido.')
            change = {}
            if 'label' in item:
                value = item['label']
                if not isinstance(value, str) or len(value) > 80 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise ValueError('Nome deve ter até 80 caracteres, sem quebras de linha.')
                change['label'] = value.strip()
            if 'position' in item:
                point = item['position']
                if not isinstance(point, dict) or set(point) != {'x', 'y'}: raise ValueError('Posição inválida.')
                if any(type(point[key]) not in (int, float) or not math.isfinite(point[key]) or not 0 <= point[key] <= 20000 for key in ('x', 'y')):
                    raise ValueError('Posição fora da área de trabalho.')
                change['position'] = {key: round(point[key], 2) for key in ('x', 'y')}
            if not change: raise ValueError('Nenhuma alteração de layout.')
            clean.append((item['device_id'], change))
        value = presentation(workspace_id)
        for identifier, change in clean:
            value['devices'][identifier] = {**value['devices'].get(identifier, {}), **change}
        value['version'] += 1
        folder = root().parent / 'workspace-layout'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder / (workspace_id + '.json'); temporary = folder / (workspace_id + '.' + uuid4().hex + '.tmp')
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output: json.dump(value, output)
        temporary.replace(path)
        return {'ok': True, 'presentation': value}


def stop_many(workspace_id, identities):
    if isinstance(identities, list) and workspace_id in identities:
        return {'ok': False, 'reason': 'Use Salvar e desligar ou Desligar sem salvar para o aparelho principal.'}
    if not LAB_LOCK.acquire(blocking=False): return {'ok': False, 'reason': 'Aguarde a operação de laboratório em andamento.'}
    try:
        members = _members(workspace_id, identities)
        results = []
        for identifier, record in zip(identities, members):
            try:
                target = worker(record) if record else AndroidWorker(avd_name=workspace_id)
                if record: relay(record).restart()
                else:
                    from .codec_relay import CODEC_RELAY
                    from .screen_relay import SCREEN_RELAY
                    from .dynamic_runtime import DYNAMIC
                    DYNAMIC.stop(); CODEC_RELAY.restart(); SCREEN_RELAY.restart()
                result = target.stop()
                if result.get('ok'):
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        state = target.status()
                        if state.get('state') == 'offline' and not state.get('attached'): break
                        time.sleep(.25)
                    else: result = {'ok': False, 'reason': 'Desligamento enviado; aguarde o aparelho ficar offline.'}
                results.append({'device_id': identifier, 'ok': result.get('ok') is True,
                                'reason': result.get('reason', '')})
            except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired):
                results.append({'device_id': identifier, 'ok': False, 'reason': 'Não foi possível confirmar o desligamento deste aparelho.'})
        return {'ok': True, 'all_stopped': all(result['ok'] for result in results), 'results': results}
    finally:
        LAB_LOCK.release()


def _available_port(sdk):
    used = {r['port'] for r in records() if r.get('platform')!='ios'}
    devices = _run((str(sdk.adb), 'devices'), timeout=5)
    if devices.returncode:
        raise ValueError('ADB indisponível para reservar um aparelho.')
    for line in devices.stdout.splitlines():
        serial = line.split('\t')[0]
        if serial.startswith('emulator-') and serial[9:].isdigit():
            used.add(int(serial[9:]))
    for port in range(5558, 5681, 2):
        if port in used:
            continue
        sockets = []
        try:
            for value in (port, port + 1, 28000 + port):
                connection = socket.socket()
                sockets.append(connection)
                connection.bind(('127.0.0.1', value))
            return port
        except OSError:
            continue
        finally:
            for connection in sockets:
                connection.close()
    raise ValueError('Sem portas disponíveis para outro Android.')


def _copy_display(source_id, target_id):
    folder = Path(os.environ.get('ANDROID_AVD_HOME', str(Path.home() / '.android/avd')))
    source = folder / (source_id + '.avd/config.ini')
    target = folder / (target_id + '.avd/config.ini')
    allowed = {'hw.lcd.width', 'hw.lcd.height', 'hw.lcd.density', 'hw.gpu.enabled', 'hw.gpu.mode', 'hw.ramSize', 'hw.cpu.ncore'}
    if not source.is_file() or not target.is_file():
        return
    copied = {}
    for line in source.read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key in allowed and len(value) <= 100 and not any(ord(c) < 32 for c in value):
            copied[key] = value
    lines = [line for line in target.read_text().splitlines() if line.partition('=')[0] not in copied]
    target.write_text('\n'.join(lines + [f'{key}={value}' for key, value in copied.items()]) + '\n')


def create(workspace_id, platform_name='android', runtime=None, model=None, root_mode=None):
    _name(workspace_id)
    if platform_name not in {'android','ios'}:return {'ok':False,'reason':'Plataforma inválida.'}
    if root_mode not in {None,'root','stock'}:return {'ok':False,'reason':'Perfil Android inválido.'}
    if not LAB_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'Aguarde a operação de laboratório em andamento.'}
    try:
        source = current()
        if source.get('id') != workspace_id:
            return {'ok': False, 'reason': 'Workspace mudou. Atualize antes de adicionar um aparelho.'}
        if sum(r['workspace_id'] == workspace_id and worker(r).status().get('state') != 'offline' for r in records()) >= MAX_DEVICES - 1:
            return {'ok': False, 'reason': f'Este workspace admite até {MAX_DEVICES} aparelhos ativos. Desligue um antes de abrir outro.'}
        if platform_name=='ios':
            from .ios_workspace import create_record
            if shutil.disk_usage(Path.home()).free<8_000_000_000:return {'ok':False,'reason':'Libere pelo menos 8 GB para criar outro iOS Simulator.'}
            record=create_record(workspace_id,runtime,model)
            _save(record)
            try:result=worker(record).start()
            except (OSError,ValueError,subprocess.TimeoutExpired):result={'ok':False,'reason':'iPhone criado, mas o boot não terminou. Use Retomar neste aparelho.'}
            return {**result,'device':record,'device_created':True}
        primary = AndroidWorker()
        if not primary.sdk or primary.status().get('ownership_verified') is not True:
            return {'ok': False, 'reason': 'Inicie o Android principal antes de adicionar outro.'}
        port = _available_port(primary.sdk)
        record = {'id': 'huntmob_lab_' + uuid4().hex, 'workspace_id': workspace_id, 'port': port, 'platform':'android',
                  'root_mode': root_mode or source.get('root_mode', 'root'), 'android_api': source.get('android_api', 35),
                  'architecture': primary.architecture, 'created_at': datetime.now(timezone.utc).isoformat(),
                  'data_mode': 'clean', 'configuration_source': workspace_id}
        target = worker(record)
        profile = target.prepare_profile(record['root_mode'])
        if not profile.get('ok'):return profile
        prepared = target.create()
        if not prepared.get('ok'):
            return prepared
        configure_graphics(record['id']); _copy_display(workspace_id, record['id'])
        _save(record)
        result = target.start()
        if result.get('ok'):
            verification=target.root_status()
            record={**record,'root_verification':verification};_save(record)
            if not verification.get('verified'):result={'ok':False,'reason':'Android iniciou, mas o perfil de root não foi confirmado. Retome o aparelho para verificar.'}
        return {**result, 'device': record, 'device_created': True,
                'reason': 'Android adicional iniciado com dados próprios.' if result.get('ok') else result.get('reason', 'Retome o aparelho para tentar iniciar novamente.')}
    finally:
        LAB_LOCK.release()


def action(payload):
    """Fixed device-management verbs only; identity is required on every action."""
    try:
        workspace_id, device_id = payload.get('workspace_id'), payload.get('device_id')
        if payload.get('action') == 'presentation': return update_presentation(workspace_id, payload.get('items'))
        if payload.get('action') == 'stop-many': return stop_many(workspace_id, payload.get('device_ids'))
        if payload.get('action') == 'create':
            return create(workspace_id,payload.get('platform','android'),payload.get('runtime'),payload.get('model'),payload.get('root_mode'))
        record = owned(workspace_id, device_id)
        target = worker(record)
        verb = payload.get('action')
        if verb == 'control':
            if current().get('id') != workspace_id: raise ValueError('Workspace selecionado mudou.')
            control = payload.get('control', {})
            if not isinstance(control, dict): raise ValueError('Controle inválido.')
            if record.get('platform') == 'ios':
                if control.get('action') in {'home', 'recents', 'lock'}: return target.input(control)
                from .ios_worker import _device_control, IOS_LOCK
                with IOS_LOCK: return _device_control(control, record=target.owned())
            from .device_controls import execute
            return execute(target, control, workspace_id=workspace_id)
        if verb == 'start':
            with LAB_LOCK:
                if target.status().get('state') == 'offline' and sum(r['workspace_id'] == workspace_id and worker(r).status().get('state') != 'offline' for r in records()) >= MAX_DEVICES - 1:
                    return {'ok': False, 'reason': 'Desligue outro aparelho antes de retomar este. Limite de quatro aparelhos ativos.'}
                return target.start()
        if verb == 'stop':
            relay(record).restart()
            return target.stop()
        if verb == 'input':
            input_payload = payload.get('input', {})
            requested = payload.get('session_generation')
            channel = relay(record)
            if requested is not None and requested != channel.snapshot().get('generation'):
                return {'ok': False, 'reason': 'Sessão de controle mudou. Atualize o aparelho antes de enviar entrada.', 'stale_session': True}
            if record.get('platform')=='ios':return target.input(input_payload)
            if not target.sdk or channel.target != (str(target.sdk.adb), target.serial, target.avd_name):
                return {'ok': False, 'reason': 'Conecte o vídeo deste aparelho antes de enviar entrada.'}
            return channel.input({**input_payload, 'session_generation': requested} if requested is not None else input_payload)
        if target.status().get('ownership_verified') is not True:
            return {'ok': False, 'reason': 'Identidade ADB não confirmada. Nenhuma entrada enviada.'}
        if verb == 'open-store':
            return target.open_play_store()
        return {'ok': False, 'reason': 'Ação de aparelho desconhecida.'}
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.TimeoutExpired):
        return {'ok': False, 'reason': 'Operação recusada. Confira identidade, estado e capacidade do aparelho.'}


def shutdown():
    with RELAY_LOCK:
        values = list(RELAYS.values())
    for value in values:
        value.shutdown()
    from .ios_workspace import shutdown as shutdown_ios
    shutdown_ios()
