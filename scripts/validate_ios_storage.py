#!/usr/bin/env python3
"""Inspect an owned research checkpoint without starting or modifying a VM."""
import argparse,json
from pathlib import Path
from huntmob.ios_storage_validation import validate_checkpoint
from huntmob.dynamic_runtime import private_json

parser=argparse.ArgumentParser()
parser.add_argument('--checkpoint',type=Path,default=Path.home()/'.huntmob/research/ios-vms/native-20261014-protected-data-checkpoint')
parser.add_argument('--output',type=Path)
args=parser.parse_args()
try:
    result=validate_checkpoint(args.checkpoint)
except (OSError,ValueError,TypeError) as error:
    print(json.dumps({'ready':False,'state':'invalid','reason':str(error) if isinstance(error,ValueError) else 'Checkpoint não pôde ser lido.'}));raise SystemExit(2)
if args.output:private_json(args.output,result)
print(json.dumps(result,indent=2,ensure_ascii=False))
raise SystemExit(1 if result['state']=='failed' or not result['cohort_matches'] else 2)
