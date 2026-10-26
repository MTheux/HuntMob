"""First-run provisioning of the Android SDK for native HuntMob workers.

Downloads the official command-line tools when none are found, then installs
the emulator, platform tools, build tools and the system image for this host.

Licenses are never accepted silently. ``provision`` takes a ``confirm``
callback; only when it returns True once are Google's SDK licenses accepted
for this install (a single human confirmation, fed to every license prompt).
"""
from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from .android_worker import AndroidSdk
from .bootstrap import bootstrap_android

# Official Android command-line tools, pinned per OS as (url, sha256). The
# published build number differs between macOS and win/linux for this release;
# each only bootstraps sdkmanager, which then fetches the shared packages.
CMDLINE_TOOLS: Dict[str, Tuple[str, str]] = {
    "darwin": (
        "https://dl.google.com/android/repository/commandlinetools-mac-13114758_latest.zip",
        "5673201e6f3869f418eeed3b5cb6c4be7401502bd0aae1b12a29d164d647a54e",
    ),
    "windows": (
        "https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip",
        "90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a",
    ),
    "linux": (
        "https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip",
        "4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583",
    ),
}


def cmdline_tools_source(host: str) -> Tuple[str, str]:
    try:
        return CMDLINE_TOOLS[host]
    except KeyError:
        raise ValueError("Sem command-line tools oficiais do Android para este sistema: " + host)


def default_sdk_root(host: str, env: Optional[dict] = None) -> Path:
    env = os.environ if env is None else env
    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        if env.get(variable):
            return Path(env[variable]).expanduser()
    if host == "windows":
        base = env.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(base) / "Android/Sdk"
    return Path.home() / "Android/Sdk"


def verify_sha256(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError("sha256 não confere para " + path.name + ": " + actual)


def download(url: str, sha256: str, dest: Path) -> Path:
    """Fetch a pinned HTTPS artifact and verify it before using it."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)
    verify_sha256(dest, sha256)
    return dest


def extract_cmdline_tools(zip_path: Path, sdk_root: Path) -> Path:
    """Place the tools at ``<sdk_root>/cmdline-tools/latest`` (the layout
    sdkmanager expects). The official zip extracts a top-level
    ``cmdline-tools/`` directory, and zip entries carry no executable bit."""
    target = sdk_root / "cmdline-tools" / "latest"
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as staging:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(staging)
        extracted = Path(staging) / "cmdline-tools"
        source = extracted if extracted.is_dir() else Path(staging)
        shutil.move(str(source), str(target))
    if os.name != "nt":
        bin_dir = target / "bin"
        if bin_dir.is_dir():
            for entry in bin_dir.iterdir():
                if entry.is_file():
                    entry.chmod(entry.stat().st_mode | 0o755)
    return target


def sdk_tool(sdk_root: Path, name: str, host: str) -> Path:
    suffix = ".bat" if host == "windows" else ""
    return sdk_root / "cmdline-tools" / "latest" / "bin" / (name + suffix)


def tool_command(tool: Path, host: str, args) -> list:
    # A Windows .bat/.cmd cannot be executed directly by CreateProcess; it must
    # run through cmd.exe. Native .exe/POSIX tools run directly.
    if host == "windows" and Path(tool).suffix.lower() in {".bat", ".cmd"}:
        return ["cmd", "/c", str(tool), *args]
    return [str(tool), *args]


def accept_licenses(sdkmanager: Path, sdk_root: Path, host: str, env: Optional[dict] = None) -> bool:
    """Accept the Android SDK licenses after a single human confirmation,
    feeding the agreement to each prompt sdkmanager emits."""
    command = tool_command(sdkmanager, host, ["--sdk_root=" + str(sdk_root), "--licenses"])
    try:
        result = subprocess.run(command, input="y\n" * 60, text=True,
                                capture_output=True, timeout=600, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _prerequisites_ready(sdk) -> bool:
    from .android_worker import AndroidWorker
    try:
        return bool(AndroidWorker(sdk).prerequisites().get("ready"))
    except Exception:
        return False


def provision(confirm: Callable[[], bool], *, env: Optional[dict] = None,
              downloader: Callable[[str, str, Path], Path] = download,
              host: Optional[str] = None) -> Dict[str, object]:
    """Make the native Android worker ready with at most one confirmation.

    No-op when the SDK and system image are already present. Otherwise the
    caller's ``confirm`` must return True before anything is downloaded or any
    license is accepted."""
    env = os.environ if env is None else env
    host = host or platform.system().lower()
    sdk = AndroidSdk.discover()
    if sdk is not None and _prerequisites_ready(sdk):
        return {"ok": True, "already_ready": True}
    url, sha = cmdline_tools_source(host)  # raises for an unsupported host before prompting
    if not confirm():
        return {"ok": False, "blocked": True, "reason": "Instalação/licença do Android SDK não autorizada."}
    if sdk is None:
        root = default_sdk_root(host, env)
        with tempfile.TemporaryDirectory() as tmp:
            archive = downloader(url, sha, Path(tmp) / "cmdline-tools.zip")
            extract_cmdline_tools(archive, root)
        env["ANDROID_SDK_ROOT"] = str(root)
        sdk = AndroidSdk.discover()
        sdkmanager = sdk_tool(root, "sdkmanager", host)
    else:
        root = sdk.root
        env.setdefault("ANDROID_SDK_ROOT", str(root))
        sdkmanager = sdk.sdkmanager
    if not accept_licenses(sdkmanager, root, host, env=env):
        return {"ok": False, "blocked": True, "reason": "As licenças do Android SDK não foram aceitas."}
    return bootstrap_android(install=True)
