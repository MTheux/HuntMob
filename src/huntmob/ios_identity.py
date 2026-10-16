"""Describe observed lab identities without asserting Apple/backend acceptance."""
from uuid import UUID


def simulator_identity(record):
    value = record.get('udid') if isinstance(record, dict) else None
    try:
        if not isinstance(value, str) or str(UUID(value)).lower() != value.lower():
            raise ValueError('Invalid Simulator UUID')
    except (ValueError, AttributeError):
        value = None
    return {
        'kind': 'simulator-uuid',
        'value': value,
        'source': 'Apple simctl',
        'available': value is not None,
        'apple_physical_device_provisioning_supported': False,
        'backend_allowlist_acceptance': 'not-validated',
        'persistence': 'saved-simulator',
        'survives_worker_restart': value is not None,
        'new_lab_creates_new_identity': True,
        'app_identifier_matches_simulator_uuid': 'not-validated',
        'reason': 'UUID deste Simulator, salvo no Mac e preservado ao fechar ou retomar o HuntMob. Novo lab cria outro UUID. Não é UDID de iPhone físico nem necessariamente o identificador enviado pelo app ao backend.',
    }
