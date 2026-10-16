#!/usr/bin/env python3
"""Bounded x86_64 USB companion for an isolated, authorized iOS restore.

No physical USB passthrough. Prepared private research image only.
"""
import argparse
import hashlib
import json
import socket
import subprocess
import time
from pathlib import Path

RESEARCH = Path.home()/'.huntmob/research'
ENGINE_SHA = 'd4764dd8498302551316ee6eaab2045e8bb9de24a183e120698afbdbc30b39da'
IMAGE_SHA = '6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2'


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024*1024),b''):
            value.update(chunk)
    return value.hexdigest()


def command(engine, root, log, controller='ehci'):
    if controller not in {'ehci','xhci'}:
        raise ValueError('Unsupported virtual USB controller.')
    usb = ['-usb','-device','usb-ehci,id=ehci'] if controller == 'ehci' else ['-device','qemu-xhci,id=xhci']
    return [str(engine), '-M','q35','-accel','tcg,thread=multi','-cpu','max',
            '-m','3G','-smp','4','-display','none','-monitor','none',
            '-qmp',f'unix:{root}/qmp.sock,server=on,wait=off',
            '-serial',f'file:{log}', *usb,
            '-device',f'usb-tcp-remote,bus={controller}.0,conn-type=unix,conn-addr={root}/usb.sock',
            '-drive',f'file={root}/disk.qcow2,format=qcow2,if=virtio',
            '-drive',f'file={root}/seed-fixed.iso,format=raw,media=cdrom',
            '-nic','user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:33227-:22',
            '-audiodev','none,id=lab-audio']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab',action='store_true',required=True)
    parser.add_argument('--seconds',type=int,choices=range(10,1801),default=1800,metavar='10..1800')
    parser.add_argument('--controller',choices=['ehci','xhci'],default='ehci')
    args=parser.parse_args()
    engine=RESEARCH/'Inferno/build-huntmob-x86/qemu-system-x86_64'
    root=RESEARCH/'ios-companion-x86_64'
    if engine.is_symlink() or digest(engine)!=ENGINE_SHA:
        raise SystemExit('Companion engine does not match its validated receipt.')
    if digest(RESEARCH/'firmware/ubuntu-24.04-server-cloudimg-amd64.img')!=IMAGE_SHA:
        raise SystemExit('Companion image does not match the official checksum.')
    if root.is_symlink() or not root.is_dir():
        raise SystemExit('Prepared owned companion directory unavailable.')
    for name in ['disk.qcow2','seed-fixed.iso']:
        if (root/name).is_symlink() or not (root/name).is_file():
            raise SystemExit('Prepared companion disk unavailable.')
    try:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(1);probe.connect(str(root/'qmp.sock'))
            raise SystemExit('Owned companion is already running.')
    except OSError:
        pass
    stamp=time.strftime('%Y%m%d-%H%M%S')
    log=root/f'serial-{stamp}.log'
    launch=command(engine,root,log,args.controller)
    started=time.monotonic()
    reason='engine-exited'
    with (root/f'qemu-{stamp}.log').open('xb') as output:
        process=subprocess.Popen(launch,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True,cwd=engine.parent)
        try:
            process.wait(timeout=args.seconds)
        except (subprocess.TimeoutExpired,KeyboardInterrupt):
            reason='bounded-observation-ended'
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill();process.wait(timeout=10)
        finally:
            if process.poll() is None: process.kill();process.wait(timeout=10)
    receipt={'command':launch,'controller':args.controller,'engine_sha256':ENGINE_SHA,'image_sha256':IMAGE_SHA,
             'elapsed_seconds':round(time.monotonic()-started,2),'exit_code':process.returncode,
             'stop_reason':reason,'physical_usb_passthrough':False,'full_restore_validated':False}
    target=root/f'run-{stamp}.json';target.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':str(target),'exit_code':process.returncode}))

if __name__=='__main__': main()
