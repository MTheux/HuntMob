"""Bounded, offline IPA inspection; never extracts or executes uploaded content."""
from __future__ import annotations
import hashlib
import plistlib
import zipfile
from pathlib import Path, PurePosixPath


def inspect_ipa(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 50000:
            raise ValueError('Arquivo contém entradas demais.')
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError('ZIP contém entradas duplicadas.')
        for name in names:
            parts = PurePosixPath(name)
            if parts.is_absolute() or '..' in parts.parts or '\\' in name:
                raise ValueError('Caminho inválido no ZIP.')
        candidates = [entry for entry in entries if len(PurePosixPath(entry.filename).parts) == 3 and entry.filename.startswith('Payload/') and entry.filename.endswith('.app/Info.plist')]
        if len(candidates) != 1:
            raise ValueError('Selecione um IPA com exatamente um aplicativo principal.')
        entry = candidates[0]
        if entry.file_size > 2 * 1024 * 1024:
            raise ValueError('Info.plist excede o limite de análise.')
        try:
            info = plistlib.loads(archive.read(entry))
        except (plistlib.InvalidFileException, ValueError, OverflowError) as error:
            raise ValueError('Info.plist inválido.') from error
        if not isinstance(info, dict):
            raise ValueError('Info.plist deve ser um dicionário.')
        # Return only selected non-secret metadata, never arbitrary plist values.
        def label(value):
            return value[:512] if isinstance(value, str) else ''
        permissions = sorted(key for key in info if key.startswith('NS') and key.endswith('UsageDescription'))
        schemes = []
        url_types = info.get('CFBundleURLTypes', [])
        if isinstance(url_types, list):
            for item in url_types[:100]:
                if isinstance(item, dict) and isinstance(item.get('CFBundleURLSchemes'), list):
                    schemes.extend(label(value) for value in item['CFBundleURLSchemes'][:100] if isinstance(value, str))
        ats = info.get('NSAppTransportSecurity', {})
        ats = ats if isinstance(ats, dict) else {}
        exceptions = ats.get('NSExceptionDomains', {})
        with path.open('rb') as source:
            hasher = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                hasher.update(chunk)
            digest = hasher.hexdigest()
        return {'ok': True, 'analysis': 'static-only', 'sha256': digest, 'evidence_path': entry.filename,
                'bundle_id': label(info.get('CFBundleIdentifier')), 'version': label(info.get('CFBundleShortVersionString')), 'minimum_os': label(info.get('MinimumOSVersion')),
                'permission_keys': permissions, 'url_schemes': sorted(set(schemes)),
                'ats': {'allows_arbitrary_loads': ats.get('NSAllowsArbitraryLoads') is True, 'exception_domain_count': len(exceptions) if isinstance(exceptions, dict) else 0},
                'limitations': ['Não executa o app.', 'Não verifica Keychain, sandbox, assinatura ou comportamento de rede.', 'Configurações observadas precisam de validação; não são falhas confirmadas.']}
