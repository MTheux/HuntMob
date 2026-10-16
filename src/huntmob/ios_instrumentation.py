"""Fixed read-only Frida probe, scoped to the installed authorized Simulator app."""
import hashlib
import threading
from datetime import datetime, timezone
from uuid import uuid4
from . import ios_worker

PROBE = "send({kind:'native-metadata',arch:Process.arch,module_count:Process.enumerateModules().length});"
LOCK = threading.Lock()


def inspect_native():
    if not LOCK.acquire(blocking=False):
        raise ValueError('Inspeção Frida iOS já em andamento.')
    ios_worker.IOS_LOCK.acquire()
    session = agent = timer = None
    spawned = False
    pid = None
    device = None
    try:
        import frida
        record=ios_worker.owned()
        package=record.get('package_id');digest=record.get('binary_sha256')
        if not package or not digest:
            raise ValueError('Instale e abra um app autorizado neste lab antes de usar Frida.')
        app_path=ios_worker.sim('get_app_container',record['udid'],package,'app',timeout=8)
        if app_path.returncode: raise ValueError('App selecionado não está instalado no lab.')
        from pathlib import Path
        import plistlib
        bundle=Path(app_path.stdout.strip())
        info=plistlib.loads((bundle/'Info.plist').read_bytes())
        name=info.get('CFBundleExecutable')
        if not isinstance(name,str) or '/' in name or '\\' in name or name in {'.','..'}:
            raise ValueError('Executável iOS inválido.')
        if _digest(bundle/name)!=digest:
            raise ValueError('Binário instalado mudou; selecione novamente o app autorizado.')
        cancellable=frida.Cancellable()
        timer=threading.Timer(12,cancellable.cancel);timer.daemon=True;timer.start()
        events=[];ready=threading.Event()
        with cancellable:
            # Never use USB, a host process PID, or an arbitrary remote endpoint.
            device=next((d for d in frida.enumerate_devices() if d.id==record['udid'] and d.type=='remote'),None)
            if device is None: raise ValueError('Frida Simmy não encontrou o Simulator selecionado.')
            app=next((a for a in device.enumerate_applications() if a.identifier==package),None)
            if app is None: raise ValueError('Frida não identificou o app selecionado.')
            pid=app.pid
            if not pid: pid=device.spawn(package);spawned=True
            session=device.attach(pid)
            agent=session.create_script(PROBE)
            def message(value,_data):
                payload=value.get('payload')
                if value.get('type')=='send' and isinstance(payload,dict) and payload.get('kind')=='native-metadata':
                    count=payload.get('module_count');arch=payload.get('arch')
                    if type(count) is int and 0<=count<=10000 and arch in {'arm64','x64','ia32','arm'}:
                        events.append({'kind':'native-metadata','arch':arch,'module_count':count});ready.set()
            agent.on('message',message);agent.load()
            if spawned: device.resume(pid);spawned=False
            if not ready.wait(5): raise ValueError('Frida conectou, mas a sonda não retornou evidência.')
        receipt={'id':uuid4().hex,'at':datetime.now(timezone.utc).isoformat(),'provider':'frida-simmy',
                 'runtime':'apple-simulator','package_id':package,'binary_sha256':digest,
                 'frida_version':frida.__version__,'events':events,'jailbreak':False,
                 'finding_created':False,'scope':'fixed-read-only-probe'}
        ios_worker.private_json(ios_worker.folder()/('frida-'+receipt['id']+'.json'),receipt)
        return {'ok':True,'receipt':receipt}
    except ImportError as error:
        raise ValueError('Frida com suporte Simmy não está instalado no worker.') from error
    finally:
        if timer: timer.cancel()
        if agent:
            try: agent.unload()
            except Exception: pass
        if session:
            try: session.detach()
            except Exception: pass
        if spawned and device and pid:
            try: device.resume(pid)
            except Exception: pass
        ios_worker.IOS_LOCK.release()
        LOCK.release()


def _digest(path):
    digest=hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
