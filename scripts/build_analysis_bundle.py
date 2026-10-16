#!/usr/bin/env python3
"""Build the embedded HuntMob analysis assets from pinned official releases.

Only the release builder downloads. Installed clients analyze offline.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import posixpath
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

PROJECT = Path(__file__).resolve().parents[1]


def host_target():
    system = {'Darwin': 'mac', 'Linux': 'linux', 'Windows': 'windows'}[platform.system()]
    arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x64', 'AMD64': 'x64'}[platform.machine()]
    return system + '-' + arch


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def download(spec, path):
    with urllib.request.urlopen(spec['url'], timeout=60) as response, path.open('wb') as output:
        shutil.copyfileobj(response, output)
    if digest(path) != spec['sha256']:
        raise ValueError('Official artifact checksum does not match pinned release')


def relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or ':' in name or '\\' in name:
        raise ValueError('Unsafe archive path')
    return Path(*path.parts)


def unpack(path, destination):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                target = destination / relative(member.filename)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open('wb') as output:
                        shutil.copyfileobj(source, output)
                    target.chmod((member.external_attr >> 16) & 0o777 or 0o644)
    else:
        with tarfile.open(path) as archive:
            members = {member.name: member for member in archive.getmembers()}
            for member in members.values():
                target = destination / relative(member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                resolved = member
                seen = set()
                while resolved.issym() or resolved.islnk():
                    if resolved.name in seen:
                        raise ValueError('Archive link cycle')
                    seen.add(resolved.name)
                    name = posixpath.normpath(posixpath.join(posixpath.dirname(resolved.name), resolved.linkname)) if resolved.issym() else resolved.linkname
                    relative(name)
                    resolved = members[name]
                if not resolved.isfile():
                    raise ValueError('Unsupported archive entry')
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(resolved) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(resolved.mode & 0o777)


def build(target, destination):
    pin = json.loads((PROJECT / 'components/analysis-core/manifest.json').read_text())
    java_spec = pin['java']['targets'][target]
    with tempfile.TemporaryDirectory(prefix='huntmob-analysis-build-') as folder:
        temporary = Path(folder)
        for name, spec in (('engine', pin['engine']), ('java', java_spec)):
            artifact = temporary / (name + '.archive')
            download(spec, artifact)
            unpack(artifact, temporary / name)
        bundle = temporary / 'bundle'
        bundle.mkdir()
        engine = temporary / 'engine'
        jars = sorted(engine.rglob('jadx-*-all.jar'))
        if len(jars) != 1:
            raise ValueError('Expected one embedded decompiler JAR')
        shutil.copy2(jars[0], bundle / 'engine.jar')
        shutil.copy2(next(engine.rglob('LICENSE')), bundle / 'LICENSE-jadx.txt')
        runtime_java = next((temporary / 'java').rglob('java.exe' if target.startswith('windows-') else 'java'))
        java_home = runtime_java.parent.parent
        shutil.copytree(java_home, bundle / 'java')
        files = {str(path.relative_to(bundle)).replace(os.sep, '/'): digest(path) for path in bundle.rglob('*') if path.is_file()}
        manifest = {'schema': 1, 'target': target, 'engine_version': pin['engine']['version'],
                    'java_version': pin['java']['version'], 'files': files,
                    'java_executable': 'java/bin/java.exe' if target.startswith('windows-') else 'java/bin/java'}
        (bundle / 'bundle.json').write_text(json.dumps(manifest, indent=2))
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ValueError('Bundle already exists; choose a new output directory')
        shutil.copytree(bundle, destination)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', default=host_target())
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    destination = args.output or PROJECT / 'src/huntmob/_analysis' / args.target
    result = build(args.target, destination)
    print(json.dumps({'target': args.target, 'files': len(result['files']), 'bundle': str(destination)}))
