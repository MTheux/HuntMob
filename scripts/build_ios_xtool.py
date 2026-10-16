#!/usr/bin/env python3
"""Build explicitly trusted local SwiftPM sources with xtool, without signing."""
import argparse
import json
import subprocess
from pathlib import Path
from huntmob.ios_xtool import executable

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('project',type=Path)
parser.add_argument('--trusted-source',action='store_true',required=True,help='Confirm that Package.swift and its build plugins are trusted')
parser.add_argument('--configuration',choices=['debug','release'],default='debug')
args=parser.parse_args()
project=args.project.resolve(strict=True)
if not project.is_dir() or not (project/'Package.swift').is_file() or not (project/'xtool.yml').is_file():
    parser.error('Project requires Package.swift and xtool.yml')
try:
    result=subprocess.run([executable(),'dev','build','--configuration',args.configuration,'--ipa'],cwd=project,stdin=subprocess.DEVNULL,timeout=600)
except (ValueError,OSError,subprocess.TimeoutExpired) as error:
    parser.exit(1,'Build not confirmed: '+str(error)+'\n')
print(json.dumps({'ok':result.returncode==0,'signed':False,'installed':False,'project':str(project)}))
raise SystemExit(result.returncode)
