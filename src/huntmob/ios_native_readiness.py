"""Read-only research milestones; these never authorize a virtual iOS runtime."""
import json
import hashlib
import re
from datetime import datetime
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[2] / 'artifacts/validation'
STAGES = (
    ('kernel', 'Kernel e filesystem'),
    ('sep_restore', 'SEP na restauração'),
    ('protection', 'Proteção no boot normal'),
    ('interface', 'Interface iOS'),
    ('app', 'Instalação e abertura de IPA'),
)


def _read_report(path, expected_sha256=None):
    if path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError('Invalid research report')
    with path.open('rb') as source:
        data = source.read(65537)
    if len(data) > 65536 or (expected_sha256 is not None and
                            hashlib.sha256(data).hexdigest() != expected_sha256):
        raise ValueError('Research evidence differs')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('Invalid research metadata')
    return value


def _scoped_progress(report):
    """Only pinned, scoped receipts can advance milestones, never readiness."""
    names = ('ios-own-data-v2-native-cold-read-v1-2026-10-15.json',
             'ios-own-data-v2-normal-boot-v1-2026-10-15.json')
    evidence = report.get('evidence_sha256', {})
    if set(evidence) != set(names) or any(not re.fullmatch(r'[0-9a-f]{64}', evidence[name] or '') for name in names):
        raise ValueError('Exact scoped evidence required')
    cold, boot = (_read_report(REPORTS / name, evidence[name]) for name in names)
    binding = cold.get('engine_binding')
    if not isinstance(binding, dict) or not binding or not re.fullmatch(r'[0-9a-f]{64}', binding.get('binary_sha256', '') or ''):
        raise ValueError('Bound engine required')
    if not (cold.get('schema') == 'huntmob.ios-own-data-v2-native-cold-read.v1' and
            boot.get('schema') == 'huntmob.ios.own-data-v2.normal-boot.v1' and
            cold.get('vm_uuid') == boot.get('vm_uuid') == '9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4' and
            cold.get('engine_binding') == boot.get('engine_binding') and
            boot.get('binary_sha256') == binding['binary_sha256'] and
            cold.get('data_profile') == boot.get('data_profile') and
            cold.get('data_profile', {}).get('id') == 'huntmob.virtual-data.v2' and
            cold.get('data_profile', {}).get('hardware_equivalent') is False and
            cold.get('persistent_ClassC_probe_read_validated') is True and
            cold.get('same_existing_probe_class') == 3 and cold.get('existing_probe_bytes') == 64 and
            cold.get('AFU_before_after') == [1, 1] and
            cold.get('native_stock_keybag_init_exit') == 0 and cold.get('native_stock_keybag_init_signal') == 0 and
            all(cold.get(key) is True for key in ('metadata_valid', 'read_complete', 'digest_match')) and
            boot.get('stock_early_boot_marker_observed') is True and boot.get('panic_observed') is False and
            boot.get('own_checkpoint_unexpected') is False and boot.get('qmp_quit_accepted') is True and
            boot.get('exit_code') == 0 and
            all(boot.get(key) is False for key in ('ready', 'native_ready', 'springboard_validated', 'ipa_execution_validated')) and
            cold.get('native_ready') is False and cold.get('ready', False) is False and
            cold.get('full_boot_validated', False) is False and boot.get('full_boot_validated', False) is False and
            cold.get('historical_plaintext_finding') == 'open'):
        raise ValueError('Scoped research acceptance incomplete')



def snapshot():
    result = {'ready': False, 'state': 'unavailable', 'label': 'Não disponível',
              'summary': 'Nenhum runtime iOS virtual foi validado neste worker.',
              'last_validation': None, 'data_protection_required': True,
              'stages': [{'id': key, 'label': label, 'state': 'pending'} for key, label in STAGES]}
    try:
        reports = []
        for path in REPORTS.glob('ios-native-runtime-status-v*-*.json'):
            match = re.fullmatch(r'ios-native-runtime-status-v([12])-(\d{4}-\d{2}-\d{2})\.json', path.name)
            if match:
                reports.append((match[2], int(match[1]), path))
        reports.sort()
        if not reports:
            return result
        _, version, path = reports[-1]
        report = _read_report(path)
        if report.get('version') != version or report.get('data_protection_disabled') is not False:
            return result
        date = datetime.strptime(report['date'], '%Y-%m-%d').strftime('%d/%m/%Y')
        if version == 2:
            _scoped_progress(report)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return result
    # Research receipts cannot declare an executable provider ready, even if edited.
    result.update(state='blocked', label='Boot bloqueado', last_validation=date,
                  summary='A preparação da proteção de dados ainda impede o boot normal.')
    if report.get('current_blocker') == 'persisted-probe-plaintext-storage':
        result['summary'] = 'A proteção do armazenamento falhou na validação. O runtime permanece indisponível.'
    elif report.get('current_blocker') == 'sep-ans-context-derivation-unvalidated':
        result['summary'] = (
            'A derivação e a associação do contexto criptográfico SEP/ANS ainda '
            'não foram validadas. O runtime permanece indisponível.')
    if report.get('stock_verifier_invoked') is True:
        result['stages'][0]['state'] = 'observed'
    if report.get('sep_restore_os_alive_observed') is True:
        result['stages'][1]['state'] = 'observed'
    result['stages'][2]['state'] = 'blocked'
    if version == 2:
        result.update(label='Interface e proteção completa pendentes',
                      summary='O perfil próprio releu uma sonda Class C após reiniciar e avançou no boot inicial. '
                              'Interface iOS, IPA e proteção completa continuam sem validação.',
                      storage_scope='one-persistent-class-c-probe-own-profile',
                      data_protection_complete_validated=False)
        result['stages'][0]['state'] = result['stages'][1]['state'] = 'observed'
        result['stages'][2].update(label='Sonda Class C após reiniciar · perfil próprio', state='observed')
        result['stages'][3]['state'] = 'blocked'
    return result
