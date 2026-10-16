"""Native Emulator fingerprint fixtures, after device_controls verifies ownership."""
import json
import re
from .android_worker import _run


def control(worker, payload):
    base = (str(worker.sdk.adb), '-s', worker.serial)
    features = _run(base + ('shell', 'pm', 'list', 'features'), timeout=5)
    dump = _run(base + ('shell', 'dumpsys', 'fingerprint'), timeout=5)
    supported = features.returncode == 0 and 'feature:android.hardware.fingerprint' in features.stdout
    # Inspect only the current scheduler client, never historical authentication logs.
    operations = re.findall(r'Current operation:\s*([^\n]+)', dump.stdout) if dump.returncode == 0 else []
    pending = next(('enrollment' if 'EnrollClient' in value else 'authentication' for value in operations if 'EnrollClient' in value or 'AuthenticationClient' in value), None)
    observed = bool(operations)
    counts = []
    for line in dump.stdout.splitlines():
        if line.startswith('{'):
            try: counts.extend(int(item['count']) for item in json.loads(line).get('prints', []) if isinstance(item.get('count'), int))
            except (ValueError, TypeError, KeyError): pass
    state = {'supported': supported, 'pending': pending, 'pending_observed': observed,
             'enrolled_count': sum(counts) if counts else None,
             'transport': 'android-emulator-console', 'scenarios': ['touch'],
             'device_id': worker.avd_name, 'serial': worker.serial}
    if payload.get('action') == 'biometric-status': return {'ok': True, 'biometrics': state}
    if not supported: return {'ok': False, 'reason': 'A imagem Android não anuncia sensor fingerprint.', 'biometrics': state}
    if not pending: return {'ok': False, 'reason': 'Abra o cadastro de digital nas Configurações ou um prompt biométrico no app. Nenhum evento enviado.', 'biometrics': state}
    identifier = payload.get('finger_id')
    if type(identifier) is not int or not 1 <= identifier <= 65535: raise ValueError('Identificador de digital inválido.')
    try:
        touched = _run(base + ('emu', 'finger', 'touch', str(identifier)), timeout=5)
    finally:
        removed = _run(base + ('emu', 'finger', 'remove'), timeout=5)
    sent = touched.returncode == 0 and removed.returncode == 0 and 'KO:' not in touched.stdout + removed.stdout
    return {'ok': sent, 'dispatched': sent, 'biometrics': state,
            'message': 'Toque enviado ao sensor virtual. Confira o resultado no Android.' if sent else '',
            'reason': '' if sent else 'O console do emulador recusou o evento.'}
