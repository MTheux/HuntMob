"""Project-owned Apple Simulator lab; never claims support for physical-device IPAs."""
import hashlib
import json
import math
import os
import platform
import re
import plistlib
import select
import shutil
import stat
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from .android_worker import _run, PACKAGE_ID
from .dynamic_runtime import private_json
from .screen_relay import ScreenRelay

IOS_LOCK=threading.RLock()
COMPANION=None
INPUT_BRIDGE=None
INPUT_UDID=None


def folder(): return Path.home()/'.huntmob/ios'
def client_path():
    return Path(__file__).resolve().parents[2]/'components/idb-client/.venv/bin/idb'
def saved():
    try: return json.loads((folder()/'current.json').read_text())
    except (OSError,ValueError): return {}
def sim(*args,timeout=30): return _run(('xcrun','simctl',*args),timeout=timeout)

def inventory():
    if platform.system()!='Darwin': return {'ok':True,'ready':False,'state':'unavailable','reason':'iOS Simulator requer um worker macOS com Xcode.'}
    try:
        runtimes=json.loads(sim('list','runtimes','--json',timeout=8).stdout).get('runtimes',[])
        runtimes=[r for r in runtimes if r.get('isAvailable') and r.get('platform')=='iOS']
        record=saved();devices=json.loads(sim('list','devices','--json',timeout=8).stdout).get('devices',{})
        device=next((d for group in devices.values() for d in group if d.get('udid')==record.get('udid') and d.get('name','').startswith('HuntMob iOS')),None)
        return {'ok':True,'ready':bool(runtimes),'state':'on' if device and device['state']=='Booted' else 'off','device':device,'lab':record,'runtimes':[{'name':r['name'],'id':r['identifier']} for r in runtimes],'input_ready':client_path().is_file() and bool(shutil.which('idb_companion')),'limitations':['Build .app para Simulator; IPA de iPhone físico não é compatível.','Frida, DAST Android e root não são oferecidos neste perfil iOS.']}
    except (OSError,ValueError,subprocess.TimeoutExpired): return {'ok':False,'ready':False,'state':'unavailable','reason':'Inventário Apple indisponível. Verifique Xcode e CoreSimulator.'}

def owned():
    info=inventory()
    if info.get('state')!='on' or not info.get('device'): raise ValueError('Simulator HuntMob não está ligado.')
    return info['lab']

def bridge_path(record):
    return folder() / ('bridge-' + record['udid'] + '.sock')

