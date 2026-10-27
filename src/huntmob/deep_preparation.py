"""Read-only APK extraction and REA preparation for an owned Android target.

Package inspection does not require a full Java reconstruction. Existing source
trees are preserved; a newly extracted APK is explicitly marked apk-only.
"""
import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from . import dynamic_runtime, lab_sessions, reverse_engines, reverse_workspace
from .android_worker import _run
from .workspace_pairs import apk_paths, remote_digest, require_online

LOCK = threading.Lock()
BUSY = set()


def _path(lab):
    return lab_sessions.root() / lab['id'] / 'rea-preparation.json'


def status(lab):
    if not lab.get('id'):
        return None
    try:
        job = json.loads(_path(lab).read_text())
        if any(job.get(k) != lab.get(k) for k in ('package_id', 'apk_sha256')):
            return None
        if job.get('state') == 'running' and job.get('key') not in BUSY:
            job.update(state='interrupted', reason='Worker reiniciado. Prepare o REA novamente.')
        return job
    except (OSError, ValueError, TypeError):
        return None


def register_engagement(payload):
    name = lab_sessions.engagement_name(payload.get('engagement'))
    if not name:
        raise ValueError('Informe o nome ou código do engagement autorizado.')
    with lab_sessions.LAB_LOCK:
        lab = dynamic_runtime.scope(payload.get('package_id'), payload.get('workspace_id'), payload.get('device_id'))
        if lab.get('apk_sha256') != payload.get('apk_sha256'):
            raise ValueError('O APK selecionado mudou.')
        owner = lab.get('workspace_id') or lab['id']
        record = lab_sessions.current()
        if record.get('id') != owner:
            raise ValueError('O laboratório selecionado mudou.')
        lab_sessions.save({**record, 'engagement': name})
    return {'ok': True, 'workspace_id': owner, 'engagement': name}


def _ensure_apk(lab, workspace_id, device_id):
    owner = lab.get('workspace_id') or lab['id']
    package, sha = lab['package_id'], lab['apk_sha256']
    try:
        record = reverse_workspace.latest(package, owner)
        reverse_engines.bound(package, owner, record['run_id'], sha)
        return record
    except (OSError, ValueError, KeyError, TypeError):
        pass
    worker = dynamic_runtime.target_worker(lab)
    require_online(worker)
    remote = apk_paths(worker, package)[0]
    if remote_digest(worker, remote) != sha:
        raise ValueError('O APK instalado difere do app selecionado. Sincronize o par novamente.')
    size = _run((str(worker.sdk.adb), '-s', worker.serial, 'shell', 'stat', '-c', '%s', remote), timeout=10)
    if size.returncode or not size.stdout.strip().isdigit() or not 0 < int(size.stdout) <= 512 * 1024**2:
        raise ValueError('O APK excede o limite de 512 MB ou seu tamanho não foi verificado.')
    with tempfile.TemporaryDirectory(prefix='huntmob-rea-input-') as folder:
        apk = Path(folder) / 'base.apk'
        pulled = _run((str(worker.sdk.adb), '-s', worker.serial, 'pull', remote, str(apk)), timeout=180)
        if pulled.returncode or not apk.is_file() or reverse_engines.digest(apk) != sha or remote_digest(worker, remote) != sha:
            raise ValueError('Não foi possível extrair e verificar o mesmo APK instalado.')
        with lab_sessions.LAB_LOCK:
            fresh = dynamic_runtime.scope(package, workspace_id, device_id)
            if fresh.get('id') != lab['id'] or fresh.get('apk_sha256') != sha:
                raise ValueError('O aparelho ou APK mudou durante a extração.')
            # A concurrent full Reverse run may already have prepared this input.
            try:
                record = reverse_workspace.latest(package, owner)
                reverse_engines.bound(package, owner, record['run_id'], sha)
                return record
            except (OSError, ValueError, KeyError, TypeError):
                pass
            destination = reverse_workspace.prepare_workspace(package, owner)
            temporary = destination / (uuid4().hex + '.apk.tmp')
            try:
                with apk.open('rb') as source, os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
                    import shutil
                    shutil.copyfileobj(source, output)
                temporary.replace(destination / 'base.apk')
            finally:
                temporary.unlink(missing_ok=True)
            record = {'ok': True, 'package_id': package, 'sha256': sha, 'run_id': uuid4().hex,
                      'status': 'apk-only', 'files': [], 'file_count': 0, 'problem_files': [],
                      'warning': 'APK identificado para inspeção REA. Abra Reverse para reconstruir o código Java.'}
            reverse_engines.save(destination / 'analysis.json', record)
            return record


