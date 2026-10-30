"""Bounded, reversible controls for the selected, project-owned emulator."""
import math
import re
import secrets
from pathlib import Path
import subprocess
import threading

_ANDROID_ID = re.compile(r'^[0-9a-f]{16}$')

from .android_worker import _run
from .lab_sessions import current, LAB_LOCK

CONTROL_LOCK = threading.Lock()


def _root_state(base):
    """Read the active ADB shell privilege; a profile label is not evidence."""
    identity = _run(base + ('shell', 'id', '-u'), timeout=5)
    build = _run(base + ('shell', 'getprop', 'ro.build.type'), timeout=5)
    debug = _run(base + ('shell', 'getprop', 'ro.debuggable'), timeout=5)
    if any(result.returncode for result in (identity, build, debug)):
        raise OSError('ADB root state unavailable')
    uid = identity.stdout.strip()
    build_type = build.stdout.strip()
    debuggable = debug.stdout.strip()
    if uid not in {'0', '2000'}:
        raise OSError('Unexpected ADB shell identity')
    return {'enabled': uid == '0', 'available': build_type in {'userdebug', 'eng'} and debuggable == '1',
            'uid': uid, 'build_type': build_type, 'debuggable': debuggable}


def _number(payload, key, low, high):
    value = float(payload[key])
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Valor fora do intervalo permitido.')
    return value


def _android_id(payload):
    """A 64-bit Android ID is 16 hex chars; generate one when none is given,
    and never let caller text reach the shell as anything but hex."""
    raw = payload.get('android_id')
    if raw is None:
        return secrets.token_hex(8)
    if not isinstance(raw, str):
        raise ValueError('Android ID inválido.')
    value = raw.strip().lower()
    if not _ANDROID_ID.fullmatch(value):
        raise ValueError('Android ID deve ter 16 dígitos hexadecimais.')
    return value


