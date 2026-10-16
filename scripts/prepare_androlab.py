"""Prepare the reviewed loopback-only AndroLab training backend."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


def main():
    source = Path(__file__).resolve().parents[1] / 'components/androlab'
    folder = Path.home() / '.huntmob/runtime/androlab'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = json.loads((source / 'upstream.json').read_text())
    for name in ('app.py', 'models.py', 'database.py', 'LICENSE', 'upstream.json'):
        shutil.copyfile(source / name, folder / name)
        (folder / name).chmod(0o600)
    database = folder / 'mydb.db'
    if not database.exists():
        url = 'https://raw.githubusercontent.com/dineshshetty/Android-InsecureBankv2/' + receipt['commit'] + '/AndroLabServer/mydb.db'
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != receipt['original_sha256']['mydb.db']:
            raise ValueError('Database digest mismatch; preparation stopped')
        with os.fdopen(os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
            output.write(data)
    environment = folder / '.venv'
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    uv = shutil.which('uv')
    if uv:
        if not python.exists():
            subprocess.run((uv, 'venv', str(environment), '--python', sys.executable), check=True, timeout=180)
        subprocess.run((uv, 'pip', 'install', '--python', str(python), 'Flask==3.1.3', 'SQLAlchemy==1.4.54'), check=True, timeout=300)
    else:
        if not python.exists():
            subprocess.run((sys.executable, '-m', 'venv', str(environment)), check=True, timeout=180)
        subprocess.run((str(python), '-m', 'pip', 'install', 'Flask==3.1.3', 'SQLAlchemy==1.4.54'), check=True, timeout=300)
    print('AndroLab prepared. HuntMob will start it on 127.0.0.1:8888 when this lab uses capture or Send.')


if __name__ == '__main__':
    main()
