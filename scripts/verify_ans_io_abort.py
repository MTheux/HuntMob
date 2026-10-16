#!/usr/bin/env python3
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: cancel a pending synthetic raw-XTS read without returning plaintext.
# Target: new ARM64 virt process and temporary 16 MiB disk; never an iOS image.
# WARNING: Unauthorized use is illegal.
"""Exercise actual asynchronous NVMe abort with throttled synthetic block I/O."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from verify_ans_unwrapped_xts import (
    CLEAR, FILE_UNIT, LBA, SYNTHETIC_KEY, UNIT_SIZE, admin_command, fixture,
    io_command, oracle, require,
)


def replace_once(text, old, new):
    require(text.count(old) == 1, 'Synthetic assembly template changed')
    return text.replace(old, new)


def abort_fixture():
    sentinel = bytes([0x5b]) * 8192
    records = [
        {'name': 'create_cq', 'queue': 0, 'command': admin_command(
            5, 1, 0x40024000, 1 | 63 << 16, 1), 'status': 0},
        {'name': 'create_sq', 'queue': 0, 'command': admin_command(
            1, 2, 0x40020000, 1 | 63 << 16, 1 | 1 << 16), 'status': 0},
        {'name': 'warm_read', 'command': io_command(2, 3, lba=0, units=1),
         'before': bytes(4096), 'after': CLEAR, 'status': 0},
        {'name': 'aborted_read', 'command': io_command(
            2, 4, flags=8, extension=bytes(32) + SYNTHETIC_KEY),
         'before': sentinel, 'after': sentinel, 'status': 7},
    ]
    asm = fixture(records)
    asm = replace_once(asm, '    mov sp, x0\n', '    mov sp, x0\n    mov w6, #0\n')
    # Post the protected read; preserve its DMA sentinel while an independent
    # admin queue aborts it. The host throttles reads after the warm-up request.
    asm = replace_once(asm, '    mov x2, #1\n    bl .Lsubmit\n    mov w1, #7\n', r'''    mov x2, #1
    mov w6, #1
    bl .Lsubmit
    mov w6, #0
    // Let the block operation enter its asynchronous wait, under one second.
    mrs x8, cntfrq_el0
    mov x9, #20
    udiv x8, x8, x9
    mrs x9, cntvct_el0
    add x8, x8, x9
.Labort_delay:
    mrs x9, cntvct_el0
    cmp x9, x8
    b.lo .Labort_delay
    adr x0, .Labort_command
    mov w1, #0
    mov x2, #2
    bl .Lsubmit
    cbnz w0, .Lfail
    ldr x5, =0x40024010
.Labort_completion:
    ldrh w0, [x5, #14]
    tbz w0, #0, .Labort_completion
    lsr w0, w0, #1
    ldr x3, =0x1000100c
    mov w4, #2
    str w4, [x3]
    dsb sy
    mov w1, #7
''')
    asm = replace_once(asm, '    str w4, [x3]\n    ldr x5, =0x40002000\n',
                       '    str w4, [x3]\n    cbnz w6, .Lasync_posted\n    ldr x5, =0x40002000\n')
    asm = replace_once(asm, '.balign 8\n.Lpass:', '.Lasync_posted:\n    ret\n.balign 8\n.Lpass:')
    abort = admin_command(8, 5, 0, 1 | 4 << 16, 0)
    asm += '\n.balign 8\n.Labort_command:\n    .byte ' + ','.join(map(str, abort)) + '\n'
    return asm


def exercise(engine):
    engine = Path(engine).resolve(strict=True)
    before_engine = hashlib.sha256(engine.read_bytes()).hexdigest()
    sources = (Path(__file__).resolve(), Path(__file__).with_name('verify_ans_unwrapped_xts.py'))
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    with tempfile.TemporaryDirectory(prefix='huntmob-ans-abort-') as directory:
        root = Path(directory)
        source, obj, image = (root / ('fixture' + ext) for ext in ('.S', '.o', '.bin'))
        source.write_text(abort_fixture())
        clang = shutil.which('clang') or 'clang'
        objcopy = shutil.which('llvm-objcopy') or '/opt/homebrew/opt/llvm/bin/llvm-objcopy'
        for command in ([clang, '--target=aarch64-none-elf', '-c', str(source), '-o', str(obj)],
                        [objcopy, '-O', 'binary', str(obj), str(image)]):
            subprocess.run(command, check=True, capture_output=True, timeout=25)
        disk = root / 'synthetic.raw'
        content = bytearray(16 * 1024 * 1024)
        content[:4096] = CLEAR
        content[LBA * UNIT_SIZE:(LBA + 2) * UNIT_SIZE] = oracle()
        disk.write_bytes(content)
        result = subprocess.run([
            str(engine), '-M', 'virt,highmem=off', '-cpu', 'max', '-accel', 'tcg',
            '-m', '64', '-display', 'none', '-serial', 'none', '-monitor', 'none',
            '-nic', 'none', '-kernel', str(image),
            '-semihosting-config', 'enable=on,target=native',
            '-drive', f'file={disk},format=raw,if=none,id=testdisk,throttling.bps-read=4096',
            '-device', 'nvme,serial=HuntMobAbort,addr=1,id=testnvme,is-apple-ans=on,apple-ans-lab-unwrapped-xts=on',
            '-device', 'nvme-ns,drive=testdisk,bus=testnvme,nsid=1,logical_block_size=4096,physical_block_size=4096',
            '-trace', 'enable=pci_nvme_apple_ans_complete',
        ], capture_output=True, text=True, timeout=25)
        output = result.stdout + result.stderr
        require(result.returncode == 0 and 'STEP_3_aborted_read_OK' in output
                and 'HUNTMOB_ANS_UNWRAPPED_XTS_PASS' in output,
                'Asynchronous abort validation failed: ' + output[-1800:])
        require(disk.read_bytes() == content, 'Read/abort changed the synthetic backing')
    require(hashlib.sha256(engine.read_bytes()).hexdigest() == before_engine,
            'Engine changed during validation')
    require(all(hashlib.sha256(path.read_bytes()).hexdigest() == source_hashes[path.name]
                for path in sources), 'Synthetic test source changed during validation')
    return {'version': 1, 'ok': True, 'engine_sha256': before_engine,
            'test_source_sha256': source_hashes,
            'scope': 'temporary-synthetic-raw-key-only', 'abort_status': '0x0007',
            'pending_read_dma_unchanged': True, 'full_backing_unchanged': True,
            'file_unit_differs_from_lba': FILE_UNIT != LBA,
            'ready': False, 'wrapped_key_support': False, 'sep_revocation_validated': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    args = parser.parse_args()
    print(json.dumps(exercise(args.engine), indent=2))


if __name__ == '__main__':
    main()
