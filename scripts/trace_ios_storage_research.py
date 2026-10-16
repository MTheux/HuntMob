#!/usr/bin/env python3
"""Observe storage metadata in an exclusive iOS clone; never validate crypto."""
import argparse
import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from boot_ios_research import RESEARCH, SEP_INPUTS, IPSW_SHA, command, digest
from boot_ios_installed_research import normal_sep_machine, quit_owned_vm, boot_observations
from build_ios_research_engine import (
    COMPONENT, PATCHES, TRACE_EVENTS, require_data_protection, reviewed_sources,
)

BACKINGS = tuple(f'namespace-{i}.raw' for i in range(1, 8)) + ('sep-nvram.raw', 'sep-ssc.raw')
FIRMWARE = ('KernelCache', 'DeviceTree', 'RestoreRamDisk', 'RestoreTrustCache')
MAX_LOG = 16 * 1024 * 1024
BASELINE_SHA = '300d1e63f75e345bba75862d3f8ebeda8edffd3b3ccffb9d2f6c11b58a0da95d'


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('Invalid research receipt.')
    with path.open('rb') as source:
        data = source.read(65537)
    if len(data) > 65536:
        raise ValueError('Oversized research receipt.')
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError('Research receipt must be an object.')
    return result


def validate_candidate(folder):
    folder = Path(folder).resolve(strict=True)
    receipt = read_json(folder / 'build-receipt.json')
    pin = read_json(COMPONENT / 'upstream.json')
    binary = folder / 'build/qemu-system-aarch64'
    if (receipt.get('state') != 'compiled' or receipt.get('ready') is not False
            or receipt.get('purpose') != 'storage-protocol-research'
            or receipt.get('revision') != pin['revision']
            or receipt.get('data_protection_source_enabled') is not True
            or receipt.get('patch_sha256') != {name: digest(COMPONENT / name) for name in PATCHES}
            or binary.is_symlink() or digest(binary) != receipt.get('binary_sha256')):
        raise ValueError('Candidate does not match the reviewed diagnostic build.')
    source = folder / 'source'
    require_data_protection(source)
    if reviewed_sources(source, PATCHES) != receipt.get('reviewed_source_sha256'):
        raise ValueError('Reviewed source changed after compilation.')
    # A changed source tree cannot retain the old compile receipt.
    diff = subprocess.check_output(['git', 'diff', '--binary', pin['revision']],
                                   cwd=source, timeout=10)
    import hashlib
    if hashlib.sha256(diff).hexdigest() != receipt.get('source_diff_sha256'):
        raise ValueError('Candidate source changed after compilation.')
    return binary, receipt


def validate_baseline(folder):
    """Negative control accepts only the preserved known diagnostic binary."""
    folder = Path(folder).resolve(strict=True)
    receipt = read_json(folder / ('build-receipt-' + BASELINE_SHA[:16] + '.json'))
    binary = folder / 'build' / ('qemu-system-aarch64-' + BASELINE_SHA[:16])
    if (receipt.get('binary_sha256') != BASELINE_SHA or receipt.get('state') != 'compiled'
            or receipt.get('data_protection_source_enabled') is not True
            or receipt.get('revision') != read_json(COMPONENT / 'upstream.json')['revision']
            or binary.is_symlink() or digest(binary) != BASELINE_SHA):
        raise ValueError('The preserved baseline does not match its recorded build.')
    return binary, receipt


def clone_checkpoint(source, target):
    source, target = Path(source).resolve(strict=True), Path(target).absolute()
    root = (RESEARCH / 'ios-vms').resolve(strict=True)
    if source.parent != root or source.name != 'native-20261014-protected-data-checkpoint':
        raise ValueError('Only the owned synthetic-data checkpoint is accepted.')
    if target.parent != root or not re.fullmatch(r'native-storage-trace-[a-z0-9-]+', target.name):
        raise ValueError('The trace requires a new exclusive research clone.')
    receipt = read_json(source / 'receipt.json')
    proof = read_json(source / 'protected-data-proof.json')
    hashes = proof.get('cohort_sha256')
    if (receipt.get('native_asr_completed') is not True or receipt.get('ipsw_sha256') != IPSW_SHA
            or not isinstance(hashes, dict) or set(hashes) != set(BACKINGS)):
        raise ValueError('The checkpoint is missing its full pinned provenance.')
    names = (*FIRMWARE, *BACKINGS)
    for name in names:
        path = source / name
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise ValueError('The checkpoint must contain independent regular files.')
    target.mkdir(mode=0o700, exist_ok=False)
    # APFS COW copies preserve space but have independent inodes. Never link disks.
    for name in names:
        subprocess.run(['/bin/cp', '-c', str(source / name), str(target / name)],
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=True)
        copied = target / name
        os.chmod(copied, 0o600)
        expected = hashes[name] if name in BACKINGS else receipt['files'][name]['sha256']
        if copied.stat().st_nlink != 1 or copied.samefile(source / name) or digest(copied) != expected:
            raise ValueError('The cloned backing does not match its preparation receipt.')
    return target, hashes


