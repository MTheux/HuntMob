#!/usr/bin/env python3
"""Archive previously packaged desktop clients and create a download manifest."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
output=root/'dist/viewer';output.mkdir(parents=True,exist_ok=True)
items=[]
for target,arch,label,slug in [('darwin','arm64','macOS · Apple Silicon (.app)','macos-arm64'),('win32','x64','Windows · x64 (.exe)','windows-x64'),('linux','x64','Linux · x64','linux-x64')]:
    source=root/'build/viewer'/f'HuntMob Viewer-{target}-{arch}'
    if not source.is_dir():continue
    artifact=output/f'huntmob-viewer-0.1.0-{slug}.zip'
    if target=='darwin':
        native=root/'build/viewer-native/HuntMob Viewer.app'
        chosen=native if native.is_dir() else source/'HuntMob Viewer.app'
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(chosen),str(artifact)],check=True,timeout=120)
    else:
        with zipfile.ZipFile(artifact,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for path in sorted(source.rglob('*')):
                if path.is_file():archive.write(path,path.relative_to(source.parent))
    digest=hashlib.sha256()
    with artifact.open('rb') as stream:
        for data in iter(lambda:stream.read(1024*1024),b''):digest.update(data)
    items.append({'filename':artifact.name,'label':label,'platform':slug,'sha256':digest.hexdigest(),'size':artifact.stat().st_size,'validation':'Pacote gerado; execução pendente','signed_release':False})
(output/'manifest.json').write_text(json.dumps({'version':'0.1.0','artifacts':items},indent=2))
print(json.dumps({'artifacts':len(items),'directory':str(output)}))
