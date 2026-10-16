#!/usr/bin/env python3
"""Bounded boot of a NEW owned VirtualSEP-v1 identity, never historical disks.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Own virtual crypto contract, not an
Apple hardware KDF. No root bytes enter Python, argv, receipts or a key file.
"""
import argparse
import json
import os
import resource
import re
import stat
import subprocess
import time
import uuid
from collections import deque
from pathlib import Path

from boot_ios_research import RESEARCH, SEP_INPUTS, digest, command, prepare
from boot_ios_installed_research import normal_sep_machine, quit_owned_vm, boot_observations
from build_ios_research_engine import require_data_protection, reviewed_sources, PATCHES
from prepare_ios_virtual_profile import SIZES, fingerprint, write_manifest, IPSW, image_inventory, image_path

CANDIDATE = RESEARCH / 'ios-engine-diagnostics-20261014'
HELPER = RESEARCH / 'virtual-sep-keychain-v1-20261015/helper-reviewed'
HELPER_SHA = '51ee8f2d25fb3098133a9006bb7893175b0e3cd695db53c5b7e93d0fd58c1691'
EVENTS = ('apple_sep_aess_operation', 'apple_sep_aess_complete',
          'apple_sep_key_control_category', 'apple_sep_derivation_readiness',
          'apple_sep_virtual_operation', 'apple_sep_virtual_mpe_control',
          'apple_sep_virtual_mpe_memory_event',
          'apple_sep_ssc_command', 'apple_sep_ssc_complete',
          'apple_sep_ssc_backing_io', 'apple_sep_ssc_reset',
          'pci_nvme_apple_ans_admin_unimplemented',
          'pci_nvme_apple_ans_protected_io_rejected',
          'pci_nvme_apple_ans_protected_gate',
          'pci_nvme_apple_ans_frame_format',
          'pci_nvme_apple_ans_submit', 'pci_nvme_apple_ans_complete')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def virtual_memory_observations(trace):
    """Summarize public control events; a successful command is not a boot proof."""
    controls, commands = deque(maxlen=256), deque(maxlen=256)
    sealed, counters, initialized = set(), {}, {}
    command_count, rejected_count = 0, 0
    memory_fault, boot_jump = False, False
    for line in trace.splitlines():
        match = re.fullmatch(
            r'apple_sep_virtual_operation command=0x([0-9a-f]+) '
            r'keydisable=0x[0-9a-f]+ iterations=\d+ accepted=([01])', line)
        if match:
            command_count += 1
            rejected_count += match[2] == '0'
            commands.append({'command': int(match[1], 16), 'accepted': match[2] == '1'})
        match = re.fullmatch(
            r'apple_sep_virtual_mpe_control action=([a-z-]+) '
            r'reg=0x([0-9a-f]+) value=0x([0-9a-f]+) accepted=([01])', line)
        if match:
            action, reg, value, accepted = match[1], int(match[2], 16), int(match[3], 16), match[4] == '1'
            controls.append({'action': action, 'register': reg,
                             'value': value, 'accepted': accepted})
            if action == 'control' and reg in (0x414, 0x434) and value == 1 and accepted:
                sealed.add(0 if reg == 0x414 else 1)
        match = re.fullmatch(
            r'apple_sep_virtual_mpe_memory_event action=([a-z-]+) '
            r'region=([012]) bytes=(\d+)', line)
        if match:
            action, region, count = match[1], match[2], int(match[3])
            if action == 'written':
                counters[region] = count
            elif action == 'initialized':
                initialized[region] = count
            elif action == 'fault':
                memory_fault = True
            elif action == 'boot-jump-request':
                boot_jump = True
    return {'aess_commands': list(commands), 'virtual_mpe_controls': list(controls),
            'aess_command_count': command_count, 'aess_rejected_command_count': rejected_count,
            'virtual_mpe_seal_commands_accepted': sorted(sealed),
            'virtual_mpe_guest_memory_validated': False,
            'virtual_mpe_last_written_byte_counters': counters,
            'virtual_mpe_initialized_region_bytes': initialized,
            'virtual_mpe_memory_fault_observed': memory_fault,
            'virtual_mpe_boot_jump_requested': boot_jump,
            'apple_mpe_equivalence': False}