def prepared_clone(target):
    """Accept only the explicitly staged own read-only diagnostic helper."""
    target = Path(target).resolve(strict=True)
    if (target.parent != (RESEARCH / 'ios-vms').resolve()
            or not re.fullmatch(r'native-storage-trace-[a-z0-9-]+', target.name)):
        raise ValueError('Prepared probe clone is outside the owned research folder.')
    staged = read_json(target / 'helper-install.json')
    cohort = read_json(target / 'prepared-cohort.json')
    if (staged.get('purpose') != 'owned-persisted-class-c-readonly-diagnostic'
            or staged.get('ready') is not False or staged.get('stock_files_unchanged') is not True
            or staged.get('source_sha256') != digest(COMPONENT.parent / 'ios-device-lab/provisioning/prepare_userdata.c')
            or cohort.get('version') != 1 or set(cohort.get('cohort_sha256', {})) != set(BACKINGS)):
        raise ValueError('Prepared clone lacks validated own-helper provenance.')
    images = __import__('plistlib').loads(subprocess.check_output(['hdiutil', 'info', '-plist'], timeout=10))['images']
    if any(image.get('image-path') == str(target / 'namespace-1.raw') for image in images):
        raise ValueError('Detach the owned staged image before boot.')
    original = read_json(RESEARCH / 'ios-vms/native-20261014-protected-data-checkpoint/receipt.json')
    for name in (*FIRMWARE, *BACKINGS):
        path = target / name
        expected = cohort['cohort_sha256'][name] if name in BACKINGS else original['files'][name]['sha256']
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 or digest(path) != expected:
            raise ValueError('Staged clone differs from its post-install receipt.')
    return target, cohort['cohort_sha256']


