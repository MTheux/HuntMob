#!/usr/bin/env python3
# AUTHORIZED TESTING ONLY — ISOLATED LAB.
# Target: a new paused t8030 process and disposable public disks only.
"""Separate authenticated-envelope acceptance from DATA-format support.

No private profile, Keychain or arbitrary inputs. An accepted envelope does not
prove hardware equivalence, a supported DATA cipher, or native iOS readiness.
"""
import argparse
import hashlib
import json
import re
import struct
import tempfile
from pathlib import Path

import boot_ios_virtual_profile as boot
import verify_virtual_sep_ans_mmio as m

ENGINE = '41963e2e3704bdae2d15f02d060a6f5ed6266f4d47b95c5aaabc9cc28160cda8'
PATCH = 'ans-authenticated-envelope-data-gate.patch'
NATIVE, LEGACY = 0x1b040, 0x1b140
EVENT = 'pci_nvme_apple_ans_protected_gate'
FORMAT_EVENT = 'pci_nvme_apple_ans_frame_format'


def oracle(flags):
    scope = m.PUBLIC_VM_ID.bytes + b'\x00' + m.PUBLIC_CONTEXT
    cipher = m.cbc(m.kdf('HuntMob.VirtualSEP.v1/inline-wrap', scope), m.PUBLIC_DEK)
    mac = m.cbc(m.kdf('HuntMob.VirtualSEP.v1/inline-auth', scope),
                cipher + bytes(12) + struct.pack('<I', flags))[-16:]
    return struct.pack('<I', flags) + bytes(12) + mac + cipher


def envelope(devices, flags):
    ciphertext = devices.aess(0x206, m.PUBLIC_DEK)
    authentication = devices.aess(8, ciphertext)
    mac = devices.aess(0x88, authentication[-16:] + bytes(12) + struct.pack('<I', flags))[-16:]
    blob = struct.pack('<I', flags) + bytes(12) + mac + ciphertext
    m.require(blob == oracle(flags), 'AESS envelope differs from independent public oracle')
    return blob


def flush(devices):
    command = bytearray(m.io.io_command(0, devices.cid))
    struct.pack_into('<I', command, 4, 0xffffffff)
    devices.submit('flush-all', bytes(command))