def execute(worker, payload, *, workspace_id=None):
    """Never accept shell text; only fixed commands and bounded numeric fields."""
    if not CONTROL_LOCK.acquire(blocking=False):
        return {'ok': False, 'reason': 'Aguarde o controle em andamento.'}
    try:
        with LAB_LOCK:
            lab = current()
            if not worker.sdk or worker.status().get('state') != 'device':
                return {'ok': False, 'reason': 'Android desconectado.'}
            base = (str(worker.sdk.adb), '-s', worker.serial)
            name = _run(base + ('emu', 'avd', 'name'), timeout=5)
            if workspace_id:
                from .workspace_devices import owned
                record = owned(workspace_id, worker.avd_name)
                if lab.get('id') != workspace_id or record.get('platform') == 'ios': raise ValueError('Workspace divergente.')
            elif lab.get('id') != worker.avd_name:
                return {'ok': False, 'reason': 'Emulador não corresponde ao laboratório selecionado.'}
            if name.returncode or worker.avd_name not in name.stdout.splitlines():
                return {'ok': False, 'reason': 'Emulador não corresponde ao laboratório selecionado.'}
            if payload.get('expected_device_id', worker.avd_name) != worker.avd_name: raise ValueError('Aparelho selecionado mudou.')
            action = payload.get('action')
            if action in {'app-root-status', 'app-root-toggle'}:
                from . import app_root
                adb_state = _root_state(base)
                before = app_root.status(base, adb_state)
                if action == 'app-root-status':
                    return {'ok': True, 'action': action, 'lab_id': worker.avd_name, 'root': before}
                if type(payload.get('enabled')) is not bool:
                    raise ValueError('Estado de root inválido.')
                enabled = payload['enabled']
                if enabled == before['enabled']:
                    return {'ok': True, 'action': action, 'lab_id': worker.avd_name, 'root': before,
                            'message': 'Root para apps já está neste estado.'}
                if enabled and not before['available']:
                    return {'ok': False, 'reason': 'Esta imagem não permite root para apps no mesmo AVD.', 'root': before}
                if enabled:
                    after = app_root.enable(base, adb_state, Path.home() / '.huntmob' / 'tools' / 'magisk-v30.7')
                else:
                    after = app_root.disable(base, adb_state)
                observed = _run(base + ('emu', 'avd', 'name'), timeout=5)
                if observed.returncode or worker.avd_name not in observed.stdout.splitlines():
                    return {'ok': False, 'reason': 'Identidade do AVD não confirmada após Magisk.'}
                if after['enabled'] != enabled:
                    return {'ok': False, 'reason': 'Root para apps não atingiu o estado solicitado neste AVD.', 'root': after}
                return {'ok': True, 'action': action, 'lab_id': worker.avd_name, 'root': after,
                        'message': 'Magisk '+('ativo' if enabled else 'desativado')+' no mesmo AVD. Cada app requer autorização individual no Magisk.'}
            if action in {'root-status', 'root-toggle'}:
                before = _root_state(base)
                if action == 'root-status':
                    return {'ok': True, 'action': action, 'lab_id': worker.avd_name, 'root': before}
                if type(payload.get('enabled')) is not bool:
                    raise ValueError('Estado de root inválido.')
                enabled = payload['enabled']
                if enabled == before['enabled']:
                    return {'ok': True, 'action': action, 'lab_id': worker.avd_name, 'root': before,
                            'message': 'ADB root já está neste estado no mesmo Android.'}
                if enabled and not before['available']:
                    return {'ok': False, 'reason': 'Este Android usa uma imagem de produção sem ADB root. O mesmo AVD não pode ativar root nesta imagem.', 'root': before}
                changed = _run(base + (('root',) if enabled else ('unroot',)), timeout=15)
                if changed.returncode or 'cannot run as root' in (changed.stdout + changed.stderr).lower():
                    return {'ok': False, 'reason': 'O Android recusou a mudança de ADB root neste aparelho.', 'root': before}
                reconnected = _run(base + ('wait-for-device',), timeout=25)
                if reconnected.returncode:
                    return {'ok': False, 'reason': 'ADB não reconectou ao mesmo Android após alterar root.'}
                observed = _run(base + ('emu', 'avd', 'name'), timeout=5)
                if observed.returncode or worker.avd_name not in observed.stdout.splitlines():
                    return {'ok': False, 'reason': 'Identidade do AVD não confirmada após a mudança; verifique o aparelho.'}
                after = _root_state(base)
                if after['enabled'] != enabled:
                    return {'ok': False, 'reason': 'ADB root não atingiu o estado solicitado neste Android.', 'root': after}
                return {'ok': True, 'action': action, 'lab_id': worker.avd_name, 'root': after,
                        'message': 'ADB root '+('ativado' if enabled else 'desativado')+' no mesmo Android.'}
            if action in {'biometric-status', 'biometric-touch'}:
                from .biometrics import control
                return control(worker, payload)
            if action == 'location':
                lat = _number(payload, 'latitude', -90, 90)
                lon = _number(payload, 'longitude', -180, 180)
                commands = [('shell', 'cmd', 'location', 'set-location-enabled', 'true'), ('emu', 'geo', 'fix', str(lon), str(lat))]
                message = 'Posição enviada ao provedor GPS do Android. O app precisa de permissão e consumir localização.'
            elif action == 'network':
                profile = payload.get('profile')
                presets = {'wifi': ('enable', 'disable'), 'mobile': ('disable', 'enable'), 'offline': ('disable', 'disable')}
                if profile not in presets: raise ValueError('Perfil de rede inválido.')
                wifi, mobile = presets[profile]
                commands = [('shell', 'svc', 'wifi', wifi), ('shell', 'svc', 'data', mobile)]
                message = 'Estado dos rádios solicitado. Conectividade e acesso ao backend dependem da rota disponível.'
            elif action == 'battery':
                level = _number(payload, 'level', 0, 100)
                if not level.is_integer(): raise ValueError('Carga deve ser inteira.')
                commands = [('shell', 'dumpsys', 'battery', 'unplug'), ('shell', 'dumpsys', 'battery', 'set', 'level', str(int(level)))]
                message = 'Carga simulada aplicada. Restaurar retorna ao estado normal do emulador.'
            elif action == 'battery-reset':
                commands = [('shell', 'dumpsys', 'battery', 'reset')]
                message = 'Simulação de bateria removida.'
            elif action == 'network-shape':
                profile = payload.get('profile')
                presets = {'normal': ('full', 'none'), 'slow': ('edge', 'gprs'), 'lte': ('lte', 'none')}
                if profile not in presets: raise ValueError('Perfil de latência inválido.')
                speed, delay = presets[profile]
                commands = [('emu', 'network', 'speed', speed), ('emu', 'network', 'delay', delay)]
                message = 'Perfil de velocidade e latência enviado ao emulador. Afeta a rede celular/ethernet emulada, não o Wi-Fi.'
            elif action == 'sensor':
                values = [_number(payload, key, -20, 20) for key in ('x', 'y', 'z')]
                commands = [('emu', 'sensor', 'set', 'acceleration', ':'.join(str(value) for value in values))]
                message = 'Aceleração simulada enviada ao Android (m/s²).'
            elif action == 'camera':
                commands = [('shell', 'am', 'start', '-a', 'android.media.action.STILL_IMAGE_CAMERA')]
                message = 'Câmera do Android aberta. A imagem usa a câmera emulada configurada no AVD; não é a webcam do navegador.'
            elif action == 'rotation':
                rotation = {'portrait': '0', 'landscape': '1'}.get(payload.get('orientation'))
                if rotation is None: raise ValueError('Orientação inválida.')
                commands = [('shell', 'wm', 'user-rotation', 'lock', rotation)]
                message = 'Orientação aplicada; apps com orientação fixa podem ignorá-la.'
            elif action == 'rotation-reset':
                commands = [('shell', 'wm', 'user-rotation', 'free')]
                message = 'Rotação automática restaurada.'
            elif action == 'device-identity':
                android_id = _android_id(payload)
                commands = [('shell', 'settings', 'put', 'secure', 'android_id', android_id)]
                message = ('Android ID reescrito no provedor Secure. No Android 8+ (API 26+) o ANDROID_ID é '
                           'derivado por app/assinatura; o app pode ler um valor distinto do global. Confira no readback.')
            elif action == 'device-identity-read':
                commands = []
                message = 'Android ID atual lido do provedor Secure. Nada foi alterado.'
            elif action in {'home', 'back', 'recents', 'volume-up', 'volume-down', 'wake'}:
                keys = {'home':'3', 'back':'4', 'recents':'187', 'volume-up':'24', 'volume-down':'25', 'wake':'224'}
                commands = [('shell', 'input', 'keyevent', keys[action])]
                message = 'Evento enviado ao Android.'
            else:
                raise ValueError('Controle desconhecido.')
            for command in commands:
                result = _run(base + tuple(command), timeout=8)
                if result.returncode or 'KO:' in result.stdout or 'Error:' in result.stdout or 'Error:' in result.stderr:
                    return {'ok': False, 'reason': 'Android recusou o controle; verifique capacidade da imagem. Parte da operação pode ter sido aplicada.'}
            readings = {}
            for key, command in {'battery':('shell','dumpsys','battery'), 'wifi':('shell','settings','get','global','wifi_on'), 'mobile':('shell','settings','get','global','mobile_data'), 'location_enabled':('shell','cmd','location','is-location-enabled'), 'rotation':('shell','wm','user-rotation'), 'acceleration':('emu','sensor','get','acceleration'), 'network_shape':('emu','network','status'), 'android_id':('shell','settings','get','secure','android_id')}.items():
                reading = _run(base + command, timeout=5)
                readings[key] = reading.stdout.strip()[:1000] if reading.returncode == 0 else 'Indisponível'
            return {'ok': True, 'action': action, 'lab_id': lab['id'], 'message': message, 'readback': readings}
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired):
        return {'ok': False, 'reason': 'Controle não concluído. Confira valores, device e capacidade da imagem.'}
    finally:
        CONTROL_LOCK.release()
