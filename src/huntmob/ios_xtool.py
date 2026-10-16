"""Bounded xtool adapter for explicitly selected physical iOS devices.

Apple authentication stays in xtool's own local setup; no credentials are
accepted by HuntMob. This module never adopts a Simulator or virtual runtime.
"""
import re
import shutil
import subprocess
import threading
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from .ios_static import inspect_ipa
from .dynamic_runtime import private_json

LOCK = threading.Lock()
UDID = re.compile(r'(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{8}-[a-fA-F0-9]{16})\Z')
BUNDLE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{1,254}\Z')


def executable():
    path = shutil.which('xtool')
    if not path:
        raise ValueError('xtool ausente no worker. Consulte a preparação local na documentação do HuntMob.')
    return path


def run(args, timeout=15):
    try:
        return subprocess.run([executable(), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise ValueError('xtool excedeu o tempo de resposta. A operação não foi confirmada; confira o dispositivo antes de repetir.') from error


def devices():
    result = run(['devices', '--usb', '--no-wait'])
    if result.returncode:
        raise ValueError('xtool não conseguiu consultar dispositivos USB. Verifique pareamento e acesso USB no worker.')
    found=[]
    for line in result.stdout.splitlines():
        match=re.fullmatch(r'(.{1,200}) \[([^\]]+)\]: ([A-Fa-f0-9-]+)', line.strip())
        if match and UDID.fullmatch(match[3]):
            found.append({'name':match[1], 'connection':match[2], 'udid':match[3]})
    return found


def status():
    try:
        executable()
        version=run(['--version'], timeout=5)
        found=devices()
        return {'ok':True, 'available':True, 'version':version.stdout.strip()[:80] if version.returncode==0 else 'desconhecida',
                'devices':found, 'runtime':'physical-ios', 'emulator':False,
                'reason':'Selecione um dispositivo USB autorizado.' if found else 'Nenhum iPhone USB conectado e pareado.',
                'setup_command':'xtool setup'}
    except (OSError, ValueError):
        return {'ok':False, 'available':bool(shutil.which('xtool')), 'devices':[],
                'reason':'xtool indisponível ou sem acesso USB. Verifique a preparação no worker.', 'setup_command':'xtool setup'}


def selected(udid):
    if not isinstance(udid,str) or not UDID.fullmatch(udid):
        raise ValueError('Selecione um UDID físico válido; UUID de Simulator não é aceito.')
    if udid not in {item['udid'] for item in devices()}:
        raise ValueError('O dispositivo selecionado não está conectado via USB. Nenhum outro dispositivo será usado.')


def receipt(action, udid, **fields):
    record={'id':uuid4().hex, 'at':datetime.now(timezone.utc).isoformat(), 'provider':'xtool',
            'runtime':'physical-ios', 'action':action, 'udid':udid, **fields}
    private_json(Path.home()/'.huntmob/ios/xtool'/('receipt-'+record['id']+'.json'),record)
    return record


def install(path, udid):
    if not LOCK.acquire(blocking=False): raise ValueError('Operação xtool já em andamento.')
    try:
        selected(udid)
        metadata=inspect_ipa(Path(path))
        result=run(['install','--usb','--udid',udid,str(Path(path).resolve())],timeout=180)
        if result.returncode:
            raise ValueError('Instalação não confirmada. Verifique xtool setup, Developer Mode, assinatura e provisioning. O Bundle ID pode mudar ao assinar; nenhum app foi aberto automaticamente.')
        record=receipt('install',udid,ipa_sha256=metadata['sha256'],source_bundle_id=metadata['bundle_id'],
                       install_command_succeeded=True, launch_verified=False)
        return {'ok':True,'receipt':record,'reason':'xtool confirmou instalação. Informe o Bundle ID realmente instalado para abrir o app; ele pode diferir do IPA original.'}
    finally:
        LOCK.release()


def launch(udid, bundle):
    if not isinstance(bundle,str) or not BUNDLE.fullmatch(bundle) or '.' not in bundle:
        raise ValueError('Informe o Bundle ID instalado no dispositivo.')
    if not LOCK.acquire(blocking=False): raise ValueError('Operação xtool já em andamento.')
    try:
        selected(udid)
        result=run(['launch','--usb','--udid',udid,bundle],timeout=30)
        if result.returncode:
            raise ValueError('Abertura não confirmada. Confira o Bundle ID instalado, Developer Mode e acesso ao debugserver.')
        return {'ok':True,'receipt':receipt('launch',udid,bundle_id=bundle,launch_command_succeeded=True),
                'reason':'xtool confirmou abertura pelo debugserver. Tela e interação físicas não estão integradas ao HuntMob.'}
    finally:
        LOCK.release()