def ensure_companion(record, *, primary=True):
    global COMPANION
    if not client_path().is_file() or not shutil.which('idb_companion'): raise ValueError('Bridge iOS local ausente. Prepare idb-companion e o cliente do HuntMob.')
    folder().mkdir(parents=True,exist_ok=True);folder().chmod(0o700)
    socket_path=bridge_path(record)
    # Validate a surviving local companion before reusing it after server restart.
    if socket_path.exists():
        probe=_run((str(client_path()),'--companion',str(socket_path),'describe','--json'),timeout=8)
        if probe.returncode==0 and json.loads(probe.stdout).get('udid')==record['udid']: return
        if probe.returncode and 'Connection refused' in probe.stderr and stat.S_ISSOCK(socket_path.lstat().st_mode) and socket_path.lstat().st_uid==os.getuid():
            socket_path.unlink()
        else:
            raise ValueError('Bridge local não corresponde ao Simulator selecionado. Reinicie o worker iOS.')
    process=subprocess.Popen(('idb_companion','--udid',record['udid'],'--grpc-domain-sock',str(socket_path),'--log-level','warning','--log-hid-details','false'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if primary: COMPANION=process
    deadline=time.monotonic()+15
    while not socket_path.exists():
        if process.poll() is not None or time.monotonic()>deadline: raise ValueError('Bridge iOS não iniciou.')
        time.sleep(.1)
    return process

def lab_catalog():
    info = inventory()
    if not info.get('ready'): return {'ok':True, 'runtimes':[], 'models':[], 'reason':info.get('reason','Runtime iOS ausente.')}
    result=sim('list','devicetypes','--json',timeout=8)
    if result.returncode: raise ValueError('Catálogo de modelos iOS indisponível.')
    models=[{'id':d['identifier'],'name':d['name'],'minimum':d.get('minRuntimeVersion',0),'maximum':d.get('maxRuntimeVersion',4294967295)} for d in json.loads(result.stdout).get('devicetypes',[]) if d.get('productFamily')=='iPhone']
    return {'ok':True,'runtimes':info['runtimes'],'models':models,'jailbreak_supported':False}


def new_lab(runtime, model, access='stock', engagement=''):
    from .lab_sessions import engagement_name
    engagement=engagement_name(engagement)
    # Validate before touching the existing lab. No jailbreak is synthesized.
    if access!='stock': raise ValueError('Não há runtime iOS com jailbreak validado neste worker.')
    catalog=lab_catalog()
    if runtime not in {r['id'] for r in catalog['runtimes']} or model not in {m['id'] for m in catalog['models']}:
        raise ValueError('Selecione versão e modelo disponíveis no worker.')
    version=re.search(r'iOS-(\d+)-(\d+)(?:-(\d+))?$',runtime)
    selected=next(m for m in catalog['models'] if m['id']==model)
    number=int(version[1])*65536+int(version[2])*256+int(version[3] or 0) if version else -1
    if not selected.get('minimum',0)<=number<=selected.get('maximum',4294967295):
        raise ValueError('Modelo incompatível com esta versão iOS; lab atual preservado.')
    with IOS_LOCK:
        name='HuntMob iOS Lab '+str(time.time_ns())
        created=sim('create',name,model,runtime)
        if created.returncode: raise ValueError('Modelo incompatível com a versão selecionada; lab atual preservado.')
        record={'udid':created.stdout.strip(),'name':name,'runtime':runtime,'model':model,'platform':'ios','access':'stock','engagement':engagement}
        previous=inventory()
        if previous.get('device'):
            private_json(folder()/('lab-'+previous['lab']['udid']+'.json'),previous['lab'])
        if previous.get('state')=='on': shutdown()
        private_json(folder()/('lab-'+record['udid']+'.json'),record)
        private_json(folder()/'current.json',record)
        return start()


def device_control(payload):
    with IOS_LOCK:
        return _device_control(payload)


def _device_control(payload, record=None):
    record=record or owned();action=payload.get('action')
    if action=='location':
        latitude=float(payload.get('latitude'));longitude=float(payload.get('longitude'))
        if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90<=latitude<=90 or not -180<=longitude<=180:
            raise ValueError('Coordenadas GPS inválidas.')
        result=sim('location',record['udid'],'set',f'{latitude},{longitude}',timeout=8)
        reason='GPS simulado aplicado ao iOS; o app precisa de permissão de localização.'
    elif action=='battery':
        level=float(payload.get('level'))
        if not math.isfinite(level) or not 0<=level<=100: raise ValueError('Carga inválida.')
        result=sim('status_bar',record['udid'],'override','--batteryLevel',str(int(level)),timeout=8)
        reason='Indicador de bateria alterado; não modifica a carga real nem APIs de energia.'
    elif action=='battery-reset':
        result=sim('status_bar',record['udid'],'clear',timeout=8);reason='Indicadores da barra de status restaurados.'
    elif action=='biometric':
        mode=payload.get('mode')
        kind={'face':'pearl','touch':'fingerTouch'}.get(payload.get('kind','face'))
        if not kind or mode not in {'enroll','unenroll','match','no-match'}:
            raise ValueError('Evento biométrico inválido.')
        enrollment='com.apple.BiometricKit.enrollmentChanged'
        if mode in {'enroll','unenroll'}:
            value='1' if mode=='enroll' else '0'
            result=sim('spawn',record['udid'],'notifyutil','-s',enrollment,value,timeout=8)
            if result.returncode: raise ValueError('O Simulator recusou o cadastro biométrico de teste.')
            result=sim('spawn',record['udid'],'notifyutil','-p',enrollment,timeout=8)
            reason='Cadastro biométrico simulado atualizado; nenhum dado biométrico real foi usado.'
        else:
            notification='com.apple.BiometricKit_Sim.'+kind+'.'+('match' if mode=='match' else 'nomatch')
            result=sim('spawn',record['udid'],'notifyutil','-p',notification,timeout=8)
            reason='Evento biométrico de teste enviado; o app precisa estar mostrando o prompt correspondente.'
    elif action=='rotation':
        orientation=payload.get('orientation')
        if orientation not in {'portrait','landscape'}: raise ValueError('Orientação inválida.')
        node=shutil.which('node')
        helper=Path(__file__).resolve().parents[2]/'components/ios-controls/control.mjs'
        if not node or not helper.is_file(): raise ValueError('Driver de orientação iOS não está instalado.')
        result=_run((node,str(helper),record['udid'],'rotation',orientation),timeout=8)
        data=json.loads(result.stdout)
        if result.returncode or not data.get('ok'): raise ValueError('O runtime recusou a orientação.')
        return {'ok':True,'reason':'Orientação confirmada no iOS.' if data.get('readback_matches') else 'Evento de orientação enviado; a tela manteve a orientação anterior. O app pode ter orientação fixa.','readback':data}
    elif action in {'home','recents','lock'}:return input_action({'action':action})
    else:raise ValueError('Este controle não é oferecido pelo runtime iOS atual.')
    return {'ok':result.returncode==0,'reason':reason if result.returncode==0 else 'O Simulator recusou o controle.'}


def start():
    with IOS_LOCK:
        if IOS_RELAY.closing.is_set(): IOS_RELAY.restart()
        info=inventory()
        if not info.get('ready'): raise ValueError(info.get('reason','Instale um runtime iOS no Xcode.'))
        record=info['lab']
        if not info.get('device'):
            if record or (folder()/'current.json').exists():
                raise ValueError('Simulator salvo não foi encontrado. A identidade foi preservada; nenhum novo dispositivo foi criado. Restaure o Simulator ou crie outro explicitamente em Novo lab.')
            runtime=info['runtimes'][-1]['id']
            created=sim('create','HuntMob iOS Lab','com.apple.CoreSimulator.SimDeviceType.iPhone-16-Pro',runtime)
            if created.returncode: raise ValueError('Não foi possível criar o Simulator HuntMob.')
            record={'udid':created.stdout.strip(),'name':'HuntMob iOS Lab','runtime':runtime,'platform':'ios'}
            private_json(folder()/'current.json',record)
        if info.get('state')!='on':
            if sim('boot',record['udid']).returncode: raise ValueError('Simulator não iniciou.')
        if sim('bootstatus',record['udid'],'-b',timeout=180).returncode: raise ValueError('Boot do Simulator não terminou.')
        ensure_companion(record)
        bundle = record.get('package_id')
        if bundle and PACKAGE_ID.fullmatch(bundle):
            if sim('launch',record['udid'],bundle,timeout=20).returncode:
                raise ValueError('Simulator ligado, mas o app salvo não abriu. Reinstale um build compatível.')
        return {'ok':True,**inventory()}

def app_metadata(app):
    info=plistlib.loads((app/'Info.plist').read_bytes());bundle=info.get('CFBundleIdentifier','');name=info.get('CFBundleExecutable','')
    if not isinstance(bundle,str) or not PACKAGE_ID.fullmatch(bundle) or not isinstance(name,str) or '/' in name or name in {'','..','.'}: raise ValueError('App sem Bundle ID ou executável válido.')
    binary=app/name
    if not binary.is_file() or binary.is_symlink(): raise ValueError('Executável do app ausente.')
    result=_run(('xcrun','vtool','-show-build',str(binary)),timeout=10)
    if result.returncode or 'IOSSIMULATOR' not in result.stdout: raise ValueError('Este build não é de Simulator. Solicite um .app compilado para iOS Simulator; IPA de device físico não funciona aqui.')
    binary.chmod(binary.stat().st_mode|0o111)
    return bundle,hashlib.sha256(binary.read_bytes()).hexdigest()

def install_app(app):
    with IOS_LOCK:
        record=owned();bundle,digest=app_metadata(app)
        if sim('install',record['udid'],str(app),timeout=90).returncode: raise ValueError('Instalação recusada pelo Simulator; verifique arquitetura e build.')
        if sim('launch',record['udid'],bundle,timeout=30).returncode: raise ValueError('App instalado, mas não abriu. Consulte o build do Simulator.')
        record.update(package_id=bundle,binary_sha256=digest);private_json(folder()/'current.json',record)
        return {'ok':True,'installed':True,'launched':True,'lab':record}

def install_zip(archive):
    if not zipfile.is_zipfile(archive):
        raise ValueError('Arquivo não é um ZIP válido. Envie um .app compilado para iOS Simulator, compactado em ZIP.')
    with tempfile.TemporaryDirectory(prefix='huntmob-ios-') as tmp:
        base=Path(tmp)
        with zipfile.ZipFile(archive) as zip_file:
            items=zip_file.infolist()
            if any(PurePosixPath(i.filename).parts[:1] == ('Payload',) for i in items):
                raise ValueError('Este arquivo tem estrutura de IPA para iPhone físico. O Simulator exige um build .app para iOS Simulator em ZIP; renomear o IPA não converte o binário.')
            if len(items)>20000 or sum(i.file_size for i in items)>1024*1024*1024: raise ValueError('Arquivo iOS excede limite de extração.')
            for item in items:
                name=PurePosixPath(item.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in item.filename or stat.S_ISLNK(item.external_attr>>16): raise ValueError('Caminho ou link inseguro no arquivo iOS.')
            zip_file.extractall(base)
        apps=[p for p in base.rglob('*.app') if not any(part.endswith('.app') for part in p.relative_to(base).parts[:-1])]
        if len(apps)!=1: raise ValueError('Envie um ZIP contendo exatamente um .app para Simulator.')
        return install_app(apps[0])

def fixture():
    app=Path(__file__).resolve().parents[2]/'components/ios-lab/HuntMobLab.app'
    if not app.is_dir(): raise ValueError('Fixture ainda não compilada. Execute scripts/build_ios_fixture.py no Mac worker.')
    return install_app(app)

def capture_image():
    with IOS_LOCK:
        record=owned()
        # Xcode 27 writes a literal '-' file despite its stdout help text.
        # A private temporary PNG works consistently across simctl versions.
        with tempfile.TemporaryDirectory(prefix='huntmob-ios-capture-') as directory:
            image=Path(directory)/'screen.png'
            result=sim('io',record['udid'],'screenshot','--type=png',str(image),timeout=15)
            if result.returncode or not image.is_file(): raise ValueError('Screenshot iOS não disponível.')
            content=image.read_bytes()
            if not content.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('Screenshot iOS não é PNG válido.')
            return record,content

def input_action(payload):
    global INPUT_BRIDGE, INPUT_UDID
    with IOS_LOCK:
        record=saved()
        if not record.get('udid'): raise ValueError('Selecione o Simulator HuntMob.')
        action=payload.get('action')
        clean={'action':action}
        if action=='touch':
            if payload.get('udid')!=record['udid']:
                raise ValueError('O Simulator selecionado mudou. Atualize a tela antes de interagir.')
            if payload.get('phase') not in {'down','move','up','cancel'}:
                raise ValueError('Fase de toque inválida.')
            clean['phase']=payload['phase']
        if action in {'tap','swipe','touch'}:
            keys=('x','y') if action in {'tap','touch'} else ('x','y','end_x','end_y')
            for key in keys:
                value=float(payload[key])
                if not math.isfinite(value) or not 0<=value<=1: raise ValueError('Coordenadas inválidas.')
                clean[key]=value
        elif action=='key':
            if payload.get('key') not in {'Backspace','Enter','Tab','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'}: raise ValueError('Tecla inválida.')
            clean['key']=payload['key']
        elif action=='text':
            text=payload.get('text','')
            if not isinstance(text,str) or not text or len(text)>256 or not all(32<=ord(c)<127 for c in text): raise ValueError('Texto ASCII inválido.')
            clean['text']=text
        elif action not in {'home','recents','lock'}: raise ValueError('Controle indisponível no iOS.')
        if INPUT_BRIDGE and INPUT_UDID != record['udid']:
            close_input_bridge()
        if not INPUT_BRIDGE or INPUT_BRIDGE.poll() is not None:
            record=owned();ensure_companion(record)
            python=client_path().with_name('python3')
            INPUT_BRIDGE=subprocess.Popen((str(python),str(Path(__file__).with_name('ios_input_bridge.py')),str(bridge_path(record)),record['udid']),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
            if not select.select([INPUT_BRIDGE.stdout],[],[],8)[0] or not json.loads(INPUT_BRIDGE.stdout.readline()).get('ready'):
                INPUT_BRIDGE.terminate();INPUT_BRIDGE=None;raise ValueError('Canal iOS de input não iniciou.')
        INPUT_UDID=record['udid']
        INPUT_BRIDGE.stdin.write(json.dumps(clean)+'\n');INPUT_BRIDGE.stdin.flush()
        if not select.select([INPUT_BRIDGE.stdout],[],[],5)[0]:
            INPUT_BRIDGE.terminate();INPUT_BRIDGE=None;raise ValueError('Input iOS excedeu o tempo de resposta.')
        return json.loads(INPUT_BRIDGE.stdout.readline())

def shutdown():
    global COMPANION, INPUT_BRIDGE, INPUT_UDID
    IOS_RELAY.shutdown()
    close_input_bridge()
    with IOS_LOCK:
        record=owned()
        result=sim('shutdown',record['udid'])
        if COMPANION:
            COMPANION.terminate();COMPANION.wait(3);COMPANION=None
        return {'ok':result.returncode==0}

def latest_jpeg(buffer):
    """Consume completed frames, publishing only the newest from a pipe batch."""
    newest = None
    while True:
        start = buffer.find(b'\xff\xd8')
        if start < 0:
            # Preserve a split SOI marker, but do not accumulate stream headers.
            buffer[:] = b'\xff' if buffer.endswith(b'\xff') else b''
            return newest
        if start:
            del buffer[:start]
        end = buffer.find(b'\xff\xd9', 2)
        if end < 0:
            return newest
        newest = bytes(buffer[:end+2])
        del buffer[:end+2]


class IosRelay(ScreenRelay):
    def __init__(self, record_provider=None):
        super().__init__()
        self.record_provider=record_provider
        self.target = None
        self.target_lock = threading.Lock()

    def snapshot(self):
        with self.condition:
            return {'transport':'mjpeg','state':'stopped' if self.closing.is_set() else 'error' if self.error else 'running' if self.frame else 'idle',
                    'frames':self.sequence,'frame_bytes':len(self.frame),'error':self.error,
                    'producer_alive':bool(self.thread and self.thread.is_alive()),'generation':self.generation,
                    'input_ready':bool(self.frame)}

    def get_frame(self, client, udid, unused, after=-1, timeout=15):
        with self.target_lock:
            if self.target != udid:
                self.restart()
                self.target = udid
            return super().get_frame(client, udid, unused, after, timeout)

    def _produce(self, client, udid, _unused):
        process=None
        try:
            record=self.record_provider() if self.record_provider else owned()
            if udid!=record['udid']: raise ValueError('Simulator divergente.')
            ensure_companion(record,primary=self.record_provider is None)
            process=subprocess.Popen((client,'--companion',str(bridge_path(record)),'video-stream','--format','mjpeg','--fps','60','--scale-factor','.5','--compression-quality','.55'),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,bufsize=0)
            buffer=bytearray()
            while not self.closing.is_set() and time.monotonic()-self.last_viewer<10:
                if not select.select([process.stdout],[],[],1)[0]:
                    if process.poll() is not None: raise OSError('Vídeo iOS terminou.')
                    continue
                data=process.stdout.read(65536)
                if not data: raise OSError('Vídeo iOS desconectado.')
                buffer.extend(data)
                if len(buffer)>8*1024*1024: raise ValueError('Frame iOS excedeu limite.')
                frame=latest_jpeg(buffer)
                if frame is not None:
                    with self.condition: self.frame=frame;self.sequence+=1;self.condition.notify_all()
        except (OSError,ValueError,subprocess.TimeoutExpired) as error:
            with self.condition: self.error=str(error);self.condition.notify_all()
        finally:
            if process:
                process.terminate()
                try:process.wait(2)
                except subprocess.TimeoutExpired:process.kill();process.wait(2)
            with self.condition: self.error=self.error or 'Vídeo iOS fechado';self.frame=b'';self.condition.notify_all()

IOS_RELAY=IosRelay()

def close_input_bridge():
    global INPUT_BRIDGE, INPUT_UDID
    with IOS_LOCK:
        if INPUT_BRIDGE:
            try:
                INPUT_BRIDGE.stdin.close()
                INPUT_BRIDGE.wait(2)
            except (OSError,ValueError,subprocess.TimeoutExpired):
                INPUT_BRIDGE.terminate()
                try: INPUT_BRIDGE.wait(3)
                except subprocess.TimeoutExpired: INPUT_BRIDGE.kill();INPUT_BRIDGE.wait(2)
            INPUT_BRIDGE=None
