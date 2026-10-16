#!/usr/bin/env python3
"""Stage only the owned probe helper in an exclusive synthetic iOS clone."""
import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

from boot_ios_research import RESEARCH, digest
from trace_ios_storage_research import BACKINGS, clone_checkpoint

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = RESEARCH / 'ios-vms/native-20261014-protected-data-checkpoint'
HELPER = PROJECT / 'components/ios-device-lab/provisioning/prepare_userdata.c'
ENTITLEMENTS = HELPER.parent / 'userdata-entitlements.plist'
STOCK = ('usr/libexec/huntmob-original/init_data_protection',
         'usr/libexec/init_data_protection', 'usr/libexec/seputil')


def run(arguments, timeout=30):
    return subprocess.run(arguments, check=True, capture_output=True, timeout=timeout)


def attach_system(image, mount, readonly):
    arguments = ['hdiutil', 'attach', '-nomount', '-noautofsck', '-noautoopen',
                 '-nobrowse', '-imagekey', 'diskimage-class=CRawDiskImage',
                 '-blocksize', '4096', '-plist']
    if readonly:
        arguments.append('-readonly')
    entities = plistlib.loads(run([*arguments, str(image)]).stdout)['system-entities']
    whole = next(item['dev-entry'] for item in entities if item.get('content-hint') == 'GUID_partition_scheme')
    try:
        container = next(item['dev-entry'] for item in entities
                         if item.get('content-hint') == 'EF57347C-0000-11AA-AA11-00306543ECAC')
        listing = plistlib.loads(run(['diskutil', 'apfs', 'list', '-plist', container]).stdout)
        systems = [volume for item in listing['Containers'] for volume in item['Volumes']
                   if volume.get('Roles') == ['System'] and volume.get('Encryption') is False]
        if len(systems) != 1:
            raise ValueError('Exactly one unencrypted System volume is required.')
        options = 'rdonly,nobrowse,noowners' if readonly else 'nobrowse,noowners'
        run(['mount_apfs', '-o', options, '/dev/' + systems[0]['DeviceIdentifier'], str(mount)])
        return whole
    except BaseException:
        run(['hdiutil', 'detach', whole])
        raise


def detach_system(device, mount):
    try:
        run(['umount', str(mount)])
    finally:
        run(['hdiutil', 'detach', device])


def stage(target, compare_fresh=False, map_existing=False):
    target, original = clone_checkpoint(SOURCE, target)
    with (target / 'receipt.json').open('xb') as output:
        output.write((SOURCE / 'receipt.json').read_bytes())
    (target / 'receipt.json').chmod(0o600)
    build = target / 'helper-build'
    build.mkdir(mode=0o700)
    # Preserve exact source/entitlements alongside the binary, even if the
    # repository changes later. No guest key or firmware enters this build.
    for path in (HELPER, ENTITLEMENTS):
        shutil.copyfile(path, build / path.name)
    sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.decode().strip()
    binary = build / 'huntmob-prepare-userdata'
    run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios14.0',
         '-isysroot', sdk, '-Wall', '-Wextra', '-Werror', '-O2',
         str(build / HELPER.name), '-o', str(binary)], timeout=60)
    run(['codesign', '-s', '-', '--force', '--entitlements', str(build / ENTITLEMENTS.name), str(binary)])

    reference, mount = target / 'ReferenceMount', target / 'SystemMount'
    for directory in (reference, mount):
        directory.mkdir(mode=0o700)
    device = attach_system(SOURCE / 'namespace-1.raw', reference, True)
    try:
        expected = {name: digest(reference / name) for name in STOCK}
        original_helper = digest(reference / 'usr/libexec/huntmob-prepare-userdata')
    finally:
        detach_system(device, reference)
    device = attach_system(target / 'namespace-1.raw', mount, False)
    try:
        if expected != {name: digest(mount / name) for name in STOCK}:
            raise ValueError('Clone stock files differ before staging.')
        helper = mount / 'usr/libexec/huntmob-prepare-userdata'
        if helper.is_symlink() or digest(helper) != original_helper:
            raise ValueError('Only the original owned helper can be replaced.')
        shutil.copyfile(binary, helper)
        helper.chmod(0o755)
        markers = ['huntmob-probe-diagnostics-only']
        if compare_fresh:
            markers.append('huntmob-probe-compare-fresh')
        if map_existing:
            markers.append('huntmob-map-existing-systembag')
        for name in markers:
            marker = mount / 'usr/libexec' / name
            with marker.open('x') as output:
                output.write('HUNTMOB OWNED SYNTHETIC PROBE DIAGNOSTIC V1\n')
            marker.chmod(0o600)
        run(['codesign', '--verify', '--strict', str(helper)])
        if digest(helper) != digest(binary) or expected != {name: digest(mount / name) for name in STOCK}:
            raise ValueError('Staged source/binary or stock files failed readback.')
    finally:
        detach_system(device, mount)
    hashes = {name: digest(target / name) for name in BACKINGS}
    result = {
        'version': 1, 'purpose': 'owned-persisted-class-c-readonly-diagnostic',
        'helper_before_sha256': original_helper, 'helper_after_sha256': digest(binary),
        'source_sha256': digest(build / HELPER.name), 'stock_hashes': expected,
        'stock_files_unchanged': True, 'source_reference_mounted_readonly': True,
        'data_probe_not_modified_by_host': True, 'fresh_comparison_requested': compare_fresh,
        'existing_systembag_map_requested': map_existing,
        'original_namespace_changed_by_host': False,
        'clone_namespace_changed_by_helper_install': hashes['namespace-1.raw'] != original['namespace-1.raw'],
        'sep_backings_unchanged_by_host': all(hashes[name] == original[name] for name in BACKINGS[1:]),
        'ready': False,
    }
    for name, data in (
        ('helper-install.json', result),
        ('prepared-cohort.json', {'version': 1, 'cohort_sha256': hashes,
                                  'host_staging_complete': True, 'ready': False}),
    ):
        with (target / name).open('x') as output:
            json.dump(data, output, indent=2)
            output.write('\n')
        (target / name).chmod(0o600)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--compare-fresh', action='store_true',
                        help='Permit a separate synthetic class C file only during ephemeral guest diagnostics.')
    parser.add_argument('--map-existing', action='store_true',
                        help='Exact pinned original mapper test; no bag loading, unlock or error suppression.')
    args = parser.parse_args()
    try:
        result = stage(args.target, args.compare_fresh, args.map_existing)
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'failure_type': type(error).__name__}))
        raise SystemExit(1)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
