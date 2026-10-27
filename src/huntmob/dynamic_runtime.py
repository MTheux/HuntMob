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


def frida_server_ready(command, frida_module, forward_port=FORWARD_PORT):
    """Probe the Frida protocol; Android's pidof may hide long process names."""
    forwarded = _run(command + ('forward', f'tcp:{forward_port}', 'tcp:27042'), timeout=5)
    if forwarded.returncode:
        return False
    try:
        device = frida_module.get_device_manager().add_remote_device(f'127.0.0.1:{forward_port}')
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


def target_context(workspace_id=None, device_id=None):
    lab = current()
    if workspace_id is None and device_id is None:
        return lab
    if not workspace_id or not device_id or lab.get('id') != workspace_id:
        raise ValueError('Workspace selecionado mudou.')
    if device_id == workspace_id:
        return lab
    from .workspace_devices import owned
    record = owned(workspace_id, device_id)
    if record.get('platform') != 'android' or record.get('link', {}).get('kind') != 'root-companion':
        raise ValueError('Selecione um companheiro Android vinculado a este lab.')
    # A failed/replaced synchronization cannot reuse the original device's evidence identity.
    matched = all(record.get(key) and record.get(key) == lab.get(key) for key in ('package_id', 'apk_sha256'))
    return {**record, 'package_id': record.get('package_id') if matched else None,
            'apk_sha256': record.get('apk_sha256') if matched else None, 'engagement': lab.get('engagement')}


def target_worker(lab):
    if lab.get('workspace_id'):
        from .workspace_devices import owned, worker
        return worker(owned(lab['workspace_id'], lab['id']))
    return AndroidWorker()


def scope(package, workspace_id=None, device_id=None):
    lab = target_context(workspace_id, device_id)
    if not lab.get('id') or not lab.get('apk_sha256') or package != lab.get('package_id'):
        raise ValueError('Selecione o app vinculado ao laboratório autorizado.')
    return lab


def connection_readiness(workspace_id=None, device_id=None):
    """Read owned-lab prerequisites without preparing root or attaching to an app."""
    lab=target_context(workspace_id, device_id)
    result={'ok':True,'ready':False,'lab_id':lab.get('id'),'package_id':lab.get('package_id'),
            'apk_sha256':lab.get('apk_sha256'),'root_mode':lab.get('root_mode'),
            'transport':'gadget' if lab.get('root_mode')=='stock' else 'server'}
    def blocked(code, reason):
        return {**result,'error_code':code,'reason':reason}
    if not lab.get('id') or not lab.get('package_id') or not lab.get('apk_sha256'):
        return blocked('selected_app_required','Selecione o aplicativo e identifique o APK antes de verificar o Frida.')
    if lab.get('workspace_id') and lab.get('link', {}).get('state') not in {'ready', 'partial'}:
        return blocked('pair_sync_pending', 'Conclua a sincronização do companheiro antes de iniciar o DAST.')
    try:
        import frida
        worker=target_worker(lab)
        if worker.avd_name!=lab['id']:
            return blocked('lab_changed','O laboratório selecionado mudou. Atualize a conexão.')
        status=worker.status()
        if status.get('state')!='device' or status.get('ownership_verified') is False:
            return blocked('android_offline','O Android principal não está online e identificado.')
        command=(str(worker.sdk.adb),'-s',worker.serial)
        if lab.get('root_mode')=='stock':
            running=_run(command+('shell','pidof',lab['package_id']),timeout=5)
            if running.returncode or not running.stdout.split():
                return blocked('gadget_app_not_running','Abra o build de teste com Frida Gadget no Android e clique em Verificar Frida.')
            ports=_run(command+('shell','ss','-ltn'),timeout=5)
            if ports.returncode:
                return blocked('gadget_check_unavailable','Não foi possível verificar a porta do Gadget neste Android. Nenhuma conexão foi iniciada.')
            listening=any(len(fields)>=4 and fields[0]=='LISTEN' and fields[3].rsplit(':',1)[-1]=='27042'
                          for fields in (line.split() for line in ports.stdout.splitlines()))
            if not listening:
                return blocked('gadget_not_listening','Google Play sem root: o app está aberto, mas não há canal Frida na porta 27042. Use um build de teste com Frida Gadget carregado e clique em Verificar Frida. Root apps/Magisk não está disponível nesta imagem.')
            reason='Porta do Gadget disponível. A identidade do processo e a conexão serão verificadas ao iniciar a sessão.'
        else:
            properties=status.get('properties',{})
            compatible=frida_compatibility(int(properties.get('ro.build.version.sdk','0')),properties.get('ro.product.cpu.abi',''),frida.__version__)
            if not compatible['ok']:
                return blocked(compatible['error_code'],compatible['reason'])
            if not worker.root_status().get('root_available'):
                return blocked('adb_root_unavailable','O servidor Frida precisa de ADB root no perfil AOSP. Root para apps/Magisk é um controle separado.')
            reason='ADB root disponível para preparar o servidor Frida. Magisk para apps não é necessário para esta conexão.'
        fresh=target_context(workspace_id, device_id)
        if any(fresh.get(key)!=lab.get(key) for key in ('id','package_id','apk_sha256')):
            return blocked('lab_changed','O app ou laboratório mudou durante a verificação. Verifique novamente.')
        return {**result,'ready':True,'error_code':'','reason':reason}
    except ImportError:
        return blocked('frida_missing','Frida não está instalado no worker local.')
    except (OSError,ValueError,subprocess.TimeoutExpired):
        return blocked('frida_check_failed','Não foi possível verificar o Frida. Confira a conexão do Android e tente novamente.')


