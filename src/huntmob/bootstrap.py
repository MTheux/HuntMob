"""Cross-platform bootstrap for HuntMob Android workers."""

from __future__ import annotations

import platform
import subprocess
from typing import Dict

from .android_worker import AndroidSdk, AndroidWorker


def bootstrap_android(*, install: bool = False) -> Dict[str, object]:
    """Inspect or install runtime packages without accepting licenses implicitly."""
    host = platform.system().lower()
    from .host_runtime import android_host
    support=android_host()
    if not support['supported']:
        return {'ok':False,'blocked':True,'ready':False,'reason':support['reason'],'host':support}
    sdk = AndroidSdk.discover()
    if sdk is None:
        instructions = {
            "darwin": "brew install --cask android-commandlinetools",
            "windows": "Install Android SDK Command-line Tools, then set ANDROID_SDK_ROOT",
            "linux": "Install Android SDK Command-line Tools, then set ANDROID_SDK_ROOT; enable access to /dev/kvm",
        }
        return {"ok": False, "blocked": True, "mode": "native", "next": instructions.get(host, "install Android SDK command-line tools")}
    worker=AndroidWorker(sdk)
    before = worker.prerequisites()
    before['device_runtime_ready']=bool(before.get('ready'))
    before['ready']=before['device_runtime_ready'] and before.get('apk_metadata_ready',False)
    if before.get("ready") or not install:
        return {"ok": True, "mode": "native", **before}
    package = worker.package
    from .analysis_core import EmbeddedAnalysis
    java=EmbeddedAnalysis()
    environment=java.environment() if java.status().get('ready') else None
    try:
        result = subprocess.run(
            (str(sdk.sdkmanager), f"--sdk_root={sdk.root}", "emulator", "platform-tools", 'build-tools;35.0.0', package),
            capture_output=True, text=True, timeout=1800, check=False,env=environment,
        )
    except (OSError,subprocess.TimeoutExpired):
        return {**before,'ok':False,'blocked':True,'mode':'native','ready':False,'reason':'SDK Manager não concluiu a preparação. Confira conexão, licenças e Java do pacote ou do SDK.'}
    after = AndroidWorker(sdk).prerequisites()
    after['device_runtime_ready']=bool(after.get('ready'))
    after['ready']=after['device_runtime_ready'] and after.get('apk_metadata_ready',False)
    return {
        "ok": result.returncode == 0 and bool(after.get("ready")),
        "mode": "native",
        **after,
        "license_note": "licenses must be accepted interactively with the official Android SDK tools if requested",
        "error": result.stderr.strip() if result.returncode else "",
    }
