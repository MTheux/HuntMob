"""Owned Android worker backed by the official Android Emulator and ADB."""

from __future__ import annotations

import os
import platform
import hashlib
import re
import shutil
import subprocess
import time
import tempfile
import zipfile
import socket
import threading
from dataclasses import dataclass
from uuid import uuid4
from .analysis_core import EmbeddedAnalysis
from pathlib import Path
from typing import Dict, List, Sequence


START_LOCK = threading.Lock()

PACKAGE_ID = __import__("re").compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
# Caminho de sandbox aceito ao abrir um arquivo: relativo (`./...` ou `nome/...`),
# só alfanumérico/_/./-. Barra inicial, espaços e metacaracteres de shell ficam de
# fora; `..` é recusado à parte. run-as já confina a leitura ao uid do app.
_SAFE_SANDBOX_PATH = __import__("re").compile(r"^(?:\./)?[A-Za-z0-9_][A-Za-z0-9_./-]*$")
_MAX_FILE_BYTES = 256 * 1024  # teto de leitura; o excedente vem marcado truncated


def _decode_file(package_id: str, source: str, path: str, raw: bytes) -> Dict[str, object]:
    """Monta o payload de um arquivo lido: texto quando decodifica em UTF-8 sem
    NUL, senão marca binary e devolve um preview hex dos primeiros bytes."""
    truncated = len(raw) > _MAX_FILE_BYTES
    raw = raw[:_MAX_FILE_BYTES]
    binary = b"\x00" in raw
    text = ""
    if not binary:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            binary = True
    return {
        "ok": True, "package_id": package_id, "source": source, "path": path,
        "size": len(raw), "truncated": truncated, "binary": binary,
        "content": text, "preview": raw[:1024].hex() if binary else "",
    }


SDK_CANDIDATES = (
    Path("/opt/homebrew/share/android-commandlinetools"),
    Path.home() / "Library/Android/sdk",
    Path.home() / "Android/Sdk",
    Path(os.environ.get("LOCALAPPDATA", "C:/__missing__")) / "Android/Sdk",
)


def _batch_wrap(command):
    """On Windows a .bat/.cmd (avdmanager, sdkmanager) cannot be launched by
    CreateProcess directly; route it through cmd.exe. .exe tools run as-is."""
    if platform.system() == "Windows" and command and str(command[0]).lower().endswith((".bat", ".cmd")):
        return ["cmd", "/c", *command]
    return command


# Consecutive offline/error polls (~2s each) a post-reboot device may show
# before we treat the adb transport as wedged and bounce the server once.
_ADB_RECOVER_POLLS = 10


def _old_target_sdk(badging: str) -> bool:
    """True when the APK targets an SDK old enough (<24) that Android 14+ blocks
    the install without --bypass-low-target-sdk-block. Read from aapt badging."""
    match = re.search(r"targetSdkVersion:'(\d+)'", badging)
    return bool(match) and int(match.group(1)) < 24


def _run(command: Sequence[str], timeout: int = 30, input_text: str | None = None, env=None):
    return subprocess.run(
        _batch_wrap(command), input=input_text, capture_output=True, text=True,
        timeout=timeout, check=False, env=env,
    )


# `adb devices` é consultado a cada tick de polling pelo status() do worker. Um
# cache curto (TTL) evita refazer a listagem várias vezes dentro da mesma
# janela. O cache é por worker (atributo de instância) — sem estado global,
# para não vazar entre chamadas/testes. now/run/cache são injetáveis; run cai no
# _run do módulo em call-time (respeita patch).
_DEVICES_TTL = 0.4


def _adb_devices(adb_path, *, now=time.monotonic, run=None, cache):
    runner = run or _run
    key = str(adb_path)
    entry = cache.get(key)
    moment = now()
    if entry and entry[0] > moment:
        return entry[1]
    result = runner((adb_path, "devices"), timeout=5)
    cache[key] = (moment + _DEVICES_TTL, result)
    return result


@dataclass(frozen=True)
class AndroidSdk:
    root: Path
    emulator: Path
    adb: Path
    avdmanager: Path
    sdkmanager: Path

    @classmethod
    def discover(cls) -> "AndroidSdk | None":
        roots = []
        for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
            if os.environ.get(variable):
                roots.append(Path(os.environ[variable]).expanduser())
        roots.extend(SDK_CANDIDATES)
        for root in roots:
            emulator = root / ("emulator/emulator.exe" if platform.system() == "Windows" else "emulator/emulator")
            adb = root / ("platform-tools/adb.exe" if platform.system() == "Windows" else "platform-tools/adb")
            bin_dir = root / "cmdline-tools/latest/bin"
            suffix = ".bat" if platform.system() == "Windows" else ""
            avdmanager = bin_dir / f"avdmanager{suffix}"
            sdkmanager = bin_dir / f"sdkmanager{suffix}"
            if adb.exists() and avdmanager.exists() and sdkmanager.exists():
                return cls(root, emulator, adb, avdmanager, sdkmanager)
        return None


