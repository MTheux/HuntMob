"""Allowlisted desktop viewer artifacts; no arbitrary file download paths."""
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]/'dist/viewer'
NAME=re.compile(r'huntmob-viewer-[0-9.]+-(?:macos-arm64|windows-x64|linux-x64)\.zip\Z')

def catalog():
    try:
        manifest=json.loads((ROOT/'manifest.json').read_text())
    except (OSError,ValueError):return {'version':'0.1.0','artifacts':[],'reason':'Pacotes ainda não gerados neste worker.'}
    valid=[]
    for item in manifest.get('artifacts',[]):
        if isinstance(item,dict) and NAME.fullmatch(item.get('filename','')):
            path=ROOT/item['filename']
            if path.is_file() and not path.is_symlink() and path.stat().st_size==item.get('size'):
                valid.append({**item,'url':'/api/viewer/download/'+item['filename']})
    return {'version':manifest.get('version'),'artifacts':valid}

def artifact(name):
    if not NAME.fullmatch(name):raise ValueError('Invalid viewer artifact')
    if name not in {item['filename'] for item in catalog()['artifacts']}:raise ValueError('Viewer artifact unavailable')
    return ROOT/name

def byte_range(value,size):
    if not value:return 0,size-1,False
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',value)
    if not match or not any(match.groups()):raise ValueError('Unsatisfiable range')
    first,last=match.groups()
    if not first:
        count=int(last)
        if count<=0:raise ValueError('Unsatisfiable range')
        start=max(0,size-count);end=size-1
    else:
        start=int(first);end=min(int(last),size-1) if last else size-1
    if start>=size or start>end:raise ValueError('Unsatisfiable range')
    return start,end,True