def _work(job, lab, workspace_id, device_id):
    def stage(value, detail):
        job.update(stage=value, detail=detail)
        dynamic_runtime.private_json(_path(lab), job)
    try:
        stage('extracting', 'Extraindo e conferindo o SHA256 do APK instalado…')
        record = _ensure_apk(lab, workspace_id, device_id)
        owner = lab.get('workspace_id') or lab['id']
        params = {'package_id': lab['package_id'], 'workspace_id': owner, 'run_id': record['run_id'], 'sha256': lab['apk_sha256']}
        existing = reverse_engines.jobs(**{'package': params['package_id'], 'workspace': owner, 'run': record['run_id'], 'sha': lab['apk_sha256']})['jobs']
        if not any(item.get('state') == 'complete' and item.get('evidence', {}).get('subject', {}).get('digest', {}).get('sha256') == lab['apk_sha256'] for item in existing):
            stage('inspecting', 'REA inspecionando Manifest e pacote. Limite de 3 minutos; não há previsão exata.')
            started = next((item for item in existing if item.get('state') == 'running'), None)
            if not started:
                started = reverse_engines.start({**params, 'operation': 'package'})
            deadline = time.monotonic() + 195
            while time.monotonic() < deadline:
                items = reverse_engines.jobs(lab['package_id'], owner, record['run_id'], lab['apk_sha256'])['jobs']
                result = next((item for item in items if item.get('job_id') == started['job_id']), {})
                if result.get('state') == 'complete':
                    break
                if result.get('state') in {'failed', 'interrupted'}:
                    raise ValueError(result.get('reason') or 'Inspeção REA não concluída.')
                time.sleep(.5)
            else:
                raise ValueError('A espera pelo REA excedeu o limite. Confira o worker e tente novamente.')
        job.update(ok=True, state='complete', stage='complete', detail='Evidência REA preparada para o mesmo APK. A AI exige execução explícita.')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        job.update(ok=False, state='failed', reason=str(error) if isinstance(error, ValueError) else 'Preparação REA não concluída. Verifique Android, armazenamento e motor REA.')
    finally:
        job['completed_at'] = datetime.now(timezone.utc).isoformat()
        try:
            dynamic_runtime.private_json(_path(lab), job)
        finally:
            with LOCK:
                BUSY.discard(job['key'])


def start(payload):
    workspace_id, device_id = payload.get('workspace_id'), payload.get('device_id')
    lab = dynamic_runtime.scope(payload.get('package_id'), workspace_id, device_id)
    if lab.get('apk_sha256') != payload.get('apk_sha256'):
        raise ValueError('O APK selecionado mudou.')
    reverse_engines.tooling()
    key = ':'.join((lab.get('workspace_id') or lab['id'], lab['package_id'], lab['apk_sha256']))
    with LOCK:
        if key in BUSY:
            raise ValueError('Uma preparação REA deste APK já está em execução.')
        BUSY.add(key)
    job = {'ok': True, 'state': 'running', 'stage': 'queued', 'key': key,
           'job_id': 'rea_prepare_' + uuid4().hex, 'lab_id': lab['id'],
           'package_id': lab['package_id'], 'apk_sha256': lab['apk_sha256'],
           'created_at': datetime.now(timezone.utc).isoformat()}
    try:
        dynamic_runtime.private_json(_path(lab), job)
        threading.Thread(target=_work, args=(job, lab, workspace_id, device_id), daemon=True).start()
    except Exception:
        with LOCK:
            BUSY.discard(key)
        raise
    return job.copy()