class AndroidWorker:
    avd_name = "huntmob_api35_arm64"
    package = "system-images;android-35;default;arm64-v8a"
    serial = "emulator-5556"
    port = "5556"

    def __init__(self, sdk: AndroidSdk | None = None, *, avd_name: str | None = None, root_mode: str | None = None, android_api: int | None = None, port: int | None = None) -> None:
        from .lab_sessions import current, LAB_NAME
        self.sdk = sdk or AndroidSdk.discover()
        self._devices_cache: dict = {}
        if port is not None:
            if type(port) is not int or port < 5558 or port > 5680 or port % 2:
                raise ValueError('Porta do emulador inválida')
            self.port = str(port)
            self.serial = 'emulator-' + str(port)
        if avd_name is not None:
            if not LAB_NAME.fullmatch(avd_name) and avd_name != type(self).avd_name:
                raise ValueError("Invalid HuntMob AVD name")
            self.avd_name = avd_name
        elif sdk is None:
            self.avd_name = current().get('id', type(self).avd_name)

        if root_mode is None:
            record = current()
            if record.get('id') != self.avd_name:
                try:
                    import json
                    from .lab_sessions import root
                    record = json.loads((root() / (self.avd_name + '.json')).read_text())
                except (OSError, ValueError):
                    record = {}
            root_mode = record.get('root_mode', 'root')
        if root_mode not in {'root', 'stock'}:
            raise ValueError('Invalid root profile')
        self.root_mode = root_mode
        if android_api is None:
            android_api = record.get('android_api', 35) if 'record' in locals() else 35
        if type(android_api) is not int or android_api not in {30, 31, 32, 33, 34, 35, 36}: raise ValueError('Unsupported Android API')
        self.android_api = android_api
        from .host_runtime import android_host
        self.host = android_host()
        self.architecture = self.host.get('architecture','unsupported')
        self.package = 'system-images;android-' + str(android_api) + ';' + ('default' if root_mode == 'root' else 'google_apis_playstore') + ';' + self.architecture

    def select_target(self, package_id):
        """Bind an explicitly selected installed app to its owned per-app lab."""
        from .lab_sessions import LAB_LOCK,current,save
        if not isinstance(package_id,str) or not PACKAGE_ID.fullmatch(package_id):return {'ok':False,'reason':'Package ID inválido.'}
        with LAB_LOCK:
            lab=current()
            if lab.get('id')!=self.avd_name:return {'ok':False,'reason':'Lab selecionado mudou; atualize os dispositivos.'}
            if lab.get('package_id') and lab['package_id']!=package_id:return {'ok':False,'reason':'Outro app exige um lab separado. Crie um novo laboratório.'}
            if not self.sdk or self.status().get('state')!='device':return {'ok':False,'reason':'Android autorizado não está online.'}
            installed=_run((str(self.sdk.adb),'-s',self.serial,'shell','pm','path',package_id),timeout=10)
            paths=[line.removeprefix('package:').strip() for line in installed.stdout.splitlines() if line.startswith('package:')]
            if installed.returncode or not paths:return {'ok':False,'reason':'App selecionado não está instalado.'}
            with tempfile.TemporaryDirectory(prefix='huntmob-target-') as directory:
                apk=Path(directory)/'base.apk'
                pulled=_run((str(self.sdk.adb),'-s',self.serial,'pull',paths[0],str(apk)),timeout=180)
                if pulled.returncode or not apk.is_file():return {'ok':False,'reason':'Não foi possível identificar o APK instalado.'}
                digest=hashlib.sha256()
                with apk.open('rb') as source:
                    for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
                value=digest.hexdigest()
            if current().get('id')!=lab['id']:return {'ok':False,'reason':'Lab mudou durante a seleção; nenhum alvo foi atualizado.'}
            if value!=lab.get('apk_sha256'):
                from .dynamic_runtime import DYNAMIC
                DYNAMIC.stop()
            record={**lab,'package_id':package_id,'apk_sha256':value}
            save(record)
            return {'ok':True,'lab':record,'reason':'App instalado vinculado ao lab e SHA256 calculado.'}

    def open_play_store(self, package_id=''):
        if self.root_mode!='stock':return {'ok':False,'reason':'Play Store exige o perfil sem root com Google Play.'}
        if package_id and (not isinstance(package_id,str) or not PACKAGE_ID.fullmatch(package_id)):
            return {'ok':False,'reason':'Package ID inválido.'}
        status=self.status()
        if status.get('state')!='device' or status.get('properties',{}).get('sys.boot_completed')!='1':return {'ok':False,'reason':'Android Google Play não está pronto.'}
        packages=_run((str(self.sdk.adb),'-s',self.serial,'shell','pm','path','com.android.vending'),timeout=10)
        if packages.returncode or 'package:' not in packages.stdout:
            return {'ok':False,'reason':'Este device não tem Play Store. Use uma imagem Google Play oficial.'}
        command=(str(self.sdk.adb),'-s',self.serial,'shell','am','start','-W')
        command+=('-a','android.intent.action.VIEW','-d','market://details?id='+package_id,'-p','com.android.vending') if package_id else ('-a','android.intent.action.MAIN','-c','android.intent.category.LAUNCHER','-p','com.android.vending')
        result=_run(command,timeout=20)
        ok=result.returncode==0 and 'Error:' not in result.stdout and 'Error:' not in result.stderr
        return {'ok':ok,'reason':'Play Store aberta. Faça login manualmente no dispositivo; instalação e compatibilidade do app ainda precisam de validação.' if ok else 'Play Store não abriu. Confira o runtime Google Play.'}

    def prepare_profile(self, mode):
        if mode not in {'root', 'stock'} or not self.sdk:
            return {'ok': False, 'reason': 'Perfil ou SDK indisponível.'}
        target = AndroidWorker(self.sdk, root_mode=mode, android_api=self.android_api)
        if not target.host['supported']:
            return {'ok':False,'reason':target.host['reason']}
        if target.prerequisites().get('ready'):
            return {'ok': True, 'already_installed': True}
        try:
            result = _run((str(self.sdk.sdkmanager), '--sdk_root=' + str(self.sdk.root), target.package), timeout=900, input_text='')
        except (OSError, subprocess.TimeoutExpired):
            return {'ok': False, 'reason': 'Preparação não concluída. Verifique conexão e armazenamento do SDK.'}
        ready = target.prerequisites().get('ready')
        return {'ok': bool(ready), 'reason': '' if ready else 'Imagem não instalada. Verifique licenças Android no SDK Manager e conexão; nenhuma licença foi aceita automaticamente.'}

    def root_status(self):
        if not self.sdk or self.status().get('state') != 'device':
            return {'verified': False, 'reason': 'Device offline'}
        command = (str(self.sdk.adb), '-s', self.serial)
        try:
            shell = _run(command + ('shell', 'id'), timeout=5)
            su = _run(command + ('shell', 'su', '0', 'id'), timeout=5)
            build = _run(command + ('shell', 'getprop', 'ro.build.type'), timeout=5).stdout.strip()
            debuggable = _run(command + ('shell', 'getprop', 'ro.debuggable'), timeout=5).stdout.strip()
            rooted = 'uid=0(' in shell.stdout or (su.returncode == 0 and 'uid=0(' in su.stdout)
            matched = rooted if self.root_mode == 'root' else not rooted and build == 'user' and debuggable == '0'
            return {'verified': matched, 'root_available': rooted, 'build_type': build, 'debuggable': debuggable, 'profile': self.root_mode}
        except (OSError, subprocess.TimeoutExpired):
            return {'verified': False, 'reason': 'Root verification unavailable'}

    def enable_adb_root(self):
        """Enable adbd root only on this owned, debug-capable AVD and read it back."""
        if self.root_mode != 'root' or not self.sdk or self.status().get('state') != 'device':
            return {'ok': False, 'reason': 'ADB root exige um Android AOSP ativo.'}
        base = (str(self.sdk.adb), '-s', self.serial)
        name = _run(base + ('emu', 'avd', 'name'), timeout=5)
        if name.returncode or self.avd_name not in name.stdout.splitlines():
            return {'ok': False, 'reason': 'Identidade do AVD não confirmada para ADB root.'}
        identity = _run(base + ('shell', 'id', '-u'), timeout=5)
        if identity.returncode:
            return {'ok': False, 'reason': 'Não foi possível consultar o UID do ADB.'}
        if identity.stdout.strip() == '0':
            return {'ok': True, 'adb_root_enabled': True}
        build = _run(base + ('shell', 'getprop', 'ro.build.type'), timeout=5)
        debug = _run(base + ('shell', 'getprop', 'ro.debuggable'), timeout=5)
        if build.returncode or debug.returncode or build.stdout.strip() not in {'userdebug', 'eng'} or debug.stdout.strip() != '1':
            return {'ok': False, 'reason': 'A imagem iniciada não permite ADB root.'}
        changed = _run(base + ('root',), timeout=15)
        if changed.returncode or 'cannot run as root' in (changed.stdout + changed.stderr).lower():
            return {'ok': False, 'reason': 'O AVD recusou ADB root.'}
        waited = _run(base + ('wait-for-device',), timeout=25)
        observed = _run(base + ('emu', 'avd', 'name'), timeout=5)
        identity = _run(base + ('shell', 'id', '-u'), timeout=5)
        if waited.returncode or observed.returncode or self.avd_name not in observed.stdout.splitlines() or identity.returncode or identity.stdout.strip() != '0':
            return {'ok': False, 'reason': 'ADB root não foi confirmado no mesmo AVD AOSP.'}
        return {'ok': True, 'adb_root_enabled': True}

    def prerequisites(self) -> Dict[str, object]:
        if not self.host['supported']:
            return {'ready':False,'reason':self.host['reason'],'host':self.host}
        if not self.sdk:
            return {"ready": False, "reason": "Android SDK command-line tools not found"}
        config=Path(os.environ.get('ANDROID_AVD_HOME',str(Path.home()/'.android/avd')))/(self.avd_name+'.avd')/'config.ini'
        if config.is_file():
            values=dict(line.split('=',1) for line in config.read_text().splitlines() if '=' in line)
            actual=values.get('abi.type')
            if actual and actual!=self.architecture:
                return {'ready':False,'reason':'Arquitetura do lab salvo incompatível com este host; use o worker original ou crie um lab novo.','architecture':self.architecture,'saved_architecture':actual}
        image = self.sdk.root.joinpath(*self.package.split(";"), "system.img")
        return {
            "ready": self.sdk.emulator.exists() and image.exists(),
            "sdk_root": str(self.sdk.root),
            "emulator": str(self.sdk.emulator),
            "image": str(image),
            "architecture": self.architecture,
            "required_package": self.package,
            "apk_metadata_ready": any(path.is_file() and path.name in {'aapt','aapt.exe'} for path in (self.sdk.root/'build-tools').glob('*/aapt*')),
            "accelerator": {"Darwin": "hvf", "Linux": "kvm", "Windows": "whpx"}.get(platform.system(), "unknown"),
        }

    def create(self) -> Dict[str, object]:
        prerequisites = self.prerequisites()
        if not prerequisites["ready"]:
            return {"ok": False, "blocked": True, "reason": prerequisites.get("reason", "runtime packages missing")}
        listed = _run((str(self.sdk.emulator), "-list-avds"))
        if self.avd_name in listed.stdout.splitlines():
            return {"ok": True, "created": False, "avd": self.avd_name}
        result = _run(
            (str(self.sdk.avdmanager), "create", "avd", "--force", "--name", self.avd_name,
             "--package", self.package, "--device", "medium_phone"),
            timeout=120, input_text="no\n",
        )
        return {"ok": result.returncode == 0, "created": result.returncode == 0, "avd": self.avd_name, "error": result.stderr.strip()}

    def status(self, *, include_properties: bool = True) -> Dict[str, object]:
        if not self.sdk:
            return {"state": "unavailable", "serial": self.serial}
        try:
            result = _adb_devices(str(self.sdk.adb), cache=self._devices_cache)
        except (OSError, subprocess.TimeoutExpired):
            return {"state": "error", "serial": self.serial, "reason": "ADB did not respond; check the local worker"}
        if result.returncode != 0:
            return {"state": "error", "serial": self.serial, "reason": "ADB discovery failed"}
        state = "offline"
        attached = False
        for line in result.stdout.splitlines():
            if line.startswith(f"{self.serial}\t"):
                attached = True
                state = line.split("\t", 1)[1].strip()
        payload: Dict[str, object] = {"state": state, "serial": self.serial, "avd": self.avd_name, "attached": attached}
        if state == "device":
            try:
                identity = _run((str(self.sdk.adb), "-s", self.serial, "emu", "avd", "name"), timeout=3)
                observed = identity.stdout.splitlines()[0].strip() if identity.stdout.splitlines() else ""
            except (OSError, subprocess.TimeoutExpired):
                return {**payload, "state":"error", "ownership_verified":False, "reason":"Identidade do emulador indisponível; nenhuma ação será enviada."}
            if identity.returncode or observed != self.avd_name:
                return {**payload, "state":"error", "ownership_verified":False, "reason":"O serial ADB pertence a outro AVD. Reconecte o laboratório selecionado."}
            payload["ownership_verified"] = True
            if not include_properties:
                return payload
            props = {}
            for key in ("ro.build.version.release", "ro.build.version.sdk", "ro.product.cpu.abi", "sys.boot_completed"):
                try:
                    prop = _run((str(self.sdk.adb), "-s", self.serial, "shell", "getprop", key), timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    return {"state": "error", "serial": self.serial, "reason": "Android properties are unavailable"}
                if prop.returncode != 0:
                    return {"state": "error", "serial": self.serial, "reason": "Android disconnected during discovery"}
                value = prop.stdout.strip()
                props[key] = value
            payload["properties"] = props
        return payload

    def start(self, timeout: int = 180) -> Dict[str, object]:
        if not START_LOCK.acquire(blocking=False):
            return {"ok": False, "blocked": True, "reason": "Android is already starting; wait for the current operation"}
        try:
            return self._start(timeout)
        finally:
            START_LOCK.release()

    def emulator_options(self) -> tuple[str, ...]:
        """Use desktop GPU acceleration without requiring a GPU in Linux Docker."""
        default_gpu = 'host' if platform.system() in {'Darwin', 'Windows'} else 'auto'
        gpu = os.environ.get('HUNTMOB_ANDROID_GPU', default_gpu)
        memory = os.environ.get('HUNTMOB_ANDROID_MEMORY_MB', '4096' if self.root_mode == 'stock' else '3072')
        if gpu not in {'auto', 'host', 'software', 'swiftshader', 'swangle', 'lavapipe'}:
            raise ValueError('HUNTMOB_ANDROID_GPU inválido. Use auto, host ou software.')
        if not memory.isascii() or not memory.isdecimal() or not 1024 <= int(memory) <= 16384:
            raise ValueError('HUNTMOB_ANDROID_MEMORY_MB deve estar entre 1024 e 16384.')
        return ('-gpu', gpu, '-memory', str(int(memory)))

    def _launch_command(self, performance: tuple, camera: tuple) -> tuple:
        """Quick Boot (snapshot save/load) makes Resume take seconds instead of
        a full cold boot. The API 30 labs run with -writable-system, which
        conflicts with snapshots, so they stay on cold boot; HUNTMOB_ANDROID_QUICKBOOT=0
        forces a clean cold boot everywhere when lab hygiene needs it."""
        quick_boot = self.android_api != 30 and os.environ.get('HUNTMOB_ANDROID_QUICKBOOT', '1') != '0'
        return (
            str(self.sdk.emulator), f"@{self.avd_name}",
            *(("-writable-system",) if self.android_api == 30 else ()),
            "-no-window", "-no-audio", "-no-boot-anim", "-port", self.port,
            *(() if quick_boot else ("-no-snapshot-save",)),
            *performance, *camera,
        )

    def _reconcile_port_owner(self) -> bool:
        """An orphan HuntMob emulator from another lab can hold our console port,
        so status reports 'serial pertence a outro AVD'. Stop that orphan (its
        data persists on disk) so the selected lab can take the port. Never
        touches a non-HuntMob emulator; returns True when the port is freed."""
        if not self.sdk:
            return False
        from .lab_sessions import LAB_NAME
        adb = str(self.sdk.adb)
        observed = _run((adb, "-s", self.serial, "emu", "avd", "name"), timeout=5)
        name = observed.stdout.splitlines()[0].strip() if observed.returncode == 0 and observed.stdout.splitlines() else ""
        if not name or name == self.avd_name:
            return False
        if not (LAB_NAME.fullmatch(name) or name == type(self).avd_name):
            return False
        if _run((adb, "-s", self.serial, "emu", "kill"), timeout=15).returncode:
            return False
        self._devices_cache.clear()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", int(self.port)), timeout=0.25):
                    pass
            except OSError:
                self._devices_cache.clear()
                return True
            time.sleep(0.5)
        return False

    def _start(self, timeout: int) -> Dict[str, object]:
        existing = self.status()
        if existing["state"] == "device" and existing.get("properties", {}).get("sys.boot_completed") == "1":
            return {"ok": True, "started": False, **existing}
        # An orphan HuntMob emulator on our port surfaces as an ownership
        # mismatch; reconcile by stopping it and re-reading, instead of failing.
        if existing["state"] == "error" and existing.get("ownership_verified") is False and self._reconcile_port_owner():
            existing = self.status()
        if existing["state"] in {"error", "unauthorized"}:
            return {"ok": False, "blocked": True, "reason": existing.get("reason", "Device authorization is required")}
        try:
            performance = self.emulator_options()
        except ValueError as error:
            return {'ok': False, 'blocked': True, 'reason': str(error)}
        created = self.create()
        if not created["ok"]:
            return created
        log_dir = Path.home() / ".huntmob/logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / ("android-" + self.avd_name + ".log")
        log = log_path.open("a", encoding="utf-8")
        log_offset = log.tell()
        from .lab_sessions import current
        lab = current()
        camera = ('-camera-front', 'webcam0') if lab.get('id') == self.avd_name and lab.get('camera_front') == 'webcam0' else ()
        command = self._launch_command(performance, camera)
        # A device already visible to ADB may still be booting; never launch it twice.
        process = None
        if not existing.get("attached") and existing["state"] not in {"device", "unauthorized"}:
            try:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                log.close()
        else:
            log.close()
        deadline = time.monotonic() + timeout
        return self._await_boot(process, log_path, log_offset, deadline)

    def _await_boot(self, process, log_path, log_offset, deadline) -> Dict[str, object]:
        recovered = False
        stale = 0
        while time.monotonic() < deadline:
            if process is not None and process.poll() is not None:
                with log_path.open('rb') as details:
                    details.seek(log_offset)
                    failure_log = details.read(262144).decode('utf-8', errors='replace')
                if 'not have enough disk space' in failure_log:
                    import shutil
                    return {'ok': False, 'blocked': True, 'error_code': 'insufficient_disk_space',
                            'free_bytes': shutil.disk_usage(Path.home()).free,
                            'reason': 'Espaço insuficiente no worker para iniciar o Android. Libere espaço no Mac e clique novamente no aparelho na lista lateral. A identidade e os dados foram preservados.'}
                return {"ok": False, "blocked": True, "reason": "Android Emulator exited before boot completed; check worker logs"}
            current = self.status()
            if current["state"] == "device" and current.get("properties", {}).get("sys.boot_completed") == "1":
                return {"ok": True, "started": True, **current}
            # A stale adb transport can report the previous AVD on the reused
            # console port right after a switch; recover it once instead of
            # letting "serial pertence a outro AVD" wait out the whole timeout.
            if current.get("state") == "error" and current.get("ownership_verified") is False:
                stale += 1
                if stale >= _ADB_RECOVER_POLLS and not recovered:
                    self._recover_adb()
                    recovered = True
            else:
                stale = 0
            time.sleep(2)
        return {"ok": False, "blocked": True, "reason": "Android boot timed out", **self.status()}

    def stop(self) -> Dict[str, object]:
        if not self.sdk:
            return {"ok": False, "reason": "Android SDK unavailable"}
        status=self.status(include_properties=False)
        if not status.get('attached') and status.get('state')=='offline':return {'ok':True,'state':'stopped'}
        if status.get('ownership_verified') is not True:return {'ok':False,'blocked':True,'reason':'Não foi possível confirmar o AVD selecionado; nenhum device foi desligado.'}
        result = _run((str(self.sdk.adb), "-s", self.serial, "emu", "kill"))
        if result.returncode:
            return {"ok": False, "state": "stopping", "error": result.stderr.strip()}
        # O kill muda o estado que o cache de `adb devices` guardou; a
        # verificação de detach abaixo precisa ler fresh.
        self._devices_cache.clear()
        # ADB acknowledges `emu kill` before QEMU releases its console port.
        # An immediate Resume would otherwise start a second process on that port.
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            detached = self.status(include_properties=False).get('attached') is False
            try:
                with socket.create_connection(('127.0.0.1', int(self.port)), timeout=0.25):
                    port_free = False
            except OSError:
                port_free = True
            if detached and port_free:
                return {"ok": True, "state": "stopped"}
            time.sleep(0.5)
        return {"ok": False, "state": "stopping", "reason": "O Android ainda está desligando; aguarde e tente retomar novamente."}

    def _recover_adb(self) -> None:
        """Un-wedge a stuck adb transport the way the operator did by hand:
        reconnect the device, then bounce the adb server. Scoped to adb only —
        the worker↔gateway pairing is HTTP and is not touched."""
        if not self.sdk:
            return
        adb = str(self.sdk.adb)
        self._devices_cache.clear()
        _run((adb, "-s", self.serial, "reconnect"), timeout=10)
        _run((adb, "kill-server"), timeout=10)
        _run((adb, "start-server"), timeout=15)
        self._devices_cache.clear()

    def reboot(self, timeout: int = 180) -> Dict[str, object]:
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "reboot"))
        if result.returncode != 0:
            return {"ok": False, "blocked": True, "reason": "reboot command failed"}
        deadline = time.monotonic() + timeout
        recovered = False
        wedged = 0
        while time.monotonic() < deadline:
            status = self.status()
            if status["state"] == "device" and status.get("properties", {}).get("sys.boot_completed") == "1":
                return {"ok": True, "state": "device", "rebooted": True, "recovered": recovered}
            # A transport stuck offline/error after reboot is the loop the
            # operator used to clear by hand; recover the adb server once.
            if status["state"] in {"offline", "error"}:
                wedged += 1
                if wedged >= _ADB_RECOVER_POLLS and not recovered:
                    self._recover_adb()
                    recovered = True
            else:
                wedged = 0
            time.sleep(2)
        return {"ok": False, "blocked": True, "reason": "reboot timed out", "recovered": recovered}

    def destroy(self, timeout: int = 45) -> Dict[str, object]:
        """Delete only the fixed HuntMob AVD after stopping its emulator."""
        if not self.sdk:
            return {"ok": False, "reason": "Android SDK unavailable"}
        status=self.status()
        if status.get('attached') and status.get('state')!='device':return {'ok':False,'blocked':True,'reason':'Android ainda está conectado sem identidade validada; lab preservado.'}
        if status.get('state') in {'error','unauthorized'}:return {'ok':False,'blocked':True,'reason':status.get('reason','Device não identificado; lab preservado.')}
        if status["state"] == "device":
            stopped=self.stop()
            if not stopped.get('ok'):return stopped
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                state=self.status()
                if state.get('state')=='offline' and not state.get('attached'):break
                time.sleep(1)
            else:return {'ok':False,'blocked':True,'reason':'Android ainda está conectado; nenhum AVD foi apagado.'}
        result = _run((str(self.sdk.avdmanager), "delete", "avd", "--name", self.avd_name), timeout=60)
        deleted = result.returncode == 0 or "does not exist" in (result.stderr + result.stdout).lower()
        if deleted:
            from .lab_sessions import current, save
            record = current()
            if record.get('id') == self.avd_name:
                save({**record, 'state': 'destroyed'})
        return {"ok": deleted, "state": "destroyed" if deleted else "error", "error": "" if deleted else result.stderr.strip()}

    def install_and_launch(self, apk: Path, package_id: str, *, legacy_sdk: bool = False, grant_permissions: bool = False) -> Dict[str, object]:
        if not PACKAGE_ID.fullmatch(package_id):
            return {"ok": False, "reason": "invalid package ID"}
        if not apk.is_file() or apk.suffix.lower() != ".apk":
            return {"ok": False, "blocked": True, "reason": "an existing APK is required"}
        if self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        api = int(self.status().get("properties", {}).get("ro.build.version.sdk", "0"))
        # Explicit permission grant prevents Android from diverting the first
        # launch to ReviewPermissionsActivity while `am start -W` still exits 0.
        flags = (("-g",) if grant_permissions else ()) + (("--bypass-low-target-sdk-block",) if legacy_sdk and api >= 34 else ())
        install = _run((str(self.sdk.adb), "-s", self.serial, "install", "-r", *flags, str(apk)), timeout=180)
        if install.returncode != 0:
            details = (install.stderr + "\n" + install.stdout).strip()
            failure = __import__("re").search(r"Failure \[(.*?)\]", details, __import__("re").S)
            reason = failure[1] if failure else "APK installation failed"
            return {"ok": False, "blocked": True, "reason": reason, "error": details}
        return self.launch_app(package_id)

    def launch_app(self, package_id):
        if not self.sdk or not PACKAGE_ID.fullmatch(package_id):
            return {'ok': False, 'reason': 'Invalid package or SDK unavailable'}
        resolved = _run((str(self.sdk.adb), "-s", self.serial, "shell", "cmd", "package", "resolve-activity", "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", package_id))
        component = next((line.strip() for line in reversed(resolved.stdout.splitlines()) if line.strip().startswith(package_id + "/")), "")
        if not component:
            return {"ok": False, "installed": True, "launched": False, "package_id": package_id, "reason": "APK installed but no launcher activity was found"}
        launch = _run((str(self.sdk.adb), "-s", self.serial, "shell", "am", "start", "-W", "-n", component))
        accepted = launch.returncode == 0 and "Error:" not in launch.stdout + launch.stderr
        stable_pid = ""
        if accepted:
            previous = set()
            for _ in range(10):
                listing = _run((str(self.sdk.adb), "-s", self.serial, "shell", "ps", "-A", "-o", "PID,NAME"), timeout=5).stdout
                observed = {
                    (match[1], match[2]) for line in listing.splitlines()
                    if (match := __import__('re').fullmatch(r'\s*(\d+)\s+([^\s]+)\s*', line))
                    and (match[2] == package_id or match[2].startswith(package_id + ':'))
                }
                stable = previous & observed
                if stable:
                    stable_pid = ' '.join(sorted(pid for pid, _name in stable))
                    break
                previous = observed
                time.sleep(0.25)
        launched = bool(stable_pid)
        if launched:
            reason = ""
        elif accepted:
            reason = "APK installed, but its process did not remain alive after launch."
        else:
            reason = (launch.stderr + launch.stdout).strip()
        return {"ok": launched, "package_id": package_id, "installed": True, "launched": launched, "pid": stable_pid, "reason": reason}

    def install_apk_set(self, apks, package_id, *, legacy_sdk=False, grant_permissions=False):
        """Install an original base and split set without changing its signatures."""
        if not PACKAGE_ID.fullmatch(package_id) or not isinstance(apks, (list, tuple)) or not 1 <= len(apks) <= 128:
            return {'ok': False, 'reason': 'Conjunto de APKs inválido.'}
        if any(not isinstance(path, Path) or not path.is_file() or path.suffix != '.apk' for path in apks):
            return {'ok': False, 'reason': 'Conjunto de APKs incompleto.'}
        if len(apks) == 1:
            return self.install_and_launch(apks[0], package_id, legacy_sdk=legacy_sdk, grant_permissions=grant_permissions)
        if not self.sdk or self.status().get('state') != 'device':
            return {'ok': False, 'reason': 'Android desconectado.'}
        api = int(self.status().get('properties', {}).get('ro.build.version.sdk', '0'))
        flags = (('-g',) if grant_permissions else ()) + (('--bypass-low-target-sdk-block',) if legacy_sdk and api >= 34 else ())
        result = _run((str(self.sdk.adb), '-s', self.serial, 'install-multiple', '-r', *flags, *(str(path) for path in apks)), timeout=180)
        if result.returncode or 'Success' not in result.stdout:
            return {'ok': False, 'reason': 'Não foi possível instalar o conjunto original de APKs.', 'error': (result.stderr + result.stdout).strip()}
        return {**self.launch_app(package_id), 'apk_count': len(apks)}

    def upload_and_launch(self, apk: Path, *, new_lab: bool = False, root_mode: str = "root", android_api: int = 35, engagement: str = '') -> Dict[str, object]:
        if not self.sdk:
            return {"ok": False, "reason": "Android SDK unavailable"}
        candidates = sorted((self.sdk.root / "build-tools").glob("*/aapt*"))
        aapt = next((path for path in candidates if path.name in {"aapt", "aapt.exe"}), None)
        if not aapt:
            return {"ok": False, "reason": "Android build-tools (aapt) required to detect APK package"}
        metadata = _run((str(aapt), "dump", "badging", str(apk)))
        match = __import__("re").search(r"package: name='([^']+)'", metadata.stdout)
        if metadata.returncode or not match or not PACKAGE_ID.fullmatch(match[1]):
            return {"ok": False, "reason": "invalid APK or unreadable package metadata"}
        from .lab_sessions import create_lab, current, save
        bound = current().get('package_id', '')
        if not new_lab and bound and bound != match[1]:
            return {"ok": False, "reason": "Different app requires a new isolated lab"}
        digest = hashlib.sha256(apk.read_bytes()).hexdigest()
        started = create_lab(self, match[1], digest, root_mode=root_mode, android_api=android_api, engagement=engagement) if new_lab else self.start()
        if not started.get("ok"):
            return started
        target = AndroidWorker(self.sdk, avd_name=started['lab']['id']) if new_lab else self
        # Old-target APKs still install (auto-detected bypass on API 34+), but we
        # never auto-grant permissions — a pentest must see the real prompts.
        result = target.install_and_launch(apk, match[1], legacy_sdk=_old_target_sdk(metadata.stdout), grant_permissions=False)
        if new_lab:
            result['lab'] = started['lab']
        elif result.get('installed') and current().get('id') == self.avd_name:
            record = {**current(), 'package_id': match[1], 'apk_sha256': digest}
            save(record)
            result['lab'] = record
        return result

    def device_input(self, payload: dict) -> Dict[str, object]:
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "reason": "device is not online"}
        action = payload.get("action")
        if action == "back":
            command = ("keyevent", "4")
        elif action == 'key':
            key={'Backspace':'67','Enter':'66','Tab':'61','ArrowUp':'19','ArrowDown':'20','ArrowLeft':'21','ArrowRight':'22'}.get(payload.get('key'))
            if not key: return {'ok':False,'reason':'Unsupported key'}
            command=('keyevent',key)
        elif action == "text":
            value = str(payload.get("text", ""))
            if not value or len(value) > 256 or not __import__("re").fullmatch(r"[A-Za-z0-9 @._+:/-]+", value):
                return {"ok": False, "reason": "Use ASCII text up to 256 characters"}
            command = ("text", value.replace(" ", "%s"))
        elif action in {"tap", "swipe"}:
            # Input viewport dimensions follow actual display rotation, including
            # apps which keep portrait despite a requested landscape orientation.
            viewport = _run((str(self.sdk.adb), "-s", self.serial, "shell", "dumpsys", "input"), timeout=5).stdout
            matches = __import__("re").findall(r"Viewport INTERNAL: displayId=0[^\n]*logicalFrame=\[0, 0, (\d+), (\d+)\]", viewport)
            matches = [match for match in matches if int(match[0]) > 0 and int(match[1]) > 0]
            if not matches:
                size = _run((str(self.sdk.adb), "-s", self.serial, "shell", "wm", "size")).stdout
                matches = __import__("re").findall(r"(\d+)x(\d+)", size)
            if not matches:
                return {"ok": False, "reason": "display size unavailable"}
            width, height = map(int, matches[-1])
            try:
                points = [float(payload[key]) for key in (("x", "y") if action == "tap" else ("x", "y", "end_x", "end_y"))]
                if not all(0 <= point <= 1 for point in points):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "reason": "invalid display coordinates"}
            coords = [str(min((width if index % 2 == 0 else height) - 1, int(point * (width if index % 2 == 0 else height)))) for index, point in enumerate(points)]
            command = (action, *coords, *(("300",) if action == "swipe" else ()))
        else:
            return {"ok": False, "reason": "unsupported input action"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "input", *command))
        return {"ok": result.returncode == 0}

    def screenshot(self) -> bytes:
        if not self.sdk or self.status()["state"] != "device":
            return b""
        result = subprocess.run(
            (str(self.sdk.adb), "-s", self.serial, "exec-out", "screencap", "-p"),
            capture_output=True, timeout=15, check=False,
        )
        return result.stdout if result.returncode == 0 and result.stdout.startswith(b"\x89PNG") else b""

    def app_files(self, package_id: str) -> Dict[str, object]:
        """List APK entries and the authorized app sandbox without changing it."""
        if not PACKAGE_ID.fullmatch(package_id):
            return {"ok": False, "blocked": True, "reason": "invalid package ID"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        installed = _run((str(self.sdk.adb), "-s", self.serial, "shell", "pm", "path", package_id))
        apk_paths = [line.removeprefix("package:").strip() for line in installed.stdout.splitlines() if line.startswith("package:")]
        if installed.returncode != 0 or not apk_paths:
            return {"ok": False, "blocked": True, "reason": "authorized package is not installed"}

        apk_entries: List[Dict[str, object]] = []
        with tempfile.TemporaryDirectory(prefix="huntmob-apk-") as directory:
            for index, remote in enumerate(apk_paths[:8]):
                local = Path(directory) / f"split-{index}.apk"
                pulled = _run((str(self.sdk.adb), "-s", self.serial, "pull", remote, str(local)), timeout=180)
                if pulled.returncode != 0 or not local.is_file():
                    continue
                try:
                    with zipfile.ZipFile(local) as archive:
                        for item in archive.infolist()[:5000]:
                            apk_entries.append({"path": item.filename, "size": item.file_size, "split": Path(remote).name})
                except zipfile.BadZipFile:
                    continue

        sandbox = _run(
            (str(self.sdk.adb), "-s", self.serial, "shell", "run-as", package_id,
             "find", ".", "-maxdepth", "5", "-print"), timeout=30,
        )
        sandbox_paths = [line.strip() for line in sandbox.stdout.splitlines() if line.strip()][:5000]
        sandbox_ready = sandbox.returncode == 0
        return {
            "ok": True,
            "package_id": package_id,
            "apk": {"paths": apk_paths, "entries": apk_entries, "truncated": len(apk_entries) >= 5000},
            "sandbox": {
                "root": f"/data/user/0/{package_id}",
                "alias": f"/data/data/{package_id}",
                "accessible": sandbox_ready,
                "mode": "run-as",
                "entries": sandbox_paths,
                "reason": "" if sandbox_ready else "run-as denied; a debuggable or explicitly prepared HuntMob lab build is required",
            },
        }

    def read_app_file(self, package_id: str, source: str, path: str) -> Dict[str, object]:
        """Lê o conteúdo de UM arquivo do app autorizado: uma entrada do APK
        (``source='apk'``) ou um caminho do sandbox via run-as (``source='sandbox'``).
        Somente leitura — nunca escreve no device."""
        if not PACKAGE_ID.fullmatch(package_id):
            return {"ok": False, "blocked": True, "reason": "invalid package ID"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        if source == "apk":
            return self._read_apk_entry(package_id, path)
        if source == "sandbox":
            return self._read_sandbox_file(package_id, path)
        return {"ok": False, "blocked": True, "reason": "unknown source"}

    def _read_apk_entry(self, package_id: str, path: str) -> Dict[str, object]:
        installed = _run((str(self.sdk.adb), "-s", self.serial, "shell", "pm", "path", package_id))
        apk_paths = [line.removeprefix("package:").strip() for line in installed.stdout.splitlines() if line.startswith("package:")]
        if installed.returncode != 0 or not apk_paths:
            return {"ok": False, "blocked": True, "reason": "authorized package is not installed"}
        with tempfile.TemporaryDirectory(prefix="huntmob-apk-") as directory:
            for index, remote in enumerate(apk_paths[:8]):
                local = Path(directory) / f"split-{index}.apk"
                pulled = _run((str(self.sdk.adb), "-s", self.serial, "pull", remote, str(local)), timeout=180)
                if pulled.returncode != 0 or not local.is_file():
                    continue
                try:
                    with zipfile.ZipFile(local) as archive:
                        if path not in archive.namelist():
                            continue
                        with archive.open(path) as handle:
                            raw = handle.read(_MAX_FILE_BYTES + 1)
                except (zipfile.BadZipFile, KeyError, OSError):
                    continue
                return _decode_file(package_id, "apk", path, raw)
        return {"ok": False, "blocked": True, "reason": "entry not found in APK"}

    def _read_sandbox_file(self, package_id: str, path: str) -> Dict[str, object]:
        if not path or ".." in path or not _SAFE_SANDBOX_PATH.fullmatch(path):
            return {"ok": False, "blocked": True, "reason": "unsafe sandbox path"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "run-as", package_id, "cat", path), timeout=30)
        if result.returncode != 0:
            return {"ok": False, "blocked": True,
                    "reason": result.stderr.strip() or "run-as denied; a debuggable or explicitly prepared HuntMob lab build is required"}
        raw = result.stdout.encode("utf-8", "surrogateescape")
        return _decode_file(package_id, "sandbox", path, raw)

    def installed_apps(self) -> Dict[str, object]:
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online", "apps": []}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "pm", "list", "packages", "-3", "-f"))
        apps = []
        for line in result.stdout.splitlines():
            if not line.startswith("package:") or "=" not in line:
                continue
            apk_path, package_id = line.removeprefix("package:").rsplit("=", 1)
            if PACKAGE_ID.fullmatch(package_id):
                apps.append({"package_id": package_id, "apk_path": apk_path})
        return {"ok": result.returncode == 0, "apps": sorted(apps, key=lambda item: item["package_id"])}

    def proxy_status(self, port: int = 8080) -> Dict[str, object]:
        configured = ""
        if self.sdk and self.status()["state"] == "device":
            configured = _run((str(self.sdk.adb), "-s", self.serial, "shell", "settings", "get", "global", "http_proxy")).stdout.strip()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                listening = True
        except OSError:
            listening = False
        from .lab_sessions import current
        route_required = current().get('package_id') == 'com.android.insecurebankv2'
        route_active = False
        capture_note = ''
        try:
            import json
            from .lab_sessions import current
            record = json.loads((Path.home() / '.huntmob/run/app-capture.json').read_text())
            if self.sdk and record.get('lab_id') == current().get('id') and record.get('proxy_port') == port:
                rules = _run((str(self.sdk.adb), '-s', self.serial, 'shell', 'su', '0', 'iptables', '-t', 'nat', '-S', 'OUTPUT'), timeout=5).stdout
                route_active = any('HuntMob-local-app' in line and f"--uid-owner {int(record['uid'])} " in line and f"--dport {int(record['backend_port'])} " in line and f"--to-destination 10.0.2.2:{port}" in line for line in rules.splitlines())
                capture_note = 'Captura HTTP por app ativa.' if route_active else 'Rota do app ausente. Clique em Iniciar captura para reaplicar.'
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            pass
        from .managed_proxy import owned
        return {"configured": configured == f"10.0.2.2:{port}", "device_proxy_set": configured not in {"", ":0", "null"}, "device_proxy": configured, "listener": listening, "native_listener":listening and owned(port), "host_port": port, "direct_capture": route_active, "direct_capture_required": route_required, "capture_note": capture_note}

    def configure_proxy(self, port: int = 8080) -> Dict[str, object]:
        if not 1024 <= port <= 65535:
            return {"ok": False, "blocked": True, "reason": "proxy port must be between 1024 and 65535"}
        status = self.proxy_status(port)
        if not status["listener"]:
            return {"ok": False, "blocked": True, "reason": f"no proxy listener is available on 127.0.0.1:{port}"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        route = f"10.0.2.2:{port}"
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "settings", "put", "global", "http_proxy", route))
        return {"ok": result.returncode == 0, "device_proxy": route, "listener": True}

    def configure_local_app_capture(self, port: int) -> Dict[str, object]:
        """Route only the known lab app's local HTTP backend through the proxy."""
        import json
        import xml.etree.ElementTree as ET
        from .lab_sessions import current
        lab = current()
        if lab.get('package_id') != 'com.android.insecurebankv2' or lab.get('apk_sha256') != 'b18af2a0e44d7634bbcdf93664d9c78a2695e050393fcfbb5e8b91f902d194a4':
            return {'direct_capture': False, 'capture_note': 'Proxy Android configurado; confirme que o app usa essa rota.'}
        root = _run((str(self.sdk.adb), '-s', self.serial, 'shell', 'su', '0', 'id'), timeout=5)
        if root.returncode != 0 or 'uid=0' not in root.stdout:
            return {'direct_capture': False, 'capture_note': 'Este cliente HTTP ignora o proxy; o worker não oferece roteamento por app.'}
        prefs = _run((str(self.sdk.adb), '-s', self.serial, 'shell', 'run-as', lab['package_id'], 'cat', 'shared_prefs/com.android.insecurebankv2_preferences.xml'), timeout=5)
        try:
            values = {node.attrib.get('name'): node.text or '' for node in ET.fromstring(prefs.stdout)}
            host = values.get('serverip', '')
            backend_port = int(values.get('serverport', ''))
        except (ValueError, ET.ParseError):
            return {'direct_capture': False, 'capture_note': 'Configure o backend local no aplicativo antes de capturar login.'}
        if host != '10.0.2.2' or not 1024 <= backend_port <= 65535 or backend_port == port:
            return {'direct_capture': False, 'capture_note': 'Roteamento direto disponível somente para backend HTTP local via 10.0.2.2, em porta diferente do proxy.'}
        package = _run((str(self.sdk.adb), '-s', self.serial, 'shell', 'cmd', 'package', 'list', 'packages', '-U', lab['package_id']), timeout=5)
        match = __import__('re').search(r'^package:com\.android\.insecurebankv2 uid:(\d+)$', package.stdout.strip(), __import__('re').M)
        if not match:
            return {'direct_capture': False, 'capture_note': 'UID do app não confirmado.'}
        uid = match[1]
        self.clear_local_app_capture()
        rule = ('OUTPUT', '-p', 'tcp', '-m', 'owner', '--uid-owner', uid, '-d', '10.0.2.2/32', '--dport', str(backend_port), '-m', 'comment', '--comment', 'HuntMob-local-app', '-j', 'DNAT', '--to-destination', f'10.0.2.2:{port}')
        command = (str(self.sdk.adb), '-s', self.serial, 'shell', 'su', '0', 'iptables', '-t', 'nat')
        checked = _run(command + ('-C',) + rule, timeout=5)
        if checked.returncode != 0:
            added = _run(command + ('-A',) + rule, timeout=5)
            if added.returncode != 0:
                return {'direct_capture': False, 'capture_note': 'Não foi possível instalar a rota por app.'}
        record = {'lab_id': lab['id'], 'package_id': lab['package_id'], 'uid': int(uid), 'backend_port': backend_port, 'proxy_port': port}
        store = Path.home() / '.huntmob/run/app-capture.json'
        store.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(os.open(store, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as stream:
            json.dump(record, stream)
        try:
            with socket.create_connection(('127.0.0.1', backend_port), timeout=.3):
                backend_available = True
        except OSError:
            backend_available = False
        return {'direct_capture': True, 'backend_available': backend_available,
                'capture_note': 'Captura HTTP por app ativa.' + ('' if backend_available else f' Backend local na porta {backend_port} indisponível; o login poderá falhar, mas a tentativa será capturada.')}

    def clear_local_app_capture(self) -> None:
        import json
        from .lab_sessions import current
        store = Path.home() / '.huntmob/run/app-capture.json'
        try:
            record = json.loads(store.read_text())
            if record.get('package_id') != 'com.android.insecurebankv2':
                return
            if record.get('lab_id') == current().get('id'):
                uid, backend_port, port = int(record['uid']), int(record['backend_port']), int(record['proxy_port'])
                if not 10000 <= uid <= 999999 or not 1024 <= backend_port <= 65535 or not 1024 <= port <= 65534:
                    return
                rule = ('OUTPUT', '-p', 'tcp', '-m', 'owner', '--uid-owner', str(uid), '-d', '10.0.2.2/32', '--dport', str(backend_port), '-m', 'comment', '--comment', 'HuntMob-local-app', '-j', 'DNAT', '--to-destination', f'10.0.2.2:{port}')
                result = _run((str(self.sdk.adb), '-s', self.serial, 'shell', 'su', '0', 'iptables', '-t', 'nat', '-D') + rule, timeout=5)
                if result.returncode != 0:
                    return
            store.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            pass

    def clear_proxy(self) -> Dict[str, object]:
        self.clear_local_app_capture()
        if not self.sdk or self.status(include_properties=False)["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "settings", "put", "global", "http_proxy", ":0"))
        return {"ok": result.returncode == 0, "device_proxy": ":0"}

    def open_certificate_settings(self) -> Dict[str, object]:
        """Open Android's security settings; certificate trust remains a user action."""
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        result = _run((str(self.sdk.adb), "-s", self.serial, "shell", "am", "start", "-a", "android.settings.SECURITY_SETTINGS"), timeout=10)
        return {"ok": result.returncode == 0, "reason": "Não foi possível abrir os ajustes de segurança." if result.returncode else "Ajustes de segurança abertos; instale e confira a CA manualmente."}

    def start_managed_proxy(self, port: int = 8080) -> Dict[str, object]:
        """Start a headless capture listener; the HuntMob UI owns the inspector."""
        if not 1024 <= port <= 65534:
            return {"ok": False, "blocked": True, "reason": "proxy port must be between 1024 and 65534"}
        from .lab_backend import supported_lab, ensure_backend
        backend = ensure_backend() if supported_lab() else {}
        executable = shutil.which("mitmdump")
        if not executable:
            return {"ok": False, "blocked": True, "reason": "O worker de captura não está disponível (mitmdump)."}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        from . import managed_proxy
        listener=self.proxy_status(port)['listener']
        if listener and not managed_proxy.owned(port):
            return {'ok':False,'reason':'Porta ocupada por um listener sem identidade HuntMob confirmada. Escolha outra porta para captura nativa ou use Configurar Burp.'}
        if not listener:
            run_dir = Path.home() / ".huntmob" / "run"
            run_dir.mkdir(parents=True, exist_ok=True)
            log = (run_dir / "proxy.log").open("a", encoding="utf-8")
            command = (
                executable, "--quiet", "--listen-host", "127.0.0.1", "--listen-port", str(port),
                "-s", str(Path(__file__).with_name("network_capture.py")),
                "--set", "block_global=false",
            )
            try:
                process=subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                managed_proxy.remember(port,process,command)
            finally:
                log.close()
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline and not self.proxy_status(port)["listener"]:
                if process.poll() is not None:break
                time.sleep(0.25)
            if process.poll() is not None or not managed_proxy.owned(port):
                return {'ok':False,'reason':'Motor de captura não iniciou ou não foi identificado; nenhuma rota do device foi alterada.'}
        configured = self.configure_proxy(port)
        if not configured.get("ok"):
            return configured
        return {
            **configured,
            "managed": True,
            "capture_backend": "headless",
            "lab_backend": backend,
            **self.configure_local_app_capture(port),
            "ca_path": str(Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.cer"),
            "ca_installed": False,
        }

    def prepare_reverse(self, package_id: str) -> Dict[str, object]:
        """Pull an installed APK and decompile it into a package-scoped workspace."""
        if not PACKAGE_ID.fullmatch(package_id):
            return {"ok": False, "blocked": True, "reason": "invalid package ID"}
        if not self.sdk or self.status()["state"] != "device":
            return {"ok": False, "blocked": True, "reason": "device is not online"}
        installed = _run((str(self.sdk.adb), "-s", self.serial, "shell", "pm", "path", package_id))
        apk_paths = [line.removeprefix("package:").strip() for line in installed.stdout.splitlines() if line.startswith("package:")]
        if installed.returncode != 0 or not apk_paths:
            return {"ok": False, "blocked": True, "reason": "authorized package is not installed"}
        engine = EmbeddedAnalysis()
        engine_status = engine.status()
        if not engine_status['ready']:
            return {"ok": False, "blocked": True, "reason": engine_status['reason']}
        from .reverse_workspace import prepare_workspace
        workspace = prepare_workspace(package_id, self.avd_name)
        base_apk = workspace / "base.apk"
        pulled = _run((str(self.sdk.adb), "-s", self.serial, "pull", apk_paths[0], str(base_apk)), timeout=180)
        if pulled.returncode != 0 or not base_apk.is_file():
            return {"ok": False, "blocked": True, "reason": "APK pull failed"}
        base_apk.chmod(0o600)
        # Each run has fresh output; earlier files must not hide a failed run.
        output = workspace / "jadx-runs" / uuid4().hex
        output.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(base_apk.read_bytes()).hexdigest()
        try:
            decoded = _run(engine.command(base_apk, output), timeout=300, env=engine.environment())
        except subprocess.TimeoutExpired:
            return {"ok": False, "blocked": True, "reason": "A análise excedeu 5 minutos. Tente novamente com mais recursos no worker.", "sha256": digest}
        except OSError:
            return {"ok": False, "blocked": True, "reason": "Não foi possível iniciar o motor integrado. Verifique a instalação do HuntMob.", "sha256": digest}
        files = sorted(str(path.relative_to(output)) for path in output.rglob("*") if path.is_file())
        # JADX 1.5.5 exits 3 after saving code with decompilation errors.
        # Other nonzero exits remain failures, even if some files were written.
        partial = decoded.returncode == 3 and bool(files)
        if decoded.returncode not in (0, 3) or not files:
            exhausted = 'OutOfMemoryError' in decoded.stderr or 'OutOfMemoryError' in decoded.stdout
            reason = ('Memória insuficiente para decompilar este APK no motor integrado. Feche outras análises e tente novamente em um host com mais memória.'
                      if exhausted else f'O motor integrado não gerou uma análise utilizável (saída {decoded.returncode}). Verifique o APK e tente novamente.')
            return {"ok": False, "blocked": True, "reason": reason, "exit_code": decoded.returncode, "sha256": digest}
        match = __import__("re").search(r"finished with errors, count:\s*(\d+)", decoded.stdout + "\n" + decoded.stderr)
        errors_count = int(match[1]) if match else None
        problem_files = []
        for path in output.rglob('*.java'):
            content = path.read_text(encoding='utf-8', errors='replace')
            if 'JADX ERROR' in content or 'Method not decompiled' in content:
                problem_files.append(str(path.relative_to(output)))
        fallback_status = 'not_needed'
        # A second full pass over a large APK can double the request duration.
        # Preserve the first pass and its per-file errors instead of timing out.
        if partial and len(files) > 5000:
            fallback_status = 'skipped_large_analysis'
        elif partial:
            try:
                rescue = _run(engine.command(base_apk, output / 'instructions') + ('--decompilation-mode', 'fallback', '--no-res'), timeout=300, env=engine.environment())
                fallback_files = [path for path in (output / 'instructions').rglob('*') if path.is_file()]
                fallback_status = 'available' if rescue.returncode == 0 and fallback_files else 'partial' if rescue.returncode == 3 and fallback_files else 'unavailable'
            except (OSError, subprocess.TimeoutExpired):
                fallback_status = 'unavailable'
        files = sorted(str(path.relative_to(output)) for path in output.rglob('*') if path.is_file())
        result = {"ok": True, "package_id": package_id, "sha256": digest,
                "workspace": str(workspace), "output_directory": str(output), 'run_id': output.name,
                "files": files, "file_count": len(files), "truncated": False,
                "status": "partial" if partial else "complete", "exit_code": decoded.returncode,
                "errors_count": errors_count, 'fallback_status': fallback_status, 'problem_files': problem_files,
                "warning": "Reconstrução Java parcial; consulte as instruções de baixo nível nos métodos com erro." if partial else ""}
        import json
        temporary = workspace / ('analysis-' + uuid4().hex + '.tmp')
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(result, stream)
        temporary.replace(workspace / 'analysis.json')
        return result
