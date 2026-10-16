#!/usr/bin/env python3
"""Assemble a platform-specific HuntMob wheel with its own engine, JRE and UI."""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from build_analysis_bundle import PROJECT, build, host_target, digest

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', default=host_target())
    parser.add_argument('--output', type=Path, default=PROJECT / 'artifacts/releases')
    args = parser.parse_args()
    destination = args.output.resolve() / args.target
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='huntmob-release-') as temporary:
        stage = Path(temporary)
        shutil.copy2(PROJECT / 'pyproject.toml', stage / 'pyproject.toml')
        tags = {'mac-aarch64':'macosx_11_0_arm64','mac-x64':'macosx_10_15_x86_64','windows-x64':'win_amd64','windows-aarch64':'win_arm64','linux-x64':'linux_x86_64','linux-aarch64':'linux_aarch64'}
        (stage / 'setup.cfg').write_text('[bdist_wheel]\nplat_name = ' + tags[args.target] + '\n')
        shutil.copytree(PROJECT / 'src', stage / 'src', ignore=shutil.ignore_patterns('_analysis', '__pycache__', '*.egg-info'))
        shutil.copytree(PROJECT / 'web', stage / 'src/huntmob/_web')
        shutil.copytree(PROJECT / 'components/scrcpy', stage / 'src/huntmob/_video')
        source = PROJECT / 'src/huntmob/_analysis' / args.target
        if source.is_dir():
            shutil.copytree(source, stage / 'src/huntmob/_analysis' / args.target)
        else:
            build(args.target, stage / 'src/huntmob/_analysis' / args.target)
        subprocess.run([sys.executable, '-m', 'pip', 'wheel', str(stage), '--no-deps', '--wheel-dir', str(destination)], check=True, timeout=300)
    wheel = max(destination.glob('huntmob-*.whl'), key=lambda path: path.stat().st_mtime_ns)
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        prefix = 'huntmob/_analysis/' + args.target + '/'
        for name in ('bundle.json', 'engine.jar', 'java/bin/java.exe' if args.target.startswith('windows-') else 'java/bin/java'):
            if prefix + name not in names:
                raise RuntimeError('Release is missing embedded runtime: ' + name)
        if 'huntmob/_web/index.html' not in names:
            raise RuntimeError('Release is missing UI')
    metadata = {'target': args.target, 'wheel': wheel.name, 'size': wheel.stat().st_size, 'sha256': digest(wheel), 'engine': 'jadx 1.5.5', 'runtime': 'Eclipse Temurin 21.0.11+10'}
    (destination / 'release.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps(metadata))
