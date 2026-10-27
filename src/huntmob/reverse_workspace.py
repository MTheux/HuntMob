"""Read-only browsing of recorded analysis runs inside the active lab."""
from __future__ import annotations
import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath

PACKAGE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$')
RUN = re.compile(r'^[a-f0-9]{32}$')


def workspace(package, avd):
    if not PACKAGE.fullmatch(package):
        raise ValueError('Invalid package')
    from .lab_sessions import LAB_NAME
    if not LAB_NAME.fullmatch(avd):
        raise ValueError('Invalid lab')
    return Path.home() / '.huntmob/workspaces' / avd / package


def latest(package, avd):
    record = json.loads((workspace(package, avd) / 'analysis.json').read_text())
    if record.get('package_id') != package or not RUN.fullmatch(record.get('run_id', '')):
        raise ValueError('Invalid analysis record')
    return record


def prepare_workspace(package, avd):
    """Make APK/source storage private even for direct native CLI with umask 022."""
    destination = workspace(package, avd)
    for path in (Path.home() / '.huntmob', destination.parents[1], destination.parents[0], destination):
        if path.is_symlink():
            raise ValueError('O workspace privado não pode ser um link simbólico.')
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
    return destination


def artifact(package, avd, run_id, filename, record=None):
    if not RUN.fullmatch(run_id):
        raise ValueError('Invalid run')
    record = record or latest(package, avd)
    if record['run_id'] != run_id:
        raise ValueError('Analysis was replaced; refresh the workspace')
    relative = PurePosixPath(filename)
    if relative.is_absolute() or '..' in relative.parts or '\\' in filename or ':' in filename:
        raise ValueError('Invalid artifact path')
    if filename not in record['files']:
        raise ValueError('File not in this analysis')
    root = (workspace(package, avd) / 'jadx-runs' / run_id).resolve()
    path = root.joinpath(*relative.parts)
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise ValueError('Artifact escapes analysis')
    return path


def preview(package, avd, run_id, filename):
    path = artifact(package, avd, run_id, filename)
    size = path.stat().st_size
    with path.open('rb') as stream:
        content = stream.read(256 * 1024)
    binary = b'\x00' in content
    try:
        text = content.decode('utf-8') if not binary else ''
    except UnicodeDecodeError:
        binary = True
    if binary:
        text = '\n'.join(f'{offset:08x}  '+content[offset:offset+16].hex(' ') for offset in range(0, min(len(content),4096),16))
    return {'path':filename,'content':text,'format':'hex' if binary else 'text',
            'size':size,'truncated':size>(4096 if binary else 256*1024)}


def export(package, avd, run_id):
    record = latest(package,avd)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('analysis.json',json.dumps(record,indent=2))
        for name in record['files']:
            archive.write(artifact(package,avd,run_id,name,record=record),name)
    return buffer.getvalue()