def validate(target):
    require(not target.is_symlink() and target.is_dir(), 'Exclusive profile must exist')
    file = target / 'virtual-profile.json'
    require(not file.is_symlink() and file.stat().st_size <= 65536, 'Invalid profile manifest')
    manifest = json.loads(file.read_text())
    vm_id = manifest.get('vm_uuid', '')
    require(str(uuid.UUID(vm_id)) == vm_id and target == RESEARCH / 'ios-vms' / ('virtual-sep-v1-' + vm_id),
            'Profile path and identity do not match')
    require(manifest.get('schema') == 'huntmob.virtual-sep-profile.v1' and
            manifest.get('old_cohort_cloned') is False and manifest.get('ready') is False and
            manifest.get('restore_completed') is True and manifest.get('owned_device_detached') is True,
            'Only the new pristine restored and detached virtual cohort is permitted')
    staging = manifest.get('virtual_staging', {})
    require(manifest.get('host_staging_complete') is True and
            manifest.get('stock_files_staged') is True and
            manifest.get('private_artifact_absence_checked') is True and
            staging.get('stock_verifier_preserved') is True and
            staging.get('stock_seputil_unchanged') is True and
            staging.get('phase') in {'restore-checkpoint', 'data-checkpoint'},
            'Verified fresh-profile helper staging must precede root delivery')
    require(manifest['firmware']['files']['RestoreTrustCache']['sha256'] == staging.get('trustcache_sha256'),
            'Trustcache does not match the staged helpers')
    for name in SIZES:
        require(fingerprint(target / name) == manifest['backings'][name], 'Backing identity changed')
    require(all(image_path(entry['image-path']).resolve() != (target / 'namespace-1.raw').resolve()
                for entry in image_inventory() if entry.get('image-path')),
            'Research backing is still attached to the host')
    receipt = json.loads((CANDIDATE / 'build-receipt.json').read_text())
    binary = CANDIDATE / 'build/qemu-system-aarch64'
    require(receipt.get('state') == 'compiled' and receipt.get('ready') is False and
            receipt.get('virtual_sep_default_enabled') is False and not binary.is_symlink() and
            digest(binary) == receipt.get('binary_sha256'), 'Unreviewed engine')
    require_data_protection(CANDIDATE / 'source')
    require(reviewed_sources(CANDIDATE / 'source', PATCHES) == receipt['reviewed_source_sha256'],
            'Engine source differs from reviewed build')
    provider_hash = receipt['reviewed_source_sha256']['crypto/huntmob-virtual-sep.c']
    require(not manifest.get('root_provisioned') or
            manifest.get('crypto_provider_source_sha256') == provider_hash,
            'A provisioned identity cannot silently change its derivation contract')
    require(not HELPER.is_symlink() and digest(HELPER) == HELPER_SHA, 'Unreviewed Keychain helper')
    for name, sha in SEP_INPUTS.items():
        require(digest(RESEARCH / 'firmware' / name) == sha, 'Pinned SEP inputs changed')
    return manifest, binary, receipt


def root_pipe(vm_id, create):
    """Only the native helper sees the root. Python owns descriptors, not bytes."""
    read_fd, write_fd = os.pipe()
    try:
        result = subprocess.run([str(HELPER), '--create' if create else '--lookup',
                                 vm_id, '--output-fd', str(write_fd)],
                                pass_fds=(write_fd,), stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=20)
        os.close(write_fd)
        write_fd = -1
        require(len(result.stdout) <= 4096 and len(result.stderr) <= 4096,
                'Unexpected helper metadata size')
        status = json.loads(result.stdout)
        require(result.returncode == 0 and status.get('delivered') is True and
                status.get('status') == 'ok', 'Keychain root delivery refused')
        return read_fd, status
    except BaseException:
        os.close(read_fd)
        raise
    finally:
        if write_fd >= 0:
            os.close(write_fd)