def trace_summary(content):
    """Allow-listed metadata only; absence and successful I/O do not prove crypto."""
    counts = Counter()
    opcodes, endpoints, stubs, completions = Counter(), Counter(), Counter(), Counter()
    aess, ssc, backing_io, backing_statuses, protected_modes = Counter(), Counter(), Counter(), Counter(), Counter()
    aes_modes, aes_rejections, aes_results, aes_opcodes, keyline = (Counter() for _ in range(5))
    key_controls = Counter()
    derivation_requests = Counter()
    untrusted_derivation_records = 0
    invalid_aess = 0
    for line in content.splitlines():
        for event in TRACE_EVENTS:
            match = re.search(r'\b' + re.escape(event) + r'\s+(.+)$', line)
            if not match:
                continue
            fields = dict(re.findall(r'\b([a-z_]+)=(-?0x[0-9a-fA-F]+|-?[0-9]+)\b', match.group(1)))
            counts[event] += 1
            if event == 'apple_sep_key_transfer_unimplemented' and 'endpoint' in fields:
                endpoints[fields['endpoint'].lower()] += 1
            elif event == 'pci_nvme_apple_ans_submit' and 'opcode' in fields:
                category = 'admin' if fields.get('sqid') == '0' else 'io'
                opcodes[f'{category}:{fields["opcode"].lower()}'] += 1
            elif event == 'pci_nvme_apple_ans_admin_unimplemented' and 'opcode' in fields:
                stubs[fields['opcode'].lower()] += 1
            elif event == 'pci_nvme_apple_ans_complete' and 'status' in fields:
                completions[fields['status'].lower()] += 1
            elif event == 'apple_sep_aess_operation':
                category = re.search(r'\boperation=(seed-sync|key-setup|uid-wrap|cbc-encrypt|cbc-decrypt|key-load|other)\b', match.group(1))
                if category:
                    aess[category.group(1)] += 1
            elif event == 'apple_sep_aess_complete':
                invalid_aess += fields.get('invalid_parameters') == '1'
            elif event == 'apple_sep_ssc_command' and 'operation' in fields:
                ssc[fields['operation'].lower()] += 1
            elif event == 'apple_sep_ssc_backing_io':
                if 'operation' in fields and fields.get('write') in {'0', '1'}:
                    direction = 'write' if fields['write'] == '1' else 'read'
                    backing_io[f'{fields["operation"].lower()}:{direction}'] += 1
                if 'result' in fields:
                    backing_statuses[fields['result']] += 1
            elif event == 'pci_nvme_apple_ans_protected_io_rejected' and fields.get('mode') in {'1', '2', '3'}:
                protected_modes[fields['mode']] += 1
            elif event == 'apple_aes_key_mode':
                category = re.search(r'\bmode=(software-wrapped|software|hardware)\s+disabled=([01])(?:\s|$)', match.group(1))
                if category:
                    aes_modes[f'{category[1]}:disabled={category[2]}'] += 1
            elif event == 'apple_aes_data_rejected':
                reason = re.search(r'\breason=(invalid-length|disabled-key)(?:\s|$)', match.group(1))
                if reason:
                    aes_rejections[reason[1]] += 1
            elif event == 'apple_aes_cipher_result' and 'result' in fields:
                aes_results[fields['result']] += 1
            elif event == 'apple_aes_process_command':
                opcode = re.search(r'\bop (0x[0-9a-fA-F])(?:\s|$)', match.group(1))
                if opcode:
                    aes_opcodes[opcode[1].lower()] += 1
            elif event == 'apple_sep_keyline_request':
                request = re.search(r'\boperation=(load|control|send)\s+active=([01])(?:\s|$)', match.group(1))
                if request:
                    keyline[f'{request[1]}:active={request[2]}'] += 1
            elif event == 'apple_sep_key_control_category':
                category = re.search(r'\bcategory=(wrapping-select|authentication-select|subkey-select|clear|seed|other)(?:\s|$)', match.group(1))
                if category:
                    key_controls[category[1]] += 1
            elif event == 'apple_sep_derivation_readiness':
                request = re.fullmatch(
                    r'phase=(latch-request|program-request|unsupported-derive) '
                    r'role=(wrapping|authentication|subkey) validated=0', match.group(1))
                if request:
                    derivation_requests[f'{request[1]}:{request[2]}'] += 1
                else:
                    # Never accept an asserted validation flag or unknown payload
                    # as evidence that placeholder slots contain native keys.
                    untrusted_derivation_records += 1
            break
    return {
        'event_counts': {name: counts[name] for name in TRACE_EVENTS},
        'submission_opcodes': dict(opcodes), 'sep_transfer_endpoints': dict(endpoints),
        'unimplemented_admin_opcodes': dict(stubs), 'completion_statuses': dict(completions),
        'aess_operation_categories': dict(aess), 'aess_invalid_parameter_completions': invalid_aess,
        'ssc_operations': dict(ssc), 'ssc_backing_operations': dict(backing_io),
        'ssc_backing_return_codes': dict(backing_statuses),
        'protected_io_rejected_modes': dict(protected_modes),
        'ap_aes_key_modes': dict(aes_modes), 'ap_aes_rejections': dict(aes_rejections),
        'ap_aes_cipher_results': dict(aes_results), 'ap_aes_opcodes': dict(aes_opcodes),
        'sep_keyline_requests': dict(keyline),
        'sep_key_control_categories': dict(key_controls),
        'sep_context_readiness_requests': dict(derivation_requests),
        'sep_context_untrusted_readiness_records': untrusted_derivation_records,
        'sep_context_derivation_validated': False,
        'ready': False, 'data_protection_validated': False,
        'interpretation': 'Metadata observation only; no cipher, key handoff or protected I/O validated.',
    }


