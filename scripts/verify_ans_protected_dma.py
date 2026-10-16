#!/usr/bin/env python3
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: reject protected transfers to MMIO/unassigned guest addresses.
# Target: new ARM64 virt process, public fixtures and temporary 16 MiB disk.
# WARNING: Unauthorized use is illegal.
"""Actual-controller checks, without iOS firmware or user-provided storage.

The negative control intentionally demonstrates the preceding model's behavior
on the same disposable fixture. It never tests physical devices or host MMIO.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import verify_ans_unwrapped_xts as raw
import verify_ans_wrapped_xts as wrapped

MARKER = 'HUNTMOB_ANS_PROTECTED_DMA_PASS'
MMIO = 0x09000000  # Guest virt PL011, serial disabled; never host MMIO.
UNASSIGNED = 0x44000000  # First byte beyond this fixture's 64 MiB RAM.
DISK_BYTES = 16 * 1024 * 1024


def rows(mode, ciphertext, negative):
    flags, extension = ((8, bytes(32) + raw.SYNTHETIC_KEY) if mode == 'raw'
                        else (4, wrapped.envelope()))
    steps = wrapped.queues()
    steps.append({'name': 'valid_initial_write', 'command': raw.io_command(
        1, 3, flags=flags, extension=extension), 'status': 0,
        'before': raw.PLAINTEXT, 'after': raw.PLAINTEXT})
    cid = 4
    variants = (
        ('first_mmio', MMIO, raw.DATA_ADDRESS + 4096),
        ('first_unassigned', UNASSIGNED, raw.DATA_ADDRESS + 4096),
        ('tail_mmio', raw.DATA_ADDRESS, MMIO),
        ('tail_unassigned', raw.DATA_ADDRESS, UNASSIGNED),
    )
    for label, first, second in variants:
        for opcode in (1, 2):
            command = bytearray(raw.io_command(opcode, cid, flags=flags, extension=extension))
            struct.pack_into('<QQ', command, 24, first, second)
            sentinel = bytes([0x80 + cid]) * 8192
            steps.append({'name': label + ('_write' if opcode == 1 else '_read'),
                          'command': bytes(command), 'status': 0 if negative else 4,
                          'before': sentinel, 'after': sentinel,
                          'invalid_dma': True})
            cid += 1
            if negative:
                # One accepted invalid write suffices as the negative control;
                # its whole temporary backing is checked independently below.
                return steps
            steps.append({'name': label + '_backing_check',
                          'command': raw.io_command(2, cid), 'status': 0,
                          'before': bytes([0x39]) * 8192, 'after': ciphertext})
            cid += 1
    raw.require(len(steps) < 64, 'Synthetic fixture exceeds queue bound')
    return steps


def exercise(engine, mode, negative):
    ciphertext = raw.oracle() if mode == 'raw' else wrapped.oracle()
    steps = rows(mode, ciphertext, negative)
    with tempfile.TemporaryDirectory(prefix='huntmob-ans-dma-public-') as directory:
        root = Path(directory)
        disk = root / 'synthetic.raw'
        disk.write_bytes(bytes(DISK_BYTES))
        context = root / 'public-context.bin'
        context.write_bytes(wrapped.PUBLIC_CONTEXT)
        os.chmod(context, 0o600)
        source, obj, image = (root / ('fixture' + ext) for ext in ('.S', '.o', '.bin'))
        source.write_text(raw.fixture(steps).replace('HUNTMOB_ANS_UNWRAPPED_XTS_PASS', MARKER))
        clang = shutil.which('clang') or 'clang'
        objcopy = shutil.which('llvm-objcopy') or '/opt/homebrew/opt/llvm/bin/llvm-objcopy'
        for command in ([clang, '--target=aarch64-none-elf', '-c', str(source), '-o', str(obj)],
                        [objcopy, '-O', 'binary', str(obj), str(image)]):
            subprocess.run(command, check=True, capture_output=True, timeout=25)
        result = subprocess.run([
            str(engine), '-M', 'virt,highmem=off', '-cpu', 'max', '-accel', 'tcg',
            '-m', '64', '-display', 'none', '-serial', 'none', '-monitor', 'none',
            '-nic', 'none', '-kernel', str(image),
            '-semihosting-config', 'enable=on,target=native',
            '-drive', f'file={disk},format=raw,if=none,id=testdisk',
            '-object', f'secret,id=public-context,file={context},format=raw',
            '-device', 'nvme,serial=HuntMobDMA,addr=1,id=testnvme,is-apple-ans=on,'
            'apple-ans-lab-unwrapped-xts=on,apple-ans-lab-wrapped-xts=on,'
            'apple-ans-lab-wrapped-xts-secret=public-context',
            '-device', 'nvme-ns,drive=testdisk,bus=testnvme,nsid=1,'
            'logical_block_size=4096,physical_block_size=4096',
        ], capture_output=True, text=True, timeout=25)
        output = result.stdout + result.stderr
        raw.require(result.returncode == 0 and MARKER in output,
                    'Protected DMA validation failed: ' + output[-1500:])
        raw.require(all(f'STEP_{i}_{r["name"]}_OK' in output for i, r in enumerate(steps)),
                    'Missing guest step receipt')
        expected = bytearray(DISK_BYTES)
        expected[raw.LBA * 4096:(raw.LBA + 2) * 4096] = ciphertext
        stored = disk.read_bytes()
        if negative:
            raw.require(stored != expected, 'Negative control did not change the backing')
        else:
            raw.require(stored == expected, 'Invalid DMA changed the full temporary backing')
        return {'mode': mode, 'completed_requests': len(steps),
                'invalid_dma_requests': sum(bool(r.get('invalid_dma')) for r in steps),
                'invalid_dma_status': '0x0000' if negative else '0x0004',
                'invalid_dma_accepted': negative,
                'ram_sentinels_unchanged': True,
                'whole_backing_matches_oracle': stored == expected,
                'backing_sha256': hashlib.sha256(stored).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--negative-control', action='store_true')
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    paths = (Path(__file__).resolve(), Path(raw.__file__), Path(wrapped.__file__))
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = hashlib.sha256(engine.read_bytes()).hexdigest()
    reports = [exercise(engine, mode, args.negative_control) for mode in ('raw', 'wrapped')]
    raw.require(hashlib.sha256(engine.read_bytes()).hexdigest() == before, 'Engine changed')
    raw.require(all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p.name] for p in paths),
                'Test source changed')
    print(json.dumps({'version': 1, 'ok': True, 'ready': False,
                      'native_provider_validated': False, 'hardware_abi_validated': False,
                      'negative_control': args.negative_control,
                      'engine_sha256': before, 'test_source_sha256': hashes,
                      'scope': 'new isolated virt processes and disposable public-fixture backing',
                      'reports': reports}, indent=2))


if __name__ == '__main__':
    main()
