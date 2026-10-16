"""Embedded decompilation engine. No PATH lookup, installation or runtime download."""
from __future__ import annotations
import hashlib
import json
import os
import platform
from pathlib import Path, PurePosixPath


class EmbeddedAnalysis:
    def __init__(self, bundle_root: Path | None = None):
        system = {'Darwin': 'mac', 'Linux': 'linux', 'Windows': 'windows'}.get(platform.system(), 'unsupported')
        arch = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x64', 'AMD64': 'x64'}.get(platform.machine(), 'unsupported')
        self.target = system + '-' + arch
        self.root = bundle_root or Path(__file__).parent / '_analysis' / self.target
        self.manifest = None

    def status(self):
        try:
            manifest = json.loads((self.root / 'bundle.json').read_text())
            if manifest.get('schema') != 1 or manifest.get('target') != self.target:
                raise ValueError('Bundle does not match this worker')
            files = manifest.get('files', {})
            if not files or 'engine.jar' not in files or manifest.get('java_executable') not in files:
                raise ValueError('Incomplete embedded engine')
            for name, expected in files.items():
                relative = PurePosixPath(name)
                if relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name:
                    raise ValueError('Invalid bundle path')
                path = self.root.joinpath(*relative.parts)
                if not path.resolve().is_relative_to(self.root.resolve()):
                    raise ValueError('Invalid bundle file')
                h = hashlib.sha256()
                with path.open('rb') as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(block)
                if h.hexdigest() != expected:
                    raise ValueError('Embedded engine integrity check failed')
            self.manifest = manifest
            return {'ready': True, 'provider': 'huntmob-embedded-analysis', 'target': self.target,
                    'engine_version': manifest['engine_version'], 'java_version': manifest['java_version']}
        except (OSError, ValueError, TypeError, KeyError):
            self.manifest = None
            return {'ready': False, 'provider': 'huntmob-embedded-analysis', 'target': self.target,
                    'reason': 'Motor de análise integrado ausente ou inválido. Reinstale o pacote HuntMob correspondente a este worker.'}

    def command(self, apk: Path, output: Path):
        if not self.manifest:
            if not self.status()['ready']:
                raise RuntimeError('Embedded analysis unavailable')
        return (str(self.root / self.manifest['java_executable']), '-Xmx2048m', '-Djava.awt.headless=true',
                '-cp', str(self.root / 'engine.jar'), 'jadx.cli.JadxCLI', '-j', '2',
                '--output-dir', str(output), str(apk))

    def environment(self):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {'JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'CLASSPATH'}}
        environment['JAVA_HOME'] = str(self.root / 'java')
        return environment
