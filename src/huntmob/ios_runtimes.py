"""Installed runtimes plus the official Xcode 27.1 catalogue observed locally."""
import platform
import re
import shutil
import subprocess
import threading
from pathlib import Path
from .android_worker import _run
from . import ios_worker

# Xcode > Settings > Components > Add Platforms, verified 2026-10-16.
OFFERED = {'17.0':7.56,'17.0.1':7.21,'17.2':7.35,'17.4':7.23,'17.5':7.34,
           '18.0':8.39,'18.1':8.59,'18.2':8.72,'18.3.1':8.72,'18.4':8.86,'18.5':8.86,'18.6':8.86,
           '26.0.1':8.05,'26.1':8.32,'26.2':8.39,'26.3.1':8.39,'26.4':8.46,'26.4.1':8.46,'26.5':8.52,'27.1':7.85}
LOCK = threading.Lock()
JOB = {'state':'idle'}


def catalog():
    mac = platform.system() == 'Darwin'
    info = ios_worker.inventory()
    installed = {}
    for item in info.get('runtimes', []):
        match = re.search(r'iOS-(\d+)-(\d+)(?:-(\d+))?$', item['id'])
        if match:
            version = '.'.join(part for part in match.groups() if part is not None)
            installed[version] = item
    xcode = ''
    if mac:
        try: xcode = _run(('xcodebuild','-version'), timeout=8).stdout.splitlines()[0]
        except (OSError, IndexError, subprocess.TimeoutExpired): pass
    compatible = mac and xcode.startswith('Xcode 27.')
    free = shutil.disk_usage(Path.home()).free
    values = []
    versions = set(OFFERED) | set(installed) | {str(n) for n in range(1,17)}
    for version in sorted(versions,key=lambda v:tuple(map(int,v.split('.'))),reverse=True):
        major = int(version.split('.')[0])
        size = OFFERED.get(version)
        required = int((size * 2 + 4) * 1_000_000_000) if size else None
        if version in installed:
            state, reason = 'installed', 'Runtime instalado neste worker.'
        elif major < 15:
            state, reason = 'historical', 'Versão histórica; execução não validada no HuntMob. Precisa de provider e ambiente compatíveis.'
        elif major < 17:
            state, reason = 'other-worker', 'Requer outro worker com macOS/Xcode e runtime compatíveis. Não suportado pelo Xcode 27 deste worker.'
        elif not compatible:
            state, reason = 'other-worker', 'Oferta verificada no Xcode 27.1. Confira um worker compatível antes de preparar.'
        elif free < required:
            state, reason = 'disk-space', f'Libere espaço: reserva de {required/1e9:.1f} GB para download, instalação e temporários; livres {free/1e9:.1f} GB.'
        else:
            state, reason = 'offered', 'Oferecido pela Apple; instalação e boot serão verificados após a preparação.'
        values.append({'version':version,'name':('iPhone OS ' if major<4 else 'iOS ')+version,
                       'runtime_id':installed.get(version,{}).get('id'),'state':state,'reason':reason,
                       'download_gb':size,'required_bytes':required,'can_install':state=='offered'})
    with LOCK: job = dict(JOB)
    return {'ok':True,'xcode':xcode,'free_bytes':free,'versions':values,'job':job,
            'catalog_observed_at':'2026-10-16','catalog_source':'Xcode 27.1 · Components · Add Platforms',
            'source_url':'https://developer.apple.com/xcode/system-requirements',
            'note':'Lista oferecida pela Apple observada em 16/10/2026; não representa todas as versões históricas nem garante disponibilidade futura do download.'}


def install(version):
    item = next((item for item in catalog()['versions'] if item['version']==version), None)
    if not item or not item['can_install']:
        return {'ok':False,'reason':item['reason'] if item else 'Versão fora do catálogo oficial observado.'}
    with LOCK:
        if JOB.get('state')=='installing': return {'ok':False,'reason':'Já há uma preparação iOS em andamento.'}
        JOB.clear(); JOB.update(state='installing',version=version,reason='Preparando runtime oficial pelo Xcode…')
    def run():
        try:
            variant='arm64' if platform.machine().lower() in {'arm64','aarch64'} else 'universal'
            result=_run(('xcodebuild','-downloadPlatform','iOS','-buildVersion',version,'-architectureVariant',variant),timeout=1800,input_text='')
            identifier='com.apple.CoreSimulator.SimRuntime.iOS-'+version.replace('.','-')
            ready=result.returncode==0 and any(r['id']==identifier for r in ios_worker.inventory().get('runtimes',[]))
            state='installed' if ready else 'failed'
            reason='Runtime instalado; selecione versão e modelo para criar o aparelho.' if ready else 'Xcode não concluiu a instalação. Confira Components, conexão, espaço e compatibilidade; nenhum runtime foi marcado como pronto.'
        except (OSError, subprocess.TimeoutExpired):
            state,reason='failed','Preparação interrompida ou excedeu 30 minutos. Confira Components no Xcode antes de repetir.'
        with LOCK: JOB.update(state=state,reason=reason)
    threading.Thread(target=run,daemon=True).start()
    return {'ok':True,'job':dict(JOB)}
