"""Explicit, scoped deletion of saved labs after shutdown and identity checks."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from . import lab_sessions, workspace_devices
from .android_worker import _run


def _checked_path(path, parent):
    if path.is_symlink() or path.resolve().parent != parent.resolve():
        raise ValueError('Caminho do laboratório não confirmado.')
    return path


def _avd_paths(identifier):
    home=Path(os.environ.get('ANDROID_AVD_HOME', str(Path.home()/'.android/avd')))
    directory=_checked_path(home/(identifier+'.avd'),home)
    settings=_checked_path(home/(identifier+'.ini'),home)
    if (directory.exists() and not directory.is_dir()) or (settings.exists() and not settings.is_file()):
        raise ValueError('Arquivos de configuração do AVD inválidos.')
    if settings.is_file():
        values=dict(line.split('=',1) for line in settings.read_text().splitlines() if '=' in line)
        if not values.get('path') or Path(values['path']).expanduser().resolve()!=directory.resolve():
            raise ValueError('O AVD aponta para outro diretório; exclusão recusada.')
    return directory,settings


def _android_running(sdk):
    if sdk is None:
        raise ValueError('Android SDK indisponível para confirmar os aparelhos.')
    listed=_run((str(sdk.adb),'devices'),timeout=5)
    if listed.returncode:
        raise ValueError('ADB indisponível; nenhum AVD será excluído.')
    running=set()
    for line in listed.stdout.splitlines():
        parts=line.split()
        if not parts or not re.fullmatch(r'emulator-\d+',parts[0]):
            continue
        if len(parts)!=2 or parts[1]!='device':
            raise ValueError('Um emulador está sem identidade confirmada. Aguarde ou reconecte antes de excluir.')
        result=_run((str(sdk.adb),'-s',parts[0],'emu','avd','name'),timeout=3)
        name=result.stdout.splitlines()[0].strip() if result.stdout.splitlines() else ''
        if result.returncode or not name:
            raise ValueError('Não foi possível identificar um emulador conectado.')
        running.add(name)
    return running


def _ios_devices():
    from . import ios_worker
    listed=ios_worker.sim('list','devices','--json',timeout=8)
    if listed.returncode:
        raise ValueError('Inventário iOS indisponível; exclusão recusada.')
    return {device['udid']:device for group in json.loads(listed.stdout).get('devices',{}).values() for device in group}


def delete_saved_labs(worker, identifiers, expected_current_id, *, delete_data=False):
    """Remove only explicitly confirmed saved labs; captured evidence is kept separately."""
    if delete_data is not True:
        return {'ok':False,'reason':'Confirme a exclusão dos apps e dados dos labs selecionados.'}
    if not isinstance(identifiers,list) or not 1<=len(identifiers)<=30 or any(
        not isinstance(identifier,str) or not lab_sessions.LAB_NAME.fullmatch(identifier) for identifier in identifiers
    ) or len(set(identifiers))!=len(identifiers):
        return {'ok':False,'reason':'Seleção de laboratórios inválida.'}
    if not isinstance(expected_current_id,str) or (expected_current_id and not lab_sessions.LAB_NAME.fullmatch(expected_current_id)):
        return {'ok':False,'reason':'Identidade do laboratório atual inválida.'}
    if not lab_sessions.LAB_LOCK.acquire(blocking=False):
        return {'ok':False,'reason':'Outra operação de laboratório está em andamento.'}
    try:
        if (lab_sessions.current().get('id') or '')!=expected_current_id:
            return {'ok':False,'reason':'O laboratório atual mudou. Atualize a lista antes de excluir.'}
        selected=set(identifiers)
        saved={item['id'] for item in lab_sessions.inventory()['labs']}
        if not selected.issubset(saved):
            return {'ok':False,'reason':'A seleção inclui um lab que não está mais salvo. Atualize a lista.'}
        records=workspace_devices.records()
        members={identifier:[record for record in records if record['workspace_id']==identifier] for identifier in identifiers}
        try:
            ios_records=[record for identifier in identifiers for record in members[identifier] if record.get('platform')=='ios']
            ios=_ios_devices() if ios_records else {}
            native=set(identifiers)|{record['id'] for identifier in identifiers for record in members[identifier]}
            ios_ids={record['udid'] for record in ios_records}
            if native.intersection(saved-selected) or len(ios_ids)!=len(ios_records):
                raise ValueError('Identidade compartilhada entre laboratórios; exclusão recusada.')
            if any(record['workspace_id'] not in selected and (record['id'] in native or record.get('udid') in ios_ids) for record in records):
                raise ValueError('Um aparelho pertence a outro workspace; exclusão recusada.')
            paths={}
            for identifier in identifiers:
                folder=lab_sessions.root()
                paths[identifier]=[_checked_path(folder/identifier,folder)]
                if paths[identifier][0].exists() and not paths[identifier][0].is_dir():
                    raise ValueError('Diretório de dados inválido.')
                _checked_path(folder/(identifier+'.json'),folder)
                layout=workspace_devices.root().parent/'workspace-layout'
                paths[identifier].append(_checked_path(layout/(identifier+'.json'),layout))
                for record in members[identifier]:
                    paths[identifier].append(_checked_path(workspace_devices.root()/(record['id']+'.json'),workspace_devices.root()))
                    if record.get('platform')=='ios':
                        found=ios.get(record['udid'])
                        if found and found.get('name')!=record['name']:
                            raise ValueError('Identidade de um Simulator adicional divergente.')
                    else:
                        _avd_paths(record['id'])
                for path in paths[identifier][1:]:
                    if path.exists() and not path.is_file():
                        raise ValueError('Registro de laboratório inválido.')
                _avd_paths(identifier)
            if expected_current_id in selected:
                _checked_path(lab_sessions.root()/'current.json',lab_sessions.root())
        except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired):
            return {'ok':False,'reason':'Não foi possível confirmar os arquivos e aparelhos selecionados. Nenhum lab foi excluído.'}

        stopped=lab_sessions.stop_saved_labs(worker,identifiers,expected_current_id)
        if not stopped.get('ok'):
            return stopped
        failures={item['lab_id'] for item in stopped['results'] if item['state']=='failed'}
        try:
            running=_android_running(worker.sdk)
            ios=_ios_devices() if ios_records else {}
        except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired):
            return {'ok':False,'reason':'Desligamento solicitado, mas o estado final não foi confirmado. Nenhum lab foi excluído.'}
        results=[]
        for identifier in identifiers:
            try:
                if identifier in failures:
                    raise ValueError('Um aparelho ainda não desligou.')
                android_ids=[identifier]+[record['id'] for record in members[identifier] if record.get('platform')!='ios']
                if running.intersection(android_ids):
                    raise ValueError('Um Android ainda está ligado.')
                for record in members[identifier]:
                    if record.get('platform')=='ios':
                        found=ios.get(record['udid'])
                        if found and (found.get('name')!=record['name'] or found.get('state')!='Shutdown'):
                            raise ValueError('Um Simulator ainda está ligado ou mudou de identidade.')
                for name in android_ids:
                    directory,settings=_avd_paths(name)
                    if directory.exists() or settings.exists():
                        deleted=_run((str(worker.sdk.avdmanager),'delete','avd','--name',name),timeout=60)
                        if deleted.returncode and 'does not exist' not in (deleted.stdout+deleted.stderr).lower():
                            raise ValueError('O Android SDK recusou a exclusão do AVD.')
                        if directory.exists() or settings.exists():
                            raise ValueError('Arquivos do AVD ainda presentes; exclusão não confirmada.')
                for record in members[identifier]:
                    if record.get('platform')=='ios' and record['udid'] in ios:
                        from . import ios_worker
                        if ios_worker.sim('delete',record['udid'],timeout=30).returncode:
                            raise ValueError('O Simulator recusou a exclusão.')
                        if record['udid'] in _ios_devices():
                            raise ValueError('O Simulator ainda está presente; exclusão não confirmada.')
                for record in members[identifier]:
                    workspace_devices.forget(record)
                for path in paths[identifier]:
                    _checked_path(path,path.parent)
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink(missing_ok=True)
                if identifier==expected_current_id:
                    (lab_sessions.root()/'current.json').unlink(missing_ok=True)
                (lab_sessions.root()/(identifier+'.json')).unlink(missing_ok=True)
                results.append({'lab_id':identifier,'state':'deleted','reason':''})
            except (OSError,ValueError,TypeError,KeyError,subprocess.TimeoutExpired):
                results.append({'lab_id':identifier,'state':'failed','reason':'Exclusão incompleta. O lab continua na lista para revisão e nova tentativa.'})
        return {'ok':True,'results':results,'deleted':sum(item['state']=='deleted' for item in results),
                'failed':sum(item['state']=='failed' for item in results)}
    finally:
        lab_sessions.LAB_LOCK.release()
