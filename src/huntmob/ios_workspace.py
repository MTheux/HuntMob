"""Per-Simulator lifecycle and input, independent of the primary iOS selection."""
import json
import math
import select
import subprocess
import tempfile
import threading
from pathlib import Path
from . import ios_worker as ios

SESSIONS = {}
SESSION_LOCK = threading.Lock()


class IosDevice:
    def __init__(self, record):
        self.record=record;self.serial=record['udid'];self.avd_name=record['id'];self.bridge=None
        self.lock=threading.RLock();self.video=ios.IosRelay(record_provider=self.owned)

    def status(self):
        result=ios.sim('list','devices','--json',timeout=8)
        if result.returncode: return {'state':'error','ownership_verified':False}
        devices=json.loads(result.stdout).get('devices',{})
        found=next((d for group in devices.values() for d in group if d.get('udid')==self.serial and d.get('name')==self.record['name']),None)
        return {'state':'device' if found and found.get('state')=='Booted' else 'offline',
                'ownership_verified':bool(found),'properties':{'sys.boot_completed':'1' if found and found.get('state')=='Booted' else '0'}}

    def owned(self):
        state=self.status()
        if state['state']!='device' or not state['ownership_verified']: raise ValueError('Simulator adicional não está ligado.')
        return self.record

    def start(self):
        with self.lock:
            state=self.status()
            if not state['ownership_verified']: raise ValueError('Simulator salvo não encontrado. Nenhuma identidade foi substituída.')
            if state['state']!='device' and ios.sim('boot',self.serial).returncode: raise ValueError('Simulator não iniciou.')
            if ios.sim('bootstatus',self.serial,'-b',timeout=180).returncode: raise ValueError('Boot iOS não concluído.')
            ios.ensure_companion(self.record,primary=False)
            if self.video.closing.is_set():self.video.restart()
            return {'ok':True}

    def close_input(self):
        if self.bridge:
            process=self.bridge;self.bridge=None
            try:process.stdin.close();process.wait(2)
            except (OSError,ValueError,subprocess.TimeoutExpired):
                process.terminate()
                try:process.wait(2)
                except subprocess.TimeoutExpired:process.kill();process.wait(2)

    def stop(self):
        with self.lock:
            self.close_input()
            if not self.status()['ownership_verified']:raise ValueError('Simulator divergente.')
            if self.status()['state']=='offline':return {'ok':True}
            return {'ok':ios.sim('shutdown',self.serial).returncode==0}

    def screenshot(self):
        self.owned()
        with tempfile.TemporaryDirectory(prefix='huntmob-ios-screen-') as directory:
            path=Path(directory)/'screen.png'
            result=ios.sim('io',self.serial,'screenshot','--type=png',str(path),timeout=15)
            if result.returncode or not path.is_file():raise ValueError('Captura iOS indisponível.')
            return path.read_bytes()

    def input(self,payload):
        action=payload.get('action');clean={'action':action}
        if action=='touch':
            if payload.get('phase') not in {'down','move','up','cancel'}:raise ValueError('Fase inválida.')
            clean['phase']=payload['phase']
            for key in ('x','y'):
                value=float(payload[key])
                if not math.isfinite(value) or not 0<=value<=1:raise ValueError('Coordenada inválida.')
                clean[key]=value
        elif action=='key':
            if payload.get('key') not in {'Backspace','Enter','Tab','ArrowUp','ArrowDown','ArrowLeft','ArrowRight'}:raise ValueError('Tecla inválida.')
            clean['key']=payload['key']
        elif action=='text':
            value=payload.get('text')
            if not isinstance(value,str) or not value or len(value)>256 or not all(32<=ord(c)<127 for c in value):raise ValueError('Texto ASCII inválido.')
            clean['text']=value
        elif action not in {'home','recents','lock'}:raise ValueError('Ação iOS indisponível.')
        with self.lock:
            if not self.bridge or self.bridge.poll() is not None:
                self.owned();ios.ensure_companion(self.record,primary=False)
                python=ios.client_path().with_name('python3')
                self.bridge=subprocess.Popen((str(python),str(Path(ios.__file__).with_name('ios_input_bridge.py')),str(ios.bridge_path(self.record)),self.serial),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
                if not select.select([self.bridge.stdout],[],[],8)[0] or not json.loads(self.bridge.stdout.readline()).get('ready'):
                    self.close_input();raise ValueError('Input iOS não iniciou.')
            self.bridge.stdin.write(json.dumps(clean)+'\n');self.bridge.stdin.flush()
            if not select.select([self.bridge.stdout],[],[],5)[0]:self.close_input();raise ValueError('Input iOS excedeu o limite.')
            return json.loads(self.bridge.stdout.readline())


def device(record):
    with SESSION_LOCK:
        if record['id'] not in SESSIONS:SESSIONS[record['id']]=IosDevice(record)
        return SESSIONS[record['id']]


def create_record(workspace_id,runtime,model):
    from uuid import uuid4
    from datetime import datetime,timezone
    catalog=ios.lab_catalog()
    if runtime not in {r['id'] for r in catalog['runtimes']}:raise ValueError('Instale o runtime iOS antes de criar o aparelho.')
    selected=next((d for d in catalog['models'] if d['id']==model),None)
    parts=runtime.rsplit('iOS-',1)[-1].split('-')
    number=sum(int(part)*factor for part,factor in zip(parts,(65536,256,1)))
    if not selected or not selected['minimum']<=number<=selected['maximum']:raise ValueError('Modelo incompatível com a versão iOS.')
    name='HuntMob iOS Workspace '+uuid4().hex
    result=ios.sim('create',name,model,runtime)
    if result.returncode:raise ValueError('CoreSimulator recusou a criação.')
    from uuid import UUID
    udid=str(UUID(result.stdout.strip())).upper()
    return {'id':'huntmob_lab_'+uuid4().hex,'workspace_id':workspace_id,'platform':'ios','udid':udid,
            'name':name,'runtime':runtime,'model':model,'data_mode':'clean','created_at':datetime.now(timezone.utc).isoformat()}


def shutdown():
    for item in list(SESSIONS.values()):
        item.video.shutdown();item.close_input()