def run():
    engine = boot.CANDIDATE/'build/qemu-system-aarch64'
    receipt_file = boot.CANDIDATE/'build-receipt.json'
    receipt = json.loads(receipt_file.read_text())
    sources = boot.reviewed_sources(boot.CANDIDATE/'source', boot.PATCHES)
    m.require(receipt.get('state') == 'compiled' and receipt['binary_sha256'] == ENGINE and
              boot.digest(engine) == ENGINE and PATCH in receipt['patch_sha256'] and
              sources == receipt['reviewed_source_sha256'], 'Only the exact closed-DATA candidate may run')
    checks, expected_events = [], []
    with tempfile.TemporaryDirectory(prefix='hm-format-gate-', dir='/tmp') as directory:
        folder = Path(directory)
        argv, original = m.prepare(engine, folder)
        event_file, trace = folder/'events.txt', folder/'trace.log'
        event_file.write_text(EVENT+'\n'+FORMAT_EVENT+'\n')
        argv += ['-trace', 'events='+str(event_file)+',file='+str(trace)]
        machine = m.PausedMachine(argv, folder)
        expected = bytearray(m.DISK_BYTES)
        try:
            devices = m.Devices(machine)
            devices.aess(0x200)
            devices.initialize_nvme()
            devices.program()
            native, legacy, unknown = (envelope(devices, flags) for flags in (NATIVE, LEGACY, LEGACY ^ 1))
            flush(devices)
            baseline = {key: boot.digest(folder/key) for key in original}
            startup = sorted(key for key in baseline if original[key] != baseline[key])
            m.require(startup == ['namespace-5.raw'], 'Unexpected startup write')
            sentinel = bytes([0x9b])*8192
            left, right = bytes([0xa8])*64, bytes([0xc9])*4096
            machine.write(m.DATA-64, left)
            machine.write(m.DATA+8192, right)

            def invariant():
                m.require((folder/'namespace-1.raw').read_bytes() == expected,
                          'Entire public backing differs from expected')
                m.require(all(boot.digest(folder/key) == value for key, value in baseline.items()
                              if key != 'namespace-1.raw'), 'Unrelated backing changed')
                m.require(machine.read(m.DATA-64, len(left)) == left and
                          machine.read(m.DATA+8192, len(right)) == right, 'DMA guard changed')

            def reject(name, blob, reason, decode, format_word=None):
                for opcode in (1, 2):
                    cid = devices.cid
                    devices.storage(name+('-write' if opcode == 1 else '-read'), opcode,
                                    blob, sentinel, sentinel, 0x4002)
                    if format_word is not None:
                        expected_events.append(('format', cid, format_word, True))
                    expected_events.extend([('gate', cid, 'sq-context', decode),
                                            ('gate', cid, 'protected-gate', reason)])
                    checks.append({'name': name, 'opcode': opcode, 'cid': cid, 'status': 0x4002})
                    invariant()

            reject('authenticated-native-DATA-closed', native, 'data-format-unsupported', 'accepted')
            for name, blob in (('native-to-legacy-no-remac', native), ('legacy-to-native-no-remac', legacy)):
                changed = bytearray(blob)
                changed[1] ^= 1  # Exactly bit0x100; preserve all MAC/cipher bytes.
                reject(name, bytes(changed), 'context-unavailable', 'context-unavailable')
            reject('unknown-format-valid-MAC', unknown, 'context-unavailable',
                   'frame-flags-unsupported', LEGACY ^ 1)
            cid = devices.cid
            devices.storage('legacy-write', 1, legacy, m.io.PLAINTEXT, m.io.PLAINTEXT)
            expected[m.io.LBA*4096:(m.io.LBA+2)*4096] = m.expected_storage()
            expected_events.append(('gate', cid, 'sq-context', 'accepted'))
            invariant()
            cid = devices.cid
            devices.storage('legacy-read', 2, legacy, sentinel, m.io.PLAINTEXT)
            expected_events.append(('gate', cid, 'sq-context', 'accepted'))
            devices.storage('independent-ciphertext-read', 2, None, sentinel, m.expected_storage())
            flush(devices)
            invariant()
            m.require(machine.command('query-status')['running'] is False, 'CPUs unexpectedly executed')
        finally:
            machine.close()
        m.require((folder/'namespace-1.raw').read_bytes() == expected and
                  all(boot.digest(folder/key) == value for key, value in baseline.items()
                      if key != 'namespace-1.raw'), 'Backing differs after flush/shutdown')
        events = []
        for line in trace.read_text().splitlines():
            gate = re.fullmatch(EVENT+r' sqid=1 cid=(\d+) stage=([a-z-]+) result=([a-z-]+)', line)
            fmt = re.fullmatch(FORMAT_EVENT+r' sqid=1 cid=(\d+) format=0x([0-9a-f]{8}) reserved_zero=([01])', line)
            m.require(gate is not None or fmt is not None, 'Unexpected trace shape')
            if gate:
                events.append(('gate', int(gate[1]), gate[2], gate[3]))
            else:
                events.append(('format', int(fmt[1]), int(fmt[2], 16), fmt[3] == '1'))
        m.require(events == expected_events, 'Exact metadata trace sequence differs')
        trace_sha, disk_sha = boot.digest(trace), hashlib.sha256(expected).hexdigest()
    m.require(boot.digest(engine) == ENGINE and boot.reviewed_sources(boot.CANDIDATE/'source', boot.PATCHES) == sources,
              'Engine changed during public validation')
    return {'schema': 'huntmob.ans.authenticated-format-DATA-gate.v1', 'engine_sha256': ENGINE,
            'build_receipt_sha256': boot.digest(receipt_file), 'patch_sha256': receipt['patch_sha256'][PATCH],
            'harness_sha256': boot.digest(Path(__file__)), 'checks': checks,
            'events': events, 'trace_sha256': trace_sha, 'backing_sha256': disk_sha,
            'both_AESS_envelopes_match_independent_oracle': True,
            'native_format_authenticated_but_DATA_read_write_rejected': True,
            'both_cross_flips_without_remac_rejected': True, 'unknown_format_with_valid_MAC_rejected': True,
            'legacy_format_write_read_and_ciphertext_oracle_passed': True,
            'entire_16MiB_and_other_eight_backings_match_after_flush_shutdown': True,
            'rejected_requests_DMA_and_backings_unchanged': True, 'DMA_guards_unchanged': True,
            'public_fixture_only': True, 'cpus_paused': True, 'firmware_executed': False,
            'private_profile_accessed': False, 'Keychain_accessed': False,
            'startup_backing_changes': startup, 'native_DATA_semantics_validated': False,
            'Apple_hardware_equivalence': False, 'ready': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    m.require(not args.output.exists(), 'Never overwrite an existing receipt')
    result = run()
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({'engine_sha256': ENGINE, 'rejected_requests': len(result['checks']),
                      'event_count': len(result['events']), 'ready': False}))


if __name__ == '__main__':
    main()
