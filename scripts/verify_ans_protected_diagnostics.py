#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: validate metadata-only ANS protected-I/O diagnostic categories.
# Target: new paused t8030 process and script-created public fixtures only.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""No VM/private-disk/Keychain inputs, firmware execution, or semantic changes.

A public fixture supplies the root and standard crypto oracle. This validates
trace categories, format metadata and controller behavior, not Apple hardware or
native Data Protection. The only permitted backing change is one known write.
"""
import argparse
from collections import Counter
import hashlib
import json
import re
import struct
import tempfile
from pathlib import Path

import boot_ios_virtual_profile as boot
import verify_virtual_sep_ans_mmio as mmio

PATCH = 'ans-protected-gate-diagnostics.patch'
FRAME_PATCH = 'ans-protected-frame-diagnostics.patch'
FORMAT_PATCH = 'ans-wrapped-format-metadata.patch'
EVENT = 'pci_nvme_apple_ans_protected_gate'
FORMAT_EVENT = 'pci_nvme_apple_ans_frame_format'
STAGES = {'sq-context': {'extension-unavailable', 'accepted', 'provider-unavailable',
                         'frame-unsupported', 'frame-flags-unsupported',
                         'frame-reserved-unsupported', 'context-unavailable'},
          'protected-gate': {'xts-key-invalid', 'flags', 'iosqe', 'context-unavailable',
                             'context-stale', 'namespace-format', 'namespace-features',
                             'metadata-pointer', 'control-fua', 'control-lr',
                             'control-other', 'transfer-size', 'unit-overflow'}}


def parse_trace(path):
    events, formats = [], []
    for line in path.read_text().splitlines():
        metadata = re.fullmatch(FORMAT_EVENT+r' sqid=(\d+) cid=(\d+) format=0x([0-9a-f]{8}) reserved_zero=([01])', line)
        if metadata:
            sqid, cid, word, reserved_zero = metadata.groups()
            mmio.require(int(sqid) == 1, 'Format metadata must target the fixture I/O queue')
            formats.append({'sqid': int(sqid), 'cid': int(cid),
                            'format32': int(word, 16), 'reserved_zero': reserved_zero == '1'})
            continue
        match = re.fullmatch(EVENT+r' sqid=(\d+) cid=(\d+) stage=([a-z-]+) result=([a-z-]+)', line)
        mmio.require(match is not None, 'Trace contains an unexpected event shape')
        sqid, cid, stage, result = match.groups()
        mmio.require(stage in STAGES and result in STAGES[stage], 'Unknown diagnostic category')
        mmio.require(int(sqid) == 1, 'Fixture diagnostics must target only its I/O queue')
        events.append({'sqid': int(sqid), 'cid': int(cid), 'stage': stage, 'result': result})
    return events, formats


def flush_all(devices, name):
    command = bytearray(mmio.io.io_command(0, devices.cid))
    struct.pack_into('<I', command, 4, 0xffffffff)
    devices.submit(name, bytes(command))


def run():
    engine = boot.CANDIDATE/'build/qemu-system-aarch64'
    receipt_path = boot.CANDIDATE/'build-receipt.json'
    receipt = json.loads(receipt_path.read_text())
    source_hashes = boot.reviewed_sources(boot.CANDIDATE/'source', boot.PATCHES)
    mmio.require(receipt.get('state') == 'compiled' and PATCH in receipt['patch_sha256'] and
                 FRAME_PATCH in receipt['patch_sha256'] and
                 FORMAT_PATCH in receipt['patch_sha256'] and
                 receipt['binary_sha256'] == boot.digest(engine) and
                 receipt['reviewed_source_sha256'] == source_hashes,
                 'Only the compiled and source-bound diagnostic candidate may run')
    checks = []
    with tempfile.TemporaryDirectory(prefix='hm-protected-diag-', dir='/tmp') as directory:
        folder = Path(directory)
        argv, originals = mmio.prepare(engine, folder)
        event_file, trace = folder/'events.txt', folder/'trace.log'
        event_file.write_text(EVENT+'\n'+FORMAT_EVENT+'\n')
        argv += ['-trace', 'events='+str(event_file)+',file='+str(trace)]
        machine = mmio.PausedMachine(argv, folder)
        expected = bytearray(mmio.DISK_BYTES)
        try:
            devices = mmio.Devices(machine)
            devices.aess(0x200)
            devices.initialize_nvme()
            devices.program()
            blob = devices.envelope()
            ciphertext = mmio.expected_storage()
            flush_all(devices, 'flush-initialized-backings')
            baseline = {name: boot.digest(folder/name) for name in originals}
            startup_changes = sorted(name for name in originals if originals[name] != baseline[name])
            mmio.require(startup_changes == ['namespace-5.raw'], 'Unexpected device initialization writes')
            left, right = bytes([0xb5])*64, bytes([0xc6])*4096
            machine.write(mmio.DATA-64, left)
            machine.write(mmio.DATA+8192, right)

            def unchanged(name):
                mmio.require(machine.read(mmio.DATA-64, len(left)) == left and
                             machine.read(mmio.DATA+8192, len(right)) == right,
                             'DMA guard changed: '+name)
                mmio.require((folder/'namespace-1.raw').read_bytes() == expected,
                             'Complete public backing differs from expected: '+name)
                mmio.require(all(boot.digest(folder/key) == digest for key, digest in baseline.items()
                                 if key != 'namespace-1.raw'), 'Unrelated backing changed: '+name)

            valid_cid = devices.cid
            devices.storage('valid_control_zero_write', 1, blob,
                            mmio.io.PLAINTEXT, mmio.io.PLAINTEXT)
            expected[mmio.io.LBA*4096:(mmio.io.LBA+2)*4096] = ciphertext
            unchanged('valid_control_zero_write')
            checks.append({'name': 'valid_control_zero_write', 'cid': valid_cid, 'status': 0})
            sentinel = bytes([0x9d])*8192
            fua_cid = devices.cid
            devices.submit('fua_rejected', mmio.io.io_command(1, devices.cid, flags=4,
                           extension=blob, control=0x4000), before=sentinel, after=sentinel, status=0x4002)
            unchanged('fua_rejected')
            checks.append({'name': 'fua_rejected', 'cid': fua_cid, 'status': 0x4002})
            bad_frame = bytearray(blob)
            bad_frame[4] ^= 1
            frame_cid = devices.cid
            devices.storage('reserved_frame_rejected', 1, bytes(bad_frame),
                            sentinel, sentinel, 0x4002)
            unchanged('reserved_frame_rejected')
            checks.append({'name': 'reserved_frame_rejected', 'cid': frame_cid, 'status': 0x4002})
            bad_flags = bytearray(blob)
            bad_flags[0] ^= 1
            flags_cid = devices.cid
            devices.storage('flags_frame_rejected', 1, bytes(bad_flags),
                            sentinel, sentinel, 0x4002)
            unchanged('flags_frame_rejected')
            checks.append({'name': 'flags_frame_rejected', 'cid': flags_cid, 'status': 0x4002})
            bad_tag = bytearray(blob)
            bad_tag[16] ^= 1
            tag_cid = devices.cid
            devices.storage('tag_rejected', 1, bytes(bad_tag), sentinel, sentinel, 0x4002)
            unchanged('tag_rejected')
            checks.append({'name': 'tag_rejected', 'cid': tag_cid, 'status': 0x4002})
            # Confirm failed requests did not revoke a valid public context or
            # damage the ordinary I/O path; only reads follow the accepted write.
            devices.storage('valid_context_read_after_rejections', 2, blob,
                            sentinel, mmio.io.PLAINTEXT)
            devices.storage('independent_ciphertext_read', 2, None, sentinel, ciphertext)
            flush_all(devices, 'flush-all-after-rejections')
            unchanged('flush-all-after-rejections')
            mmio.require(machine.command('query-status')['running'] is False, 'CPUs must remain paused')
        finally:
            machine.close()
        mmio.require((folder/'namespace-1.raw').read_bytes() == expected,
                     'Public backing differs after flush and shutdown')
        mmio.require(all(boot.digest(folder/key) == digest for key, digest in baseline.items()
                         if key != 'namespace-1.raw'), 'Unrelated backing changed after shutdown')
        events, formats = parse_trace(trace)
        expected_events = [
            (valid_cid, 'sq-context', 'accepted'),
            (fua_cid, 'sq-context', 'accepted'),
            (fua_cid, 'protected-gate', 'control-fua'),
            (frame_cid, 'sq-context', 'frame-reserved-unsupported'),
            (frame_cid, 'protected-gate', 'context-unavailable'),
            (flags_cid, 'sq-context', 'frame-flags-unsupported'),
            (flags_cid, 'protected-gate', 'context-unavailable'),
            (tag_cid, 'sq-context', 'context-unavailable'),
            (tag_cid, 'protected-gate', 'context-unavailable'),
            (tag_cid+1, 'sq-context', 'accepted'),
        ]
        mmio.require([(row['cid'], row['stage'], row['result']) for row in events] == expected_events,
                     'Exact diagnostic event sequence differs from the expected categories')
        mmio.require(formats == [
            {'sqid': 1, 'cid': frame_cid, 'format32': mmio.FLAGS, 'reserved_zero': False},
            {'sqid': 1, 'cid': flags_cid, 'format32': mmio.FLAGS ^ 1, 'reserved_zero': True},
        ], 'Format metadata differs from the two exact public malformed fixtures')
        trace_hash = boot.digest(trace)
        backing_hash = hashlib.sha256(expected).hexdigest()
    mmio.require(boot.digest(engine) == receipt['binary_sha256'] and
                 boot.reviewed_sources(boot.CANDIDATE/'source', boot.PATCHES) == source_hashes,
                 'Candidate changed during public validation')
    return {'schema': 'huntmob.ans.protected-diagnostics.v3',
            'engine_sha256': receipt['binary_sha256'],
            'build_receipt_sha256': boot.digest(receipt_path),
            'patch_sha256': receipt['patch_sha256'][PATCH],
            'frame_patch_sha256': receipt['patch_sha256'][FRAME_PATCH],
            'format_patch_sha256': receipt['patch_sha256'][FORMAT_PATCH],
            'source_ctrl_sha256': source_hashes['hw/nvme/ctrl.c'],
            'harness_sha256': boot.digest(Path(__file__)),
            'checks': checks, 'exact_events': events,
            'exact_public_format_events': formats,
            'event_counts': dict(Counter(row['stage']+'/'+row['result'] for row in events)),
            'trace_sha256': trace_hash, 'public_backing_sha256': backing_hash,
            'public_fixture_only': True, 'firmware_executed': False, 'cpus_paused': True,
            'private_profile_accessed': False, 'Keychain_accessed': False,
            'startup_changes_before_test': startup_changes,
            'other_eight_backings_unchanged': True,
            'entire_16MiB_backing_matches_single_accepted_ciphertext_write': True,
            'rejected_requests_left_DMA_and_backing_unchanged': True,
            'DMA_guard_sentinels_unchanged': True,
            'trace_has_only_allowed_metadata': True,
            'numeric_trace_fields': ['sqid', 'cid', 'format32', 'reserved_zero'],
            'remaining_60_frame_bytes_logged': False,
            'native_Data_Protection_validated': False, 'Apple_hardware_equivalent': False,
            'ready': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    mmio.require(not args.output.exists(), 'Never overwrite an existing receipt')
    result = run()
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({'engine_sha256': result['engine_sha256'],
                      'gate_event_count': len(result['exact_events']),
                      'format_event_count': len(result['exact_public_format_events']), 'ready': False}))


if __name__ == '__main__':
    main()