def observe(candidate, source, target, seconds, use_prepared_clone=False, baseline=False):
    if not 10 <= seconds <= 60:
        raise ValueError('Observation time must be between 10 and 60 seconds.')
    binary, build_receipt = validate_baseline(candidate) if baseline else validate_candidate(candidate)
    # Fixed SEP inputs from the existing owned lab, never physical USB or NIC.
    for name, expected in SEP_INPUTS.items():
        if digest(RESEARCH / 'firmware' / name) != expected:
            raise ValueError('SEP input does not match its preparation receipt.')
    # Validate serving firmware before copying any disks.
    normal_sep_machine(f"t8030,sep-fw={RESEARCH / 'firmware/sep-firmware.n104.RELEASE.new.img4'}")
    target, expected_hashes = prepared_clone(target) if use_prepared_clone else clone_checkpoint(source, target)
    events = target / 'events.txt'
    enabled_events = [event for event in TRACE_EVENTS if event in build_receipt['trace_events']]
    events.write_text('\n'.join(enabled_events) + '\n')
    events.chmod(0o600)
    trace, log = target / 'storage.trace', target / 'boot.log'
    for path in (trace, log):
        path.touch(mode=0o600, exist_ok=False)
    files = {name: {'path': str(target / name)} for name in FIRMWARE}
    launch = command(binary, target, files, restore=False, sep=True,
                     companion_profile='x86_64', tcg_thread='single', create_disks=False)
    index = launch.index('-initrd')
    del launch[index:index + 2]
    index = launch.index('-M') + 1
    launch[index] = normal_sep_machine(launch[index]) + ',boot-mode=exit_recovery'
    launch += ['-trace', f'events={events},file={trace}']
    if '-snapshot' not in launch or launch[launch.index('-nic') + 1] != 'none':
        raise ValueError('Research observation must keep ephemeral writes and no guest network.')
    started = time.monotonic()
    stopped = 'engine-exit'
    with log.open('ab') as output:
        process = subprocess.Popen(launch, cwd=target, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                if log.stat().st_size > MAX_LOG or trace.stat().st_size > MAX_LOG:
                    stopped = 'log-size-limit'
                    break
                if time.monotonic() - started >= seconds:
                    stopped = 'time-limit'
                    break
                try:
                    process.wait(timeout=.25)
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if process.poll() is None:
                if not quit_owned_vm(target / 'qmp.sock'):
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
    observation_seconds = round(time.monotonic() - started, 2)
    audit_started = time.monotonic()
    # Hash all nine clone files again after flushing/closing the engine.
    unchanged = all(digest(target / name) == expected for name, expected in expected_hashes.items())
    with trace.open('rb') as stream:
        data = stream.read(MAX_LOG + 1)
    with log.open('rb') as stream:
        boot = stream.read(MAX_LOG + 1)
    complete = len(data) <= MAX_LOG and len(boot) <= MAX_LOG and stopped != 'log-size-limit'
    result = {
        'version': 1, 'scope': 'owned-synthetic-checkpoint',
        'engine_revision': build_receipt['revision'], 'engine_sha256': digest(binary),
        'baseline_negative_control': baseline,
        'diagnostic_patch_sha256': build_receipt['patch_sha256']['ans-storage-diagnostics.patch'],
        'ephemeral_guest_writes': True, 'clone_backings_unchanged': unchanged,
        'observation_seconds': observation_seconds,
        'post_run_audit_seconds': round(time.monotonic() - audit_started, 2),
        'engine_exit_code': process.returncode, 'stop_reason': stopped,
        'trace_complete_within_limits': complete,
        'metadata': trace_summary(data.decode(errors='replace')),
        'boot': boot_observations(boot.decode(errors='replace'), stopped == 'time-limit'),
        'ready': False, 'storage_crypto_implemented': False,
        'data_protection_validated': False, 'springboard_validated': False,
        'ipa_execution_validated': False,
    }
    text = boot.decode(errors='replace')
    first_unlock = re.findall(r'HuntMob: first-unlock state (-1|0|1)\b', text)
    result['probe'] = {
        'readonly_diagnostic_requested': use_prepared_clone,
        'first_unlock_state': int(first_unlock[-1]) if first_unlock else None,
        'metadata_class_c_observed': 'HuntMob: persisted probe protection class 3' in text,
        'readonly_open_rejected': 'HuntMob: Class C read-only open rejected' in text,
        'readonly_read_rejected': 'HuntMob: Class C read-only read rejected' in text,
        'readonly_read_completed': 'HuntMob: persisted class C read-only read completed' in text,
        'fresh_class_c_observed': 'HuntMob: fresh probe protection class 3' in text,
        'fresh_create_rejected': 'HuntMob: fresh class C create rejected' in text,
        'fresh_write_rejected': 'HuntMob: fresh class C write rejected' in text,
        'fresh_roundtrip_completed': 'HuntMob: fresh class C roundtrip completed' in text,
        'original_systembag_map_completed': 'HuntMob: original system bag association call completed' in text,
        'existing_systembag_unavailable': 'HuntMob: existing system bag unavailable for map' in text,
        'systembag_binding_rejected': any(message in text for message in [
            'HuntMob: existing system bag map preconditions rejected',
            'HuntMob: original keybag module binding rejected',
            'HuntMob: original keybag routine fingerprint rejected']),
    }
    receipt_path = target / 'trace-receipt.json'
    receipt_path.touch(mode=0o600, exist_ok=False)
    receipt_path.write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--source', type=Path,
                        default=RESEARCH / 'ios-vms/native-20261014-protected-data-checkpoint')
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--prepared-clone', action='store_true',
                        help='Use a verified staged read-only helper clone instead of making a new clone.')
    parser.add_argument('--baseline', action='store_true',
                        help='Negative control with the preserved stage-2 diagnostic binary; own synthetic data only.')
    args = parser.parse_args()
    try:
        result = observe(args.candidate, args.source, args.target, args.seconds, args.prepared_clone, args.baseline)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'failure_type': type(error).__name__}))
        raise SystemExit(1)
    print(json.dumps(result))
    if not result['clone_backings_unchanged'] or not result['trace_complete_within_limits']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