class DynamicRuntime:
    def __init__(self, workspace_id=None, device_id=None, forward_port=FORWARD_PORT):
        self.workspace_id, self.device_id, self.forward_port = workspace_id, device_id, forward_port
        self.lock = threading.RLock()
        self.session = self.agent = self.device = None
        self.receipt = None
        self.events = []
        self.event_bytes = 0
        self.operation_lock = threading.Lock()
        self.preparing = False
        self.ready = threading.Event()

    def context(self):
        return target_context(self.workspace_id, self.device_id)

    def scoped_lab(self, package):
        return scope(package, self.workspace_id, self.device_id)

    def readiness(self):
        return connection_readiness(self.workspace_id, self.device_id)

    def snapshot(self):
        with self.lock:
            receipt = self.receipt
            if receipt and receipt['lab_id'] != self.context().get('id'):
                receipt = None
            if receipt:
                return {'ok': True, 'state': receipt['state'], 'receipt': receipt, 'events': self.events[-250:]}
            try:
                saved = json.loads((root() / self.context()['id'] / 'dynamic.json').read_text())
                if saved.get('state') in {'running', 'starting'}:
                    saved['state'] = 'interrupted'
                if not re.fullmatch(r'dyn_[a-f0-9]{32}', saved.get('id', '')): raise ValueError('Invalid job')
                path = root() / self.context()['id'] / (saved['id'] + '.jsonl')
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
        lab = self.scoped_lab(self.context().get('package_id'))
        worker = target_worker(lab)
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
        if frida_server_ready(command, frida, self.forward_port):
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
            if frida_server_ready(command, frida, self.forward_port):
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
            lab = self.scoped_lab(package)
            if lab.get('workspace_id'):
                from .workspace_pairs import apk_paths, remote_digest
                worker = target_worker(lab)
                files = apk_paths(worker, package)
                recorded = next((a for a in lab.get('link', {}).get('apps', []) if a.get('package_id') == package and a.get('state') == 'verified'), {})
                if sorted(remote_digest(worker, path) for path in files) != sorted(item['sha256'] for item in recorded.get('files', [])):
                    return {'ok': False, 'reason': 'APKs do companheiro mudaram. Sincronize o par novamente.'}
            selected = payload.get('script_ids', [])
            if not isinstance(selected, list) or not selected or any(not isinstance(item, str) or item not in OBSERVERS for item in selected):
                return {'ok': False, 'reason': 'Selecione monitores de observação implementados.'}
            readiness=self.readiness()
            if not readiness['ready']:
                return {**readiness,'ok':False,'blocked':True}
            if any(readiness.get(key)!=lab.get(key) for key in ('package_id','apk_sha256')) or readiness.get('lab_id')!=lab['id']:
                return {'ok':False,'blocked':True,'error_code':'lab_changed','reason':'O app ou laboratório mudou. Verifique a conexão novamente.'}
            worker = target_worker(lab)
            if worker.status().get('state') != 'device': return {'ok': False, 'reason': 'Android offline.'}
            bridge_spec = __import__('importlib.util', fromlist=['find_spec']).find_spec('frida_tools')
            bridge = Path(bridge_spec.origin).parent / 'bridges/java.js' if bridge_spec else None
            if not bridge or not bridge.exists(): return {'ok': False, 'reason': 'Instale frida-tools para disponibilizar o Java bridge.'}
            command = (str(worker.sdk.adb), '-s', worker.serial)
            properties = worker.status().get('properties', {})
            root_mode = lab.get('root_mode', 'root')
            self.receipt = {'id': 'dyn_' + uuid4().hex, 'lab_id': lab['id'], 'package_id': package, 'apk_sha256': lab['apk_sha256'], 'scripts': selected, 'root_mode': root_mode, 'frida_version': frida.__version__, 'frida_transport': 'server' if root_mode == 'root' else 'gadget', 'android_api': int(properties.get('ro.build.version.sdk', '0')), 'android_abi': properties.get('ro.product.cpu.abi', ''), 'started_at': datetime.now(timezone.utc).isoformat(), 'started_epoch': time.time(), 'state': 'starting', 'phase': 'preflight', 'finding_status': 'not_assessed'}
            self.receipt.update({'workspace_id': lab.get('workspace_id', lab['id']), 'device_id': lab['id'], 'serial': worker.serial})
            self.events = []; self.event_bytes = 0; self.ready.clear(); self.persist()
            if root_mode == 'root':
                result = self.prepare()
                if not result.get('ok'):
                    self.receipt['state'] = 'failed'; self.receipt['failure_phase'] = 'preflight'; self.receipt['error_type'] = result.get('error_code', 'FridaPrepareError'); self.persist()
                    return result
                self.receipt['frida_server_version'] = result['version']; self.persist()
            forwarded = _run(command + ('forward', f'tcp:{self.forward_port}', 'tcp:27042'), timeout=10)
            if forwarded.returncode:
                self.receipt['state'] = 'failed'; self.receipt['failure_phase'] = 'forward'; self.receipt['error_type'] = 'AdbForwardError'; self.persist()
                return {'ok': False, 'reason': 'Forward Frida indisponível.'}
            pid = None
            spawned = False
            try:
                self.receipt['phase'] = 'connect'; self.persist()
                self.device = frida.get_device_manager().add_remote_device(f'127.0.0.1:{self.forward_port}')
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
                self.receipt['state'] = 'failed'; self.receipt['failure_phase'] = self.receipt.get('phase', 'unknown'); self.receipt['error_type'] = type(error).__name__
                reason=('O canal Frida Gadget não confirmou a conexão com este app. Verifique se o Gadget está carregado no build de teste aberto; Magisk não é compatível com esta imagem Google Play.'
                        if root_mode=='stock' else 'O servidor Frida não confirmou a conexão. Verifique ADB root, versão do servidor e compatibilidade do runtime; Magisk para apps é um controle separado.')
                self.receipt['failure_reason']=reason;self.persist()
                return {'ok': False, 'reason': reason, 'error_code':'gadget_connection_failed' if root_mode=='stock' else 'frida_connection_failed','error_type': type(error).__name__}

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
            if not self.receipt or self.receipt['lab_id'] != self.context().get('id'):
                saved = self.snapshot()
                if not saved.get('receipt'): raise ValueError('Nenhuma sessão neste laboratório.')
                receipt = saved['receipt']
                event_file = root() / self.context()['id'] / (receipt['id'] + '.jsonl')
                events = [json.loads(line) for line in event_file.read_text().splitlines()] if event_file.exists() else []
            else:
                receipt, events = self.receipt, list(self.events)
            from .lab_sessions import network_store
            try: flows = visible_snapshot(network_store())['flows'] if not self.workspace_id else []
            except (OSError, ValueError): flows = []
            flows = [flow for flow in flows if receipt.get('started_epoch', 0) <= flow.get('started_at', 0) <= receipt.get('ended_epoch', time.time())]
            from .evidence import EvidenceStore
            screenshots = [item for item in EvidenceStore().inventory().get('records', []) if item.get('lab_id') == receipt['lab_id'] and receipt['started_at'] <= item.get('created_at', '') <= receipt.get('ended_at', datetime.now(timezone.utc).isoformat())]
            payload = {'version': 1, 'receipt': receipt, 'events': events, 'network': flows, 'screenshots': screenshots, 'finding_status': 'not_assessed', 'limitations': ['Captura de proxy do principal excluída: rede do companheiro não atribuída.'] if self.workspace_id else []}
            return json.dumps(payload, ensure_ascii=False, indent=2).encode()


DYNAMIC = DynamicRuntime()
RUNTIMES = {}
RUNTIME_LOCK = threading.Lock()


def runtime_for(workspace_id=None, device_id=None):
    lab = target_context(workspace_id, device_id)
    if not lab.get('workspace_id'):
        return DYNAMIC
    key = (workspace_id, device_id)
    with RUNTIME_LOCK:
        if key not in RUNTIMES:
            RUNTIMES[key] = DynamicRuntime(workspace_id, device_id, 29000 + lab['port'])
        return RUNTIMES[key]


def stop_device(device_id):
    with RUNTIME_LOCK:
        values = [value for (_, identifier), value in RUNTIMES.items() if identifier == device_id]
    for value in values:
        value.stop()


def stop_workspace(workspace_id):
    with RUNTIME_LOCK:
        values = [value for (owner, _), value in RUNTIMES.items() if owner == workspace_id]
    for value in values:
        value.stop()


def shutdown_companions():
    with RUNTIME_LOCK:
        values = list(RUNTIMES.values())
    for value in values:
        value.stop()