def effaceable_ramdisk_inputs(target, manifest):
    record = manifest.get('effaceable_ramdisk', {})
    require(record.get('state') == 'prepared' and record.get('fresh_ns6_zero_verified') is True and
            record.get('secure_root_policy_changed') is False and
            record.get('sep_restore_or_erase_requested') is False,
            'Only the prepared fresh effaceable ramdisk may run once')
    require(not any((target/'namespace-6.raw').read_bytes()), 'Fresh namespace6 is no longer empty')
    root = target/('effaceable-ramdisk-v6-preloaded-online'
                  if manifest.get('effaceable_ramdisk_online_predecessor') else
                  'effaceable-ramdisk-v5-bounded-matching'
                  if manifest.get('effaceable_ramdisk_matching_predecessor') else
                  'effaceable-ramdisk-v4-library-install-name'
                  if manifest.get('effaceable_ramdisk_library_predecessor') else
                  'effaceable-ramdisk-v3-device-identity'
                  if manifest.get('effaceable_ramdisk_device_identity_predecessor') else
                  'effaceable-ramdisk-v2-scope-diagnostics'
                  if manifest.get('effaceable_ramdisk_scope_rejection') else 'effaceable-ramdisk-v1')
    result = {}
    for name, filename, prefix in [('RestoreRamDisk', 'RestoreRamDisk.raw', 'ramdisk'),
                                   ('RestoreTrustCache', 'RestoreTrustCache', 'trustcache')]:
        path = Path(record[prefix+'_path'])
        require(path == root/filename and not path.is_symlink() and
                digest(path) == record[prefix+'_sha256'], 'Prepared ramdisk input changed')
        result[name] = {'path': str(path), 'sha256': record[prefix+'_sha256']}
    return result


