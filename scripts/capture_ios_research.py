#!/usr/bin/env python3
"""Capture the framebuffer of an owned local experimental VM via private QMP."""
import argparse
import hashlib
import json
import socket
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm', type=Path)
    args = parser.parse_args()
    root = (Path.home()/'.huntmob/research/ios-vms').resolve(strict=True)
    vm = args.vm.resolve(strict=True)
    if args.vm.is_symlink() or vm.parent != root:
        raise SystemExit('Only owned research VM directories are accepted.')
    receipt = json.loads((vm/'receipt.json').read_text())
    if receipt.get('model') != 't8030' or receipt.get('build') != '18A5351d':
        raise SystemExit('Research VM receipt does not match the supported model.')
    name = 'frame-' + str(time.time_ns())
    frame = vm/(name+'.ppm')
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(10)
        connection.connect(str(vm/'qmp.sock'))
        stream = connection.makefile('rwb')
        greeting = json.loads(stream.readline())
        if 'QMP' not in greeting:
            raise SystemExit('QMP handshake failed.')

        def request(execute, arguments=None):
            payload = {'execute': execute}
            if arguments is not None:
                payload['arguments'] = arguments
            stream.write(json.dumps(payload).encode()+b'\n');stream.flush()
            for _ in range(100):
                result = json.loads(stream.readline())
                if 'error' in result:
                    raise RuntimeError('QMP request failed: '+execute)
                if 'return' in result:
                    return result['return']
            raise RuntimeError('QMP response limit reached.')

        request('qmp_capabilities')
        state = request('query-status')
        request('screendump', {'filename': str(frame)})
    data = frame.read_bytes()
    if not data.startswith(b'P6') or len(data) > 16*1024*1024:
        raise SystemExit('Unexpected framebuffer format or size.')
    evidence = {'schema':1,'vm':str(vm),'frame':str(frame),
                'sha256':hashlib.sha256(data).hexdigest(),'qmp_status':state,
                'framebuffer_captured':True,'springboard_validated':False,
                'note':'Frame capture does not establish a usable UI or app execution.'}
    (vm/(name+'.json')).write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence))


if __name__ == '__main__':
    try:
        main()
    except OSError:
        raise SystemExit('Capture unavailable; the owned VM may be stopped or its private socket unavailable.')
