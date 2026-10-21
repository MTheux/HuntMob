"""Owned-lab Frida observations and portable evidence receipts. No raw script execution."""
import hashlib
import json
import lzma
import os
import re
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .android_worker import AndroidWorker, _run
from .lab_sessions import current, root
from .network_capture import redact, visible_snapshot

OBSERVERS = {'tls-observe', 'biometric-monitor', 'root-detection-observe', 'webview-observe', 'crypto-observe', 'file-observe'}
FORWARD_PORT = 27052
MAX_EVENT_BYTES = 2 * 1024 * 1024
MAX_SESSION_SECONDS = 30 * 60


def frida_compatibility(android_api, android_abi, client_version):
    """Fail closed for runtime tuples reproduced as incompatible in this lab."""
    if android_api == 30 and android_abi == 'arm64-v8a' and client_version == '17.23.3':
        return {
            'ok': False,
            'error_code': 'frida_android_sigchain_incompatible',
            'reason': 'Frida 17.23.3 aborta no Android API 30 arm64 durante a validação de signal chain. Selecione outro runtime validado; downgrade automático é proibido.',
        }
    return {'ok': True}


def frida_server_ready(command, frida_module):
    """Probe the Frida protocol; Android's pidof may hide long process names."""
    forwarded = _run(command + ('forward', f'tcp:{FORWARD_PORT}', 'tcp:27042'), timeout=5)
    if forwarded.returncode:
        return False
    try:
        device = frida_module.get_device_manager().add_remote_device(f'127.0.0.1:{FORWARD_PORT}')
        device.enumerate_processes()
        return True
    except Exception as error:
        transport_error = getattr(frida_module, 'TransportError', ())
        if transport_error and isinstance(error, transport_error):
            return False
        return False


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid4().hex)
    with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(value, stream, ensure_ascii=False)
    temporary.replace(path)


def scope(package):
    lab = current()
    if not lab.get('id') or not lab.get('apk_sha256') or package != lab.get('package_id'):
        raise ValueError('Selecione o app vinculado ao laboratório autorizado.')
    return lab


