#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: validate own-profile C6 inventory validation and format denial.
# Target: new paused t8030 process and disposable public fixture disks only.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""Real-controller C6 checks without CPU execution, private disks, or Keychain.

Mode 1 is an own-model read-only inventory contract, not Apple provisioning.
No disk, key, firmware, or arbitrary engine input is accepted.
"""
import argparse
import hashlib
import json
import struct
import tempfile
from pathlib import Path

import verify_virtual_sep_ans_mmio as mmio
import boot_ios_virtual_profile as boot

PATCH = 'ans-virtual-namespace-layout-validation.patch'
TYPES = (0, 2, 3, 4, 5, 6, 8)
SIZES = (mmio.DISK_BYTES, 8*1024**2, 128*1024, 8*1024, 8*1024, 4*1024, 1024**2)


def payload(sentinel=True):
    out = bytearray(4096)
    struct.pack_into('<I', out, 0, 7)
    for index, (kind, size) in enumerate(zip(TYPES, SIZES)):
        struct.pack_into('<III', out, 4 + index*12, index+1, kind,
                         0 if sentinel and index == 0 else size//4096)
    return bytes(out)


def mutate(data, offset, value):
    out = bytearray(data)
    struct.pack_into('<I', out, offset, value)
    return bytes(out)


def cases():
    good = payload()
    rows = [
        ('valid-existing-sentinel', good, {}, 0),
        ('valid-existing-explicit-size', payload(False), {}, 0),
        ('valid-existing-repeat', good, {}, 0),
    ]
    for name, offset, value in (
        ('count-zero', 0, 0), ('count-too-large', 0, 342),
        ('count-omits-existing', 0, 6), ('count-extra', 0, 8),
        ('duplicate-id', 4+12, 1), ('nonsequential-id', 4+12, 3),
        ('wrong-first-type', 8, 1), ('wrong-type', 8+12, 99),
        ('wrong-first-size', 12, SIZES[0]//4096+1),
        ('wrong-size', 12+12, SIZES[1]//4096+1),
        ('zero-nonfirst-size', 12+12, 0),
        ('nonzero-tail', 4+7*12, 1), ('nonzero-last-word', 4092, 1),
    ):
        rows.append((name, mutate(good, offset, value), {}, 0x4002))
    for name, options, status in (
        ('mode0-valid-buffer', {'mode': 0}, 0x4002),
        ('mode0-unmapped-buffer', {'mode': 0, 'pointer': 0}, 0x4002),
        ('mode2', {'mode': 2}, 0x4002),
        ('mode-allbits', {'mode': 0xffffffff}, 0x4002),
        ('unknown-flag20', {'flags': 0x20}, 0x4002),
        ('sgl-flag40', {'flags': 0x40}, 0x4002),
        ('fused-flag01', {'flags': 1}, 2),
        ('metadata-pointer', {'mptr': mmio.DATA}, 0x4002),
        ('reserved-command', {'res1': 1}, 0x4002),
        ('unexpected-nsid', {'nsid': 1}, 0x4002),
        ('reserved-cdw11', {'cdw11': 1}, 0x4002),
        ('reserved-cdw15', {'cdw15': 1}, 0x4002),
        ('unmapped-dma', {'pointer': 0}, 4),
        ('mmio-dma', {'pointer': mmio.ANS}, 4),
    ):
        rows.append((name, good, options, status))
    return rows


def admin(devices, options):
    options = dict(options)
    out = bytearray(mmio.io.admin_command(0xc6, devices.cid,
                    options.pop('pointer', mmio.DATA), options.pop('mode', 1), 0))
    if 'flags' in options:
        out[1] = options.pop('flags')
    for key, offset, fmt in (('nsid', 4, '<I'), ('res1', 8, '<Q'),
                             ('mptr', 16, '<Q'), ('cdw11', 44, '<I'),
                             ('cdw15', 60, '<I')):
        if key in options:
            struct.pack_into(fmt, out, offset, options.pop(key))
    mmio.require(not options, 'Unsupported fixture option')
    return bytes(out)


def fingerprints(folder):
    return {p.name: boot.digest(p) for p in folder.glob('*.raw')}


def run():
    candidate = boot.CANDIDATE/'build/qemu-system-aarch64'
    receipt = json.loads((boot.CANDIDATE/'build-receipt.json').read_text())
    source_hashes = boot.reviewed_sources(boot.CANDIDATE/'source', boot.PATCHES)
    mmio.require(receipt['binary_sha256'] == boot.digest(candidate) and
                 source_hashes == receipt['reviewed_source_sha256'],
                 'Only the reviewed candidate with namespace validation may run')
    mmio.require(PATCH in receipt['patch_sha256'] and PATCH in boot.PATCHES,
                 'Namespace validation patch is required')
    rows = cases()
    results = []
    startup_changes = set()
    # Admin queues have 16 entries; preserve the existing bounded transport and
    # use fresh disposable processes instead of reusing or wrapping an old SQ.
    with tempfile.TemporaryDirectory(prefix='hm-nsguard-', dir='/tmp') as directory:
        root = Path(directory)
        for batch, start in enumerate(range(0, len(rows), 12)):
            folder = root/str(batch)
            folder.mkdir()
            argv, _ = mmio.prepare(candidate, folder)
            public = bytes(range(256))*(mmio.DISK_BYTES//256)
            (folder/'namespace-1.raw').write_bytes(public)
            originals = fingerprints(folder)
            machine = mmio.PausedMachine(argv, folder)
            try:
                devices = mmio.Devices(machine)
                devices.initialize_nvme()
                # apple-nvram initializes its new disposable namespace during
                # realize. Drain all namespace backends before taking the C6
                # baseline; record startup changes separately from C6 effects.
                flush = bytearray(mmio.io.io_command(0, devices.cid))
                struct.pack_into('<I', flush, 4, 0xffffffff)
                devices.submit('flush-startup-all-namespaces', bytes(flush))
                before_c6 = fingerprints(folder)
                startup_changes.update(name for name in originals
                                       if originals[name] != before_c6[name])
                mmio.require(startup_changes <= {'namespace-5.raw'},
                             'Unexpected device-startup backing mutation')
                originals = before_c6
                # Guard both sides and a separate full page of ordinary RAM.
                left, right = bytes([0xb6])*64, bytes([0xc7])*4096
                machine.write(mmio.DATA-64, left)
                machine.write(mmio.DATA+4096, right)
                for name, data, options, status in rows[start:start+12]:
                    machine.write(mmio.DATA, data)
                    devices.submit(name, admin(devices, options), queue=0, status=status)
                    mmio.require(machine.read(mmio.DATA, 4096) == data, 'C6 changed input DMA: '+name)
                    mmio.require(machine.read(mmio.DATA-64, len(left)) == left and
                                 machine.read(mmio.DATA+4096, len(right)) == right,
                                 'C6 changed DMA sentinels: '+name)
                    mmio.require((folder/'namespace-1.raw').read_bytes() == public,
                                 'C6 changed complete 16 MiB backing: '+name)
                    mmio.require(fingerprints(folder) == originals,
                                 'C6 changed an existing backing: '+name)
                    results.append({'name': name, 'status': status})
                # A clear I/O remains functional after every rejected command;
                # a read followed by Flush proves the admin path did not damage
                # ordinary queue operation. This read targets public disk LBA7.
                expected = public[mmio.io.LBA*4096:(mmio.io.LBA+2)*4096]
                devices.storage('clear-read-after-C6', 2,
                                before=bytes([0x98])*8192, after=expected)
                flush = bytearray(mmio.io.io_command(0, devices.cid))
                struct.pack_into('<I', flush, 4, 0xffffffff)
                devices.submit('flush-after-C6-all-namespaces', bytes(flush))
                mmio.require(machine.command('query-status')['running'] is False,
                             'Fixture CPUs must remain paused')
            finally:
                machine.close()
            mmio.require((folder/'namespace-1.raw').read_bytes() == public and
                         fingerprints(folder) == originals,
                         'Backing changed after flush and process shutdown')
    mmio.require(boot.digest(candidate) == receipt['binary_sha256'] and
                 boot.reviewed_sources(boot.CANDIDATE/'source', boot.PATCHES) == source_hashes,
                 'Candidate changed during validation')
    return {
        'schema': 'huntmob.virtual-sep-namespace-validation.v1',
        'engine_sha256': receipt['binary_sha256'],
        'patch_sha256': receipt['patch_sha256'][PATCH],
        'source_ctrl_sha256': source_hashes['hw/nvme/ctrl.c'],
        'harness_sha256': boot.digest(Path(__file__)),
        'public_fixture_only': True, 'cpus_paused': True,
        'firmware_executed': False, 'Keychain_accessed': False,
        'inventory': [{'nsid': i+1, 'nstype': kind, 'blocks4096': size//4096}
                      for i, (kind, size) in enumerate(zip(TYPES, SIZES))],
        'cases': results, 'case_count': len(results),
        'accepted_existing_layouts': sum(r['status'] == 0 for r in results),
        'DMA_and_sentinels_unchanged': True,
        'entire_16MiB_namespace_unchanged': True,
        'all_nine_backings_unchanged_after_flush_shutdown': True,
        'all_nine_invariant_baseline': 'after device realize and initial all-namespace flush',
        'device_startup_changes_before_C6': sorted(startup_changes),
        'clear_reads_and_flush_after_rejections_passed': True,
        'apple_hardware_mode1_semantics_validated': False,
        'native_C6_flags_and_inventory_validated': False,
        'flag20_unsupported': True,
        'no_namespace_create_resize_format_or_backend_write': True,
        'ready': False, 'native_storage_validated': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    mmio.require(not args.output.exists(), 'Never overwrite an existing receipt')
    result = run()
    with args.output.open('x') as out:
        json.dump(result, out, indent=2)
        out.write('\n')
    print(json.dumps({'case_count': result['case_count'], 'ready': result['ready'],
                      'engine_sha256': result['engine_sha256']}))


if __name__ == '__main__':
    main()
