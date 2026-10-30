"""Read-only detection of known Android app-protection / RASP frameworks.

Mirrors nutcracker's protector fingerprinting as a bounded, offline pass over
the APK's central directory: it reads entry names only — never extracts, never
runs the app, never touches the network — so it stays inside the HuntMob
observe-only lane.
"""
import zipfile

# (display name, vendor, category, substring tokens matched against lowercased entry paths)
_SIGNATURES = (
    ('DexGuard', 'Guardsquare', 'ofuscação + RASP', ('dexguard',)),
    ('DexProtector', 'Licel', 'ofuscação + RASP', ('dexprotector',)),
    ('Promon SHIELD', 'Promon', 'RASP', ('libpromon', 'libshield')),
    ('Appdome', 'Appdome', 'RASP', ('appdome',)),
    ('Arxan / Digital.ai', 'Digital.ai', 'RASP', ('arxan', 'libguardit')),
    ('RootBeer', 'scottyab', 'detecção de root', ('libtoolchecker',)),
    ('HST Security', 'HST', 'RASP / anti-tamper', ('libhstsecurity',)),
    ('Jiagu', 'Qihoo 360', 'packer', ('libjiagu',)),
    ('Bangcle / SecShell', 'Bangcle', 'packer', ('libsecexe', 'libsecshell', 'libsecmain')),
    ('Tencent Legu', 'Tencent', 'packer', ('libtxlegu', 'libshella', 'libshellx')),
    ('SecNeo', 'SecNeo', 'packer', ('libdexdefender', 'libnesec')),
)


def scan_protections(apk_path):
    """Scan an APK (path or file-like) for known protector fingerprints by name."""
    try:
        with zipfile.ZipFile(apk_path) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile, ValueError):
        return {'ok': False, 'protections': [], 'summary': 'APK ilegível para varredura de proteções.'}
    lowered = [(name, name.lower()) for name in names]
    protections = []
    for name, vendor, category, tokens in _SIGNATURES:
        evidence = sorted({original for original, low in lowered if any(token in low for token in tokens)})
        if evidence:
            protections.append({'name': name, 'vendor': vendor, 'category': category, 'evidence': evidence[:8]})
    summary = ('%d proteção(ões) conhecida(s) detectada(s).' % len(protections)) if protections \
        else 'Nenhuma proteção/RASP conhecida encontrada na varredura de nomes.'
    return {'ok': True, 'protections': protections, 'summary': summary}