class DynamicRuntime:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = self.agent = self.device = None
        self.receipt = None
        self.events = []
        self.event_bytes = 0
        self.operation_lock = threading.Lock()
        self.preparing = False
        self.ready = threading.Event()

    def snapshot(self):
        with self.lock:
            receipt = self.receipt
            if receipt and receipt['lab_id'] != current().get('id'):
                receipt = None
            if receipt:
                return {'ok': True, 'state': receipt['state'], 'receipt': receipt, 'events': self.events[-250:]}
            try:
                saved = json.loads((root() / current()['id'] / 'dynamic.json').read_text())
                if saved.get('state') in {'running', 'starting'}:
                    saved['state'] = 'interrupted'
                if not re.fullmatch(r'dyn_[a-f0-9]{32}', saved.get('id', '')): raise ValueError('Invalid job')
                path = root() / current()['id'] / (saved['id'] + '.jsonl')
                events = [json.loads(line) for line in path.read_text().splitlines()[-250:]] if path.exists() else []
                return {'ok': True, 'state': saved['state'], 'receipt': saved, 'events': events}
            except (OSError, ValueError, KeyError):
                return {'ok': True, 'state': 'idle', 'events': []}

    def record(self, payload):
        with self.lock:
            if not self.receipt:
                return
            if time.time() - self.receipt.get('started_epoch', time.time()) > MAX_SESSION_SECONDS:
                self.receipt['dropped_event_count'] = self.receipt.get('dropped_event_count', 0) + 1
                return
            # Strict metadata schema. No arbitrary message strings, buffers or credentials.
            allowed = {'script', 'kind', 'class_name', 'method', 'overloads', 'scheme', 'hostname', 'algorithm', 'integrity_indicator', 'java_available', 'scripts', 'reason_code'}
            cleaned = {key: value for key, value in payload.items() if key in allowed and isinstance(value, (str, bool, int, list))}
            for key, value in list(cleaned.items()):
                if isinstance(value, str): cleaned[key] = value[:160]
            event = {'at': datetime.now(timezone.utc).isoformat(), 'job_id': self.receipt['id'], **redact(cleaned)}
            encoded = json.dumps(event, ensure_ascii=False).encode()
            if len(self.events) >= 4000 or self.event_bytes + len(encoded) > MAX_EVENT_BYTES:
                self.receipt['dropped_event_count'] = self.receipt.get('dropped_event_count', 0) + 1
                return
            self.events.append(event)
            self.event_bytes += len(encoded)
            folder = root() / self.receipt['lab_id']
            with os.fdopen(os.open(folder / (self.receipt['id'] + '.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), 'a') as output:
                output.write(encoded.decode() + '\n')
            if event.get('kind') == 'agent_ready': self.ready.set()

    def persist(self):
        folder = root() / self.receipt['lab_id']
        private_json(folder / 'dynamic.json', self.receipt)
        private_json(folder / (self.receipt['id'] + '.receipt.json'), self.receipt)

    def prepare(self):
        try:
            return self._prepare()
        except (OSError, ValueError, ImportError, lzma.LZMAError, subprocess.TimeoutExpired):
            return {'ok': False, 'reason': 'Frida não pôde ser preparado. Verifique dependências, acesso ao release oficial, SDK e versão do servidor.'}

    def _prepare(self):
        import frida
        worker = AndroidWorker()
        lab = scope(current().get('package_id'))
        if lab.get('root_mode', 'root') != 'root' or not worker.root_status().get('root_available'):
            return {'ok': False, 'reason': 'Sem root: use um build de teste do app com Frida Gadget integrado. Não alteramos o APK automaticamente.'}
        properties = worker.status().get('properties', {})
        abi = properties.get('ro.product.cpu.abi')
        arch = {'arm64-v8a': 'arm64', 'armeabi-v7a': 'arm', 'x86': 'x86', 'x86_64': 'x86_64'}.get(abi)
        if not arch: return {'ok': False, 'reason': 'Arquitetura Frida não suportada.'}
        version = frida.__version__
        if not re.fullmatch(r'\d+\.\d+\.\d+', version): raise ValueError('Invalid Frida version')
        compatibility = frida_compatibility(int(properties.get('ro.build.version.sdk', '0')), abi, version)
        if not compatibility['ok']:
            return {**compatibility, 'version': version, 'architecture': arch}
        folder = Path.home() / '.huntmob/runtime/frida' / version
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        binary = folder / ('frida-server-' + arch)
        if not binary.exists():
            url = f'https://github.com/frida/frida/releases/download/{version}/frida-server-{version}-android-{arch}.xz'
            with urllib.request.urlopen(url, timeout=45) as response:
                data = response.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024: raise ValueError('Frida asset too large')
            content = lzma.decompress(data)
            if len(content) > 200 * 1024 * 1024: raise ValueError('Frida binary too large')
            binary.write_bytes(content); binary.chmod(0o600)
            private_json(folder / 'receipt.json', {'version': version, 'arch': arch, 'source': url, 'sha256': hashlib.sha256(content).hexdigest()})
        provenance = json.loads((folder / 'receipt.json').read_text())
        if provenance.get('version') != version or provenance.get('arch') != arch or provenance.get('sha256') != hashlib.sha256(binary.read_bytes()).hexdigest():
            return {'ok': False, 'reason': 'Cache Frida com hash ou arquitetura divergente. Prepare o runtime novamente.'}
        command = (str(worker.sdk.adb), '-s', worker.serial)
        remote = '/data/local/tmp/huntmob-frida-server'
        if frida_server_ready(command, frida):
            check = _run(command + ('shell', remote, '--version'), timeout=5)
            if check.stdout.strip() == version:
                return {'ok': True, 'version': version, 'architecture': arch, 'transport': 'server'}
            return {'ok': False, 'reason': 'Outro servidor Frida está ativo. Reinicie o device para trocar a versão.'}
        for args in [('push', str(binary), remote), ('shell', 'chmod', '755', remote)]:
            result = _run(command + args, timeout=30)
            if result.returncode: return {'ok': False, 'reason': 'Não foi possível preparar o servidor Frida.'}
        checked = _run(command + ('shell', remote, '--version'), timeout=10)
        if checked.stdout.strip() != version: return {'ok': False, 'reason': 'Versão do servidor Frida diverge do cliente.'}
        # adb's shell service joins argv differently from a local shell. Keep
        # this constant command as one remote expression so `sh -c` receives
        # the daemon invocation instead of only the first token.
        launch_command = f"su 0 sh -c 'exec {remote} -D -l 127.0.0.1:27042 >/dev/null 2>&1 </dev/null'"
        launched = _run(command + ('shell', launch_command), timeout=10)
        if launched.returncode:
            return {'ok': False, 'reason': 'Servidor Frida não iniciou; outro worker pode estar usando a porta 27042.'}
        # `--daemonize` may return success even when the child crashes during startup.
        for _ in range(5):
            if frida_server_ready(command, frida):
                break
            time.sleep(0.2)
        else:
            return {'ok': False, 'reason': 'Servidor Frida encerrou após iniciar neste Android. Verifique a compatibilidade da versão no log do device.'}
        return {'ok': True, 'version': version, 'architecture': arch, 'transport': 'server', 'reason': 'Frida preparado no Android com root.'}

    def start(self, payload):
        if not self.operation_lock.acquire(blocking=False):
            return {'ok': False, 'reason': 'Uma operação Frida já está em andamento.'}
        try:
            try:
                result = self._start(payload)
            except (ValueError, ImportError, OSError, subprocess.TimeoutExpired) as error:
                return {'ok': False, 'reason': str(error) if isinstance(error, ValueError) else 'Worker Frida indisponível neste runtime.'}
            if result.get('ok') and not self.ready.wait(8):
                self.stop()
                with self.lock:
                    self.receipt['state'] = 'failed'; self.receipt['failure_phase'] = 'agent_ready'; self.receipt['error_type'] = 'AgentNotReady'; self.persist()
                return {'ok': False, 'reason': 'Agente Java não ficou pronto. Consulte os eventos da sessão.'}
            return result
        finally:
            self.operation_lock.release()

    def _start(self, payload):
        import frida
        with self.lock:
            if self.receipt and self.receipt['state'] in {'running', 'starting'}:
                return {'ok': False, 'reason': 'Pare a sessão atual antes de iniciar outra.'}
            package = payload.get('package_id')
            lab = scope(package)
            selected = payload.get('script_ids', [])
            if not isinstance(selected, list) or not selected or any(not isinstance(item, str) or item not in OBSERVERS for item in selected):
                return {'ok': False, 'reason': 'Selecione monitores de observação implementados.'}
            worker = AndroidWorker()
            if worker.status().get('state') != 'device': return {'ok': False, 'reason': 'Android offline.'}
            bridge_spec = __import__('importlib.util', fromlist=['find_spec']).find_spec('frida_tools')
            bridge = Path(bridge_spec.origin).parent / 'bridges/java.js' if bridge_spec else None
            if not bridge or not bridge.exists(): return {'ok': False, 'reason': 'Instale frida-tools para disponibilizar o Java bridge.'}
            command = (str(worker.sdk.adb), '-s', worker.serial)
            properties = worker.status().get('properties', {})
            root_mode = lab.get('root_mode', 'root')
            self.receipt = {'id': 'dyn_' + uuid4().hex, 'lab_id': lab['id'], 'package_id': package, 'apk_sha256': lab['apk_sha256'], 'scripts': selected, 'root_mode': root_mode, 'frida_version': frida.__version__, 'frida_transport': 'server' if root_mode == 'root' else 'gadget', 'android_api': int(properties.get('ro.build.version.sdk', '0')), 'android_abi': properties.get('ro.product.cpu.abi', ''), 'started_at': datetime.now(timezone.utc).isoformat(), 'started_epoch': time.time(), 'state': 'starting', 'phase': 'preflight', 'finding_status': 'not_assessed'}
            self.events = []; self.event_bytes = 0; self.ready.clear(); self.persist()
            if root_mode == 'root':
                result = self.prepare()
                if not result.get('ok'):
                    self.receipt['state'] = 'failed'; self.receipt['failure_phase'] = 'preflight'; self.receipt['error_type'] = result.get('error_code', 'FridaPrepareError'); self.persist()
                    return result
                self.receipt['frida_server_version'] = result['version']; self.persist()
            forwarded = _run(command + ('forward', f'tcp:{FORWARD_PORT}', 'tcp:27042'), timeout=10)
            if forwarded.returncode:
                self.receipt['state'] = 'failed'; self.receipt['failure_phase'] = 'forward'; self.receipt['error_type'] = 'AdbForwardError'; self.persist()
                return {'ok': False, 'reason': 'Forward Frida indisponível.'}
            pid = None
            spawned = False
            try:
                self.receipt['phase'] = 'connect'; self.persist()
                self.device = frida.get_device_manager().add_remote_device(f'127.0.0.1:{FORWARD_PORT}')
                if lab.get('root_mode', 'root') == 'stock' or payload.get('mode') == 'attach':
                    self.receipt['phase'] = 'attach_lookup'; self.persist()
                    found = _run(command + ('shell', 'pidof', package), timeout=5).stdout.split()
                    if not found: raise ValueError('App não está aberto. Abra o build instrumentado antes de conectar.')
                    pid = int(found[0])
                else:
                    self.receipt['phase'] = 'spawn'; self.persist()
                    pid = self.device.spawn([package]); spawned = True
                self.receipt['phase'] = 'attach'; self.persist()
                self.session = self.device.attach(pid)
                self.session.on('detached', lambda reason, crash: self.detached(reason))
                source = (Path(__file__).with_name('agents') / 'observe.js').read_text().replace('__SCRIPTS__', json.dumps(selected))
                self.agent = self.session.create_script(bridge.read_text() + '\nconst Java = bridge;\n' + source)
                self.agent.on('message', self.message)
                self.receipt['phase'] = 'agent_load'; self.persist()
                self.agent.load()
                if spawned: self.device.resume(pid)
                elif lab.get('root_mode') == 'stock':
                    try: self.device.resume(pid)
                    except frida.InvalidOperationError: pass
                self.receipt['pid'] = pid
                self.receipt['state'] = 'running'; self.receipt['phase'] = 'observe'; self.persist()
                return {'ok': True, 'receipt': self.receipt}
            except Exception as error:
                if spawned and pid:
                    try: self.device.resume(pid)
                    except Exception: pass
                if self.session:
                    try: self.session.detach()
                    except Exception: pass
                self.receipt['state'] = 'failed'; self.receipt['failure_phase'] = self.receipt.get('phase', 'unknown'); self.receipt['error_type'] = type(error).__name__; self.persist()
                return {'ok': False, 'reason': 'Frida não conectou ao app. Verifique root/servidor ou Gadget no perfil sem root.', 'error_type': type(error).__name__}

    def message(self, message, data):
        if message.get('type') == 'send' and isinstance(message.get('payload'), dict): self.record(message['payload'])
        elif message.get('type') == 'error': self.record({'kind': 'agent_error', 'reason_code': 'script_error'})

    def detached(self, reason):
        with self.lock:
            if self.receipt and self.receipt['state'] in {'running', 'starting'}:
                self.receipt['state'] = 'detached'; self.persist()
                self.record({'kind': 'detached', 'reason_code': str(reason)})

    def stop(self):
        with self.lock:
            if self.receipt and not self.receipt.get('ended_at'):
                previous = self.receipt['state']
                self.receipt['state'] = previous if previous in {'failed', 'detached', 'interrupted'} else 'stopped'
                self.receipt['event_count'] = len(self.events); self.receipt['ended_at'] = datetime.now(timezone.utc).isoformat(); self.receipt['ended_epoch'] = time.time(); self.persist()
            final_state = self.receipt.get('state', 'stopped') if self.receipt else 'stopped'
            agent, session = self.agent, self.session
            self.agent = self.session = None
        for obj, operation in ((agent, 'unload'), (session, 'detach')):
            if obj:
                try: getattr(obj, operation)()
                except Exception: pass
        return {'ok': True, 'state': final_state}

    def export(self):
        with self.lock:
            if not self.receipt or self.receipt['lab_id'] != current().get('id'):
                saved = self.snapshot()
                if not saved.get('receipt'): raise ValueError('Nenhuma sessão neste laboratório.')
                receipt = saved['receipt']
                event_file = root() / current()['id'] / (receipt['id'] + '.jsonl')
                events = [json.loads(line) for line in event_file.read_text().splitlines()] if event_file.exists() else []
            else:
                receipt, events = self.receipt, list(self.events)
            from .lab_sessions import network_store
            try: flows = visible_snapshot(network_store())['flows']
            except (OSError, ValueError): flows = []
            flows = [flow for flow in flows if receipt.get('started_epoch', 0) <= flow.get('started_at', 0) <= receipt.get('ended_epoch', time.time())]
            from .evidence import EvidenceStore
            screenshots = [item for item in EvidenceStore().inventory().get('records', []) if item.get('lab_id') == receipt['lab_id'] and receipt['started_at'] <= item.get('created_at', '') <= receipt.get('ended_at', datetime.now(timezone.utc).isoformat())]
            payload = {'version': 1, 'receipt': receipt, 'events': events, 'network': flows, 'screenshots': screenshots, 'finding_status': 'not_assessed'}
            return json.dumps(payload, ensure_ascii=False, indent=2).encode()


DYNAMIC = DynamicRuntime()
