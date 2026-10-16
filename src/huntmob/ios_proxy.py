"""Separate local iOS proxy with app-scoped routing; no host network changes."""
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from uuid import UUID
from . import ios_worker
from .network_capture import visible_snapshot, clear_capture

PORT=18083
LOCK=threading.RLock()
PROCESS=None
TARGET=None


def store(record):
    identifier='ios_'+UUID(record['udid']).hex
    return Path.home()/'.huntmob/labs'/identifier/'network.json'


def status():
    record=ios_worker.saved()
    active=PROCESS is not None and PROCESS.poll() is None and TARGET==record.get('udid')
    path=store(record) if record.get('udid') else None
    captured=visible_snapshot(path) if path and path.exists() and not path.is_symlink() and path.stat().st_size<=8*1024*1024 else {'flows':[]}
    return {'ok':True,'active':active,'port':PORT,'app_routing_configured':active and record.get('package_id')=='com.huntmob.ios.lab','flows':captured.get('flows',[]),'tls_trust_configured':False}


def start():
    global PROCESS,TARGET
    with LOCK,ios_worker.IOS_LOCK:
        record=ios_worker.owned()
        if not record.get('package_id') or not record.get('binary_sha256'):
            raise ValueError('Selecione um app autorizado antes de iniciar a captura iOS.')
        if PROCESS is not None and PROCESS.poll() is None:
            if TARGET!=record['udid']: raise ValueError('Encerre a captura do lab anterior primeiro.')
            return status()
        executable=shutil.which('mitmdump')
        if not executable: raise ValueError('Motor mitmdump ausente no worker.')
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',PORT))
            except OSError as error:raise ValueError('Porta iOS ocupada; nenhum serviço existente foi adotado.') from error
        path=store(record);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        env=dict(os.environ,HUNTMOB_IOS_CAPTURE_LAB=path.parent.name)
        source=Path(__file__).resolve().parent
        env['PYTHONPATH']=str(source.parent)+os.pathsep+env.get('PYTHONPATH','')
        log=(path.parent/'proxy.log').open('ab')
        try:
            PROCESS=subprocess.Popen([executable,'--quiet','--listen-host','127.0.0.1','--listen-port',str(PORT),'-s',str(source/'ios_capture_addon.py')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,umask=0o077)
        finally:log.close()
        TARGET=record['udid']
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if PROCESS.poll() is not None:raise ValueError('Motor de captura iOS encerrou; consulte o log privado do lab.')
            with socket.socket() as probe:
                probe.settimeout(.2)
                if probe.connect_ex(('127.0.0.1',PORT))==0:break
            time.sleep(.1)
        else:
            stop();raise ValueError('Listener iOS não ficou disponível.')
        # Our fixture explicitly opts into URLSession proxy configuration. This
        # does not claim routing of arbitrary apps or change the Mac's proxy.
        if record['package_id']=='com.huntmob.ios.lab':
            env=dict(os.environ,SIMCTL_CHILD_HUNTMOB_LAB_PROXY_PORT=str(PORT))
            result=ios_worker._run(('xcrun','simctl','launch','--terminate-running-process',record['udid'],record['package_id']),timeout=15,env=env)
            if result.returncode:
                stop();raise ValueError('Fixture não abriu com configuração de proxy.')
        result=status()
        result['reason']='Captura pronta para a requisição de teste da fixture.' if result['app_routing_configured'] else 'Listener pronto. Este app precisa configurar o proxy 127.0.0.1:18083; roteamento automático ainda não validado.'
        return result


def stop():
    global PROCESS,TARGET
    with LOCK:
        if PROCESS is not None:
            PROCESS.terminate()
            try:PROCESS.wait(3)
            except subprocess.TimeoutExpired:PROCESS.kill();PROCESS.wait(3)
        old=TARGET;PROCESS=None;TARGET=None
        record=ios_worker.saved()
        if record.get('udid')==old and record.get('package_id')=='com.huntmob.ios.lab':
            ios_worker.sim('launch','--terminate-running-process',old,record['package_id'],timeout=15)
        return {'ok':True,'active':False,'reason':'Captura iOS encerrada.'}


def clear():
    record=ios_worker.owned();clear_capture(store(record))
    return {'ok':True,'reason':'Capturas iOS limpas.'}