def boot(target, seconds, persistent=False, sep_profile='serving', create_root=False, effaceable_ramdisk=False):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    manifest, binary, build = validate(target)
    phase = manifest['virtual_staging']['phase']
    require(persistent and sep_profile == ('restore-preload' if phase == 'restore-checkpoint' else 'serving'),
            'Checkpoint phase requires its matching SEP profile and persistent new cohort')
    require(create_root == (manifest.get('root_provisioned') is False),
            'Create root exactly once; later boots must lookup the same identity')
    if not manifest.get('firmware_components_staged'):
        firmware = prepare(IPSW, target / 'firmware')
        manifest['firmware'] = firmware
        manifest['firmware_components_staged'] = True
        write_manifest(target, manifest)
    files = manifest['firmware']['files']
    for entry in files.values():
        require(digest(Path(entry['path'])) == entry['sha256'], 'Firmware component changed')
    if effaceable_ramdisk:
        require(phase == 'data-checkpoint' and not create_root, 'Initializer requires the existing identity')
        files = {**files, **effaceable_ramdisk_inputs(target, manifest)}
    require(not (target / 'qmp.sock').exists(), 'QMP socket already exists; refuse concurrent VM')
    run_dir = target / ('observation-' + time.strftime('%Y%m%d-%H%M%S'))
    run_dir.mkdir(mode=0o700)
    launch = command(binary, target, files, sep=True, companion_profile='x86_64',
                     tcg_thread='single', create_disks=False)
    if not effaceable_ramdisk:
        del launch[launch.index('-initrd'):launch.index('-initrd') + 2]
    if persistent:
        launch.remove('-snapshot')
    machine_index = launch.index('-M') + 1
    mode = 'enter_recovery' if effaceable_ramdisk else 'exit_recovery'
    launch[machine_index] = normal_sep_machine(launch[machine_index], sep_profile) + ',boot-mode='+mode
    launch[machine_index] += (',huntmob-virtual-sep-root-secret=virtual-root'
                              ',huntmob-virtual-sep-vm-id=' + manifest['vm_uuid'])
    trace_events = run_dir / 'trace-events.txt'
    trace_events.write_text('\n'.join(EVENTS) + '\n')
    launch += ['-trace', 'events=' + str(trace_events) + ',file=' + str(run_dir / 'trace.log')]
    read_fd, status = root_pipe(manifest['vm_uuid'], create_root)
    if effaceable_ramdisk:
        manifest['effaceable_ramdisk'].update(state='launch-requested', observation=str(run_dir))
    manifest.update(root_provisioned=True, root_lookup_performed=not create_root,
                    root_helper_sha256=HELPER_SHA, engine_sha256=build['binary_sha256'],
                    crypto_provider_source_sha256=build['reviewed_source_sha256']['crypto/huntmob-virtual-sep.c'])
    write_manifest(target, manifest)
    launch += ['-object', 'secret,id=virtual-root,file=/dev/fd/' + str(read_fd) + ',format=raw']
    receipt = {'schema': 'huntmob.virtual-sep-boot.v1', 'vm_uuid': manifest['vm_uuid'],
               'engine_sha256': build['binary_sha256'], 'sep_profile': sep_profile,
               'persistent_writes_requested': persistent, 'root_pipe_delivered': True,
               'root_key_in_python_or_file': False, 'core_dumps_disabled': True,
               'ready': False, 'apple_sep_equivalent': False, 'data_protection_validated': False,
               'springboard_validated': False, 'ipa_execution_validated': False,
               'effaceable_ramdisk_requested': effaceable_ramdisk,
               'command': launch, 'seconds': seconds}
    process = None
    started = time.monotonic()
    reason = 'engine-exited'
    try:
        with (run_dir / 'boot.log').open('xb') as output:
            process = subprocess.Popen(launch, pass_fds=(read_fd,), cwd=run_dir,
                                       stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            os.close(read_fd)
            read_fd = -1
            while process.poll() is None:
                if time.monotonic() - started >= seconds:
                    reason = 'bounded-observation-ended'
                    break
                if any(path.stat().st_size > 16 * 1024 * 1024 for path in
                       (run_dir / 'boot.log', run_dir / 'trace.log') if path.exists()):
                    reason = 'metadata-log-bound-reached'
                    break
                with (run_dir / 'boot.log').open('rb') as reader:
                    reader.seek(max(0, (run_dir / 'boot.log').stat().st_size - 32768))
                    recent = reader.read(32768)
                if b'HuntMob: provisioning checkpoint ready;' in recent:
                    reason = 'provisioning-checkpoint-observed'
                    break
                if effaceable_ramdisk and b'HuntMob: trusted effaceable RAMdisk scope rejected' in recent:
                    reason = 'effaceable-ramdisk-scope-rejected'
                    break
                if effaceable_ramdisk and b'HuntMob: trusted effaceable matching failed' in recent:
                    reason = 'effaceable-service-not-published'
                    break
                if b'panic(cpu' in recent:
                    reason = 'guest-panic-observed'
                    break
                trace_file = run_dir / 'trace.log'
                if trace_file.exists():
                    with trace_file.open('rb') as reader:
                        reader.seek(max(0, trace_file.stat().st_size - 32768))
                        recent_trace = reader.read(32768)
                    recent_state = virtual_memory_observations(recent_trace.decode('ascii', errors='replace'))
                    if recent_state['virtual_mpe_memory_fault_observed'] or any(
                            item['action'] == 'revoked' and not item['accepted']
                            for item in recent_state['virtual_mpe_controls']):
                        reason = 'virtual-mpe-contract-rejected'
                        break
                time.sleep(.1)
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if process is not None and process.poll() is None:
            receipt['qmp_quit_accepted'] = quit_owned_vm(target / 'qmp.sock')
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        receipt.update(elapsed_seconds=round(time.monotonic() - started, 2),
                       stop_reason=reason, exit_code=process.returncode if process else None)
        for name in ('boot.log', 'trace.log'):
            if (run_dir / name).is_file():
                receipt[name + '_sha256'] = digest(run_dir / name)
        content = (run_dir / 'boot.log').read_text(errors='replace') if (run_dir / 'boot.log').exists() else ''
        receipt.update(boot_observations(content, timed_out=reason == 'bounded-observation-ended'))
        receipt['provisioning_checkpoint_observed'] = reason == 'provisioning-checkpoint-observed'
        trace = (run_dir / 'trace.log').read_text(errors='replace') if (run_dir / 'trace.log').exists() else ''
        receipt.update(virtual_memory_observations(trace))
        receipt['virtual_identity_trace_observed'] = 'phase=virtual-' in trace
        receipt['qom_root_load_error_observed'] = 'Unable to read' in content or 'Virtual SEP root' in content
        (run_dir / 'observation.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return run_dir, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--vm-uuid', required=True)
    parser.add_argument('--seconds', type=int, choices=range(10, 181), default=25)
    parser.add_argument('--persistent-new-cohort', action='store_true')
    parser.add_argument('--create-root', action='store_true')
    parser.add_argument('--sep-profile', choices=('serving', 'restore-preload'), default='serving')
    parser.add_argument('--effaceable-ramdisk', action='store_true', help='Run the once-only fresh initializer on md0')
    args = parser.parse_args()
    require(str(uuid.UUID(args.vm_uuid)) == args.vm_uuid, 'Canonical UUID required')
    target = RESEARCH / 'ios-vms' / ('virtual-sep-v1-' + args.vm_uuid)
    run_dir, result = boot(target, args.seconds, args.persistent_new_cohort, args.sep_profile, args.create_root,
                          args.effaceable_ramdisk)
    print(json.dumps({'observation': str(run_dir), 'stop_reason': result['stop_reason'],
                      'ready': False, 'sep_os_alive_observed': result['sep_os_alive_observed'],
                      'panic_observed': result['panic_observed']}))


if __name__ == '__main__':
    main()
