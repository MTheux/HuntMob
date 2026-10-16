"""Temporary Magisk root on the selected, owned AOSP AVD.

Uses the upstream Magisk v30.7 emulator setup script and APK, both pinned by
SHA256. The setup restarts Android processes but keeps the current AVD/data.
Individual apps still require an explicit MagiskSU grant.
"""

import hashlib
import io
from pathlib import Path
import urllib.request
import zipfile

from .android_worker import _run

VERSION = "v30.7"
COMMIT = "e8a58776f1d7bdf852072ad0baa6eceb9a1e4aac"
APK_URL = f"https://github.com/topjohnwu/Magisk/releases/download/{VERSION}/Magisk-{VERSION}.apk"
SCRIPT_URL = f"https://raw.githubusercontent.com/topjohnwu/Magisk/{COMMIT}/scripts/live_setup.sh"
APK_SHA256 = "e0d32d2123532860f97123d927b1bb86c4e08e6fd8a48bfc6b5bee0afae9ebd5"
SCRIPT_SHA256 = "b3dc430c96718cd4a08e30282c6c57f3da026bc4e75de09e0a426eaed64a1e49"


def _verified(cache: Path, name: str, url: str, digest: str, limit: int) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / name
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
        return path
    request = urllib.request.Request(url, headers={"User-Agent": "HuntMob/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
        raise OSError("Artefato Magisk excede o limite ou falhou na verificação SHA256.")
    path.write_bytes(data)
    return path


def status(base, adb_state):
    """Report readiness for per-app grants, not authorization for a given app."""
    version = _run(base + ("shell", "/debug_ramdisk/magisk", "-v"), timeout=5)
    daemon = _run(base + ("shell", "pidof", "magiskd"), timeout=5)
    active = version.returncode == 0 and "MAGISK:" in version.stdout and daemon.returncode == 0 and bool(daemon.stdout.strip())
    return {"enabled": active, "available": adb_state["available"],
            "version": version.stdout.strip()[:80] if active else None,
            "app_grants": "Gerenciados individualmente pelo Magisk" if active else None,
            "temporary": True}


def enable(base, adb_state, cache: Path):
    if not adb_state["available"]:
        raise ValueError("Esta imagem não permite preparar root para apps no mesmo AVD. Use AOSP userdebug.")
    if not adb_state["enabled"]:
        changed = _run(base + ("root",), timeout=15)
        if changed.returncode or "cannot run as root" in (changed.stdout + changed.stderr).lower():
            raise OSError("ADB root necessário para preparar Magisk neste AVD.")
        if _run(base + ("wait-for-device",), timeout=25).returncode:
            raise OSError("ADB não reconectou ao mesmo AVD.")
    apk = _verified(cache, "Magisk-v30.7.apk", APK_URL, APK_SHA256, 25_000_000)
    script = _verified(cache, "live_setup-v30.7.sh", SCRIPT_URL, SCRIPT_SHA256, 50_000)
    abi_result = _run(base + ("shell", "getprop", "ro.product.cpu.abi"), timeout=5)
    abi = abi_result.stdout.strip()
    if abi_result.returncode or abi not in {"arm64-v8a", "x86_64"}:
        raise ValueError("Arquitetura deste AVD não suportada para Magisk temporário.")
    with zipfile.ZipFile(io.BytesIO(apk.read_bytes())) as archive:
        busybox = archive.read(f"lib/{abi}/libbusybox.so")
    if len(busybox) > 10_000_000:
        raise OSError("BusyBox do Magisk excede o limite.")
    busybox_path = cache / f"busybox-{abi}"
    busybox_path.write_bytes(busybox)
    for source, target in ((busybox_path, "/data/local/tmp/busybox"),
                           (script, "/data/local/tmp/live_setup.sh"),
                           (apk, "/data/local/tmp/magisk.apk")):
        if _run(base + ("push", str(source), target), timeout=35).returncode:
            raise OSError("Falha ao copiar Magisk ao mesmo AVD.")
    result = _run(base + ("shell", "sh", "/data/local/tmp/live_setup.sh"), timeout=120)
    if result.returncode:
        raise OSError("O setup oficial do Magisk não concluiu neste AVD.")
    if _run(base + ("wait-for-device",), timeout=30).returncode:
        raise OSError("Android não reconectou após Magisk.")
    return status(base, adb_state)


def disable(base, adb_state):
    if not adb_state["enabled"]:
        raise ValueError("ADB root é necessário para desativar Magisk neste AVD.")
    result = _run(base + ("shell", "/debug_ramdisk/magisk", "--stop"), timeout=30)
    if result.returncode:
        raise OSError("O Magisk não confirmou a desativação.")
    return status(base, adb_state)
