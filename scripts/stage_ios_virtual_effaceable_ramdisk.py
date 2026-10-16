#!/usr/bin/env python3
"""Prepare an owned ramdisk initializer, without starting a guest or reading keys.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Uses the pinned public restore root.
No kernel, DeviceTree, SecureRoot gate, SEP identity or existing disk is patched.
Only an independent copy of the public ramdisk receives the scoped helper.
"""
import argparse
import json
import plistlib
import re
import shutil
from pathlib import Path

import stage_ios_virtual_profile as stage
from install_auxiliary_bootstrap_vm import cdhash

SOURCE = stage.profile.RESEARCH/'ramdisk-inspection.raw'
SOURCE_SHA = '5eff57f37009c1d996d6de3d6a069029a855cdc978fd54af0977cac49b42689e'
HELPER_SOURCE = 'initialize_effaceable_virtual_v1.c'


def require_fresh(target, manifest, scope_diagnostics=False, device_identity=False, library_install_name=False, wait_for_service=False, online_preloaded=False):
    stage.require(manifest['virtual_staging']['phase'] == 'data-checkpoint' and
                  manifest.get('effaceable_query_observer', {}).get('observe_only') is True and
                  (scope_diagnostics or device_identity or library_install_name or wait_for_service or online_preloaded or not manifest.get('effaceable_ramdisk')),
                  'Expected the observed fresh Data checkpoint')
    stage.require(not (target/'qmp.sock').exists(), 'VM may be active')
    ns6 = target/'namespace-6.raw'
    stage.require(stage.profile.fingerprint(ns6) == manifest['backings'][ns6.name] and
                  ns6.stat().st_size == 4096 and not any(ns6.read_bytes()),
                  'Effaceable initialization is limited to the completely zero fresh namespace6')
    if scope_diagnostics or device_identity or library_install_name or wait_for_service or online_preloaded:
        record = manifest.get('effaceable_ramdisk', {})
        expected = ('9eafe25aa05016f3cc82231ad00a398e530d0a80e1b10214cd6c909898266d91' if online_preloaded else
                    'e76001da5caf01b51f98f6139dc20e87556ca4d1b10b382c389ea951e03496a2' if wait_for_service else
                    '9e7edda86670b07da8c4886be29800f522daa5a2672d93db9c6bf0f8a58632e6' if library_install_name else
                    'eab5ebd22c0f1633d414d2253fb6de51e09f85e8efcf666b19cb01546da4e9c8'
                    if device_identity else '89b79af9ba20580d1674f158e1361a04aed3fdbffed385c94911ad0f69daf24b')
        key = ('effaceable_ramdisk_online_predecessor' if online_preloaded else
               'effaceable_ramdisk_matching_predecessor' if wait_for_service else
               'effaceable_ramdisk_library_predecessor' if library_install_name else
               'effaceable_ramdisk_device_identity_predecessor' if device_identity else 'effaceable_ramdisk_scope_rejection')
        stage.require(record.get('state') == 'launch-requested' and
                      record.get('source_sha256') == expected and not manifest.get(key),
                      'Only the exact known scope rejection may be corrected once')
        observation = Path(record.get('observation', ''))
        stage.require(observation.parent == target and observation.name.startswith('observation-') and
                      not observation.is_symlink(), 'Rejection receipt must belong to this VM')
        log = (observation/'boot.log').read_text()
        trace = (observation/'trace.log').read_text()
        receipt = json.loads((observation/'observation.json').read_text())
        stage.require(receipt.get('effaceable_ramdisk_requested') is True and
                      receipt.get('panic_observed') is False and
                      (library_install_name or wait_for_service or online_preloaded or 'HuntMob: trusted effaceable RAMdisk scope rejected' in log) and
                      'HuntMob: trusted effaceable stock format' not in log and
                      not re.search(r'pci_nvme_apple_ans_submit sqid=1 cid=\d+ opcode=0x01 nsid=6', trace),
                      'A format attempt or namespace write forbids automatic scope diagnosis')
        if device_identity:
            stage.require('HuntMob: trusted effaceable root scope=0 type=hfs from=root_device on=/ rootfs=1' in log and
                          'BSD root: md0,' in log, 'Only the confirmed native root_device alias may be corrected')
        if library_install_name:
            stage.require('HuntMob: trusted effaceable root device-is-md0=1' in log and
                          'HuntMob: trusted effaceable open status=' not in log and
                          'HuntMob: trusted effaceable RAMdisk scope rejected' not in log and
                          'Service exited with abnormal code: 1' in log,
                          'Only the verified pre-open library failure may be corrected')
        if wait_for_service or online_preloaded:
            stage.require('HuntMob: trusted effaceable root device-is-md0=1' in log and
                          'HuntMob: trusted effaceable matching failed status=0' in log and
                          'HuntMob: trusted effaceable open status=' not in log,
                          'Only the confirmed pre-open missing service may receive a bounded wait')
        if online_preloaded:
            stage.require('FW update not complete, create dummy block device' in log,
                          'The restore-specific driver state must be confirmed before online initialization')


def stage_ramdisk(vm_id, scope_diagnostics=False, device_identity=False, library_install_name=False, wait_for_service=False, online_preloaded=False):
    target, manifest = stage.validate(vm_id)
    stage.require(sum((scope_diagnostics, device_identity, library_install_name, wait_for_service, online_preloaded)) <= 1, 'Select only one reviewed transition')
    require_fresh(target, manifest, scope_diagnostics, device_identity, library_install_name, wait_for_service, online_preloaded)
    if online_preloaded:
        import boot_ios_virtual_profile as boot
        _, _, engine = boot.validate(target)
        test = json.loads((stage.PROJECT/'artifacts/validation/ios-virtual-sep-namespace-guard-v1-2026-10-15.json').read_text())
        stage.require(test.get('engine_sha256') == engine['binary_sha256'] and
                      test.get('format_commands_rejected') == 2 and test.get('DMA_unchanged') is True and
                      test.get('entire_16MiB_namespace_unchanged') is True,
                      'A tested vendor namespace-format denial must precede controller initialization')
    stage.require(not SOURCE.is_symlink() and SOURCE.stat().st_size == 104685568 and
                  stage.digest(SOURCE) == SOURCE_SHA, 'Pinned public ramdisk differs')
    build = target/('effaceable-ramdisk-v6-preloaded-online' if online_preloaded else
                    'effaceable-ramdisk-v5-bounded-matching' if wait_for_service else
                    'effaceable-ramdisk-v4-library-install-name' if library_install_name else
                    'effaceable-ramdisk-v3-device-identity' if device_identity else
                    'effaceable-ramdisk-v2-scope-diagnostics' if scope_diagnostics else 'effaceable-ramdisk-v1')
    build.mkdir(mode=0o700)
    for name in (HELPER_SOURCE, 'virtual_v1_scope.h'):
        shutil.copyfile(stage.PROVISIONING/name, build/name)
    stage.require(stage.digest(build/'virtual_v1_scope.h') ==
                  manifest['virtual_staging']['source_sha256']['virtual_v1_scope.h'], 'Scope contract changed')
    entitlements = {'com.apple.security.iokit-user-client-class': ['AppleEffaceableStorageUserClient']}
    ent = build/'effaceable-entitlements.plist'
    stage.write_new(ent, plistlib.dumps(entitlements))
    sdk = stage.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.decode().strip()
    binary = build/'huntmob-initialize-effaceable'
    stage.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios14.0',
               '-isysroot', sdk, '-Wall', '-Wextra', '-Werror', '-O2',
               '-DHUNTMOB_VM_UUID="'+vm_id+'"', str(build/HELPER_SOURCE), '-o', str(binary)], timeout=60)
    stage.run(['codesign', '-s', '-', '--force', '--identifier', 'com.huntmob.virtual-sep.effaceable-init',
               '--entitlements', str(ent), str(binary)])
    stage.run(['codesign', '--verify', '--strict', str(binary)])
    actual = stage.run(['codesign', '-d', '--entitlements', ':-', str(binary)])
    stage.require(plistlib.loads(actual.stdout) == entitlements, 'Unexpected initializer entitlements')
    base = target/'firmware/RestoreTrustCache'
    stage.require(stage.digest(base) == 'af33b3466bd828bf1ccaa1ab35d060bfcce62ade26ee74acf176501b00ea0d7f',
                  'Pinned stock trustcache differs')
    tc = build/'RestoreTrustCache'
    stage.write_new(tc, stage.merged_trustcache(base.read_bytes(), [cdhash(binary)], vm_id))
    image = build/'RestoreRamDisk.raw'
    shutil.copyfile(SOURCE, image)
    stage.require(stage.digest(image) == SOURCE_SHA and image.stat().st_ino != SOURCE.stat().st_ino,
                  'Ramdisk must start as an independent public copy')
    mount = build/'mount'
    mount.mkdir(mode=0o700)
    before = stage.profile.whole_devices(stage.profile.image_inventory())
    result = stage.profile.run_plist(['hdiutil', 'attach', '-nobrowse', '-noautoopen', '-noautofsck',
             '-owners', 'off', '-imagekey', 'diskimage-class=CRawDiskImage', '-plist',
             '-mountpoint', str(mount), str(image)])
    devices = stage.profile.whole_devices([result]) - before
    stage.require(len(devices) == 1, 'Ambiguous new ramdisk attachment')
    device = devices.pop()
    try:
        entries = [entry for entry in result['system-entities'] if entry.get('mount-point') == str(mount)]
        stage.require(len(entries) == 1 and entries[0].get('dev-entry') == device and
                      entries[0].get('volume-kind') == 'hfs', 'Only the new HFS ramdisk may be staged')
        if online_preloaded:
            utility = stage.safe_path(mount, 'usr/bin/nvmefwupdater')
            stage.require(not utility.is_symlink() and stage.digest(utility) ==
                          '48ee43ea674778fa6aeed41b7e564f829c2efaf87e5f7bb0d08b4f95b2183693',
                          'Only the pinned original preloaded-controller utility may execute')
        guest = stage.safe_path(mount, 'usr/libexec/huntmob-initialize-effaceable')
        stage.write_new(guest, binary.read_bytes(), 0o755)
        stage.write_new(stage.safe_path(mount, 'usr/libexec/huntmob-virtual-sep-v1'),
                        ('HUNTMOB VIRTUAL SEP MODEL V1\n'+vm_id+'\n').encode())
        daemon = {'Label': 'com.huntmob.virtual-sep.effaceable-init',
                  'ProgramArguments': ['/usr/libexec/huntmob-initialize-effaceable'],
                  'RunAtLoad': True, 'KeepAlive': False, 'StandardOutPath': '/dev/console',
                  'StandardErrorPath': '/dev/console'}
        stage.write_new(stage.safe_path(mount, 'System/Library/LaunchDaemons/com.huntmob.effaceable-init.plist'),
                        plistlib.dumps(daemon), 0o644)
        # This clone performs only the explicit initializer. Do not start a
        # broader restore server or KeyMaker while initializing fresh storage.
        for name in ('com.apple.restored_external.plist', 'com.apple.KeyMaker.plist',
                     'com.apple.PurpleReverseProxy.ramdisk.plist'):
            path = stage.safe_path(mount, 'System/Library/LaunchDaemons/'+name)
            saved = path.read_bytes()
            stage.write_new(build/(name+'.original'), saved)
            value = plistlib.loads(saved)
            value['Disabled'] = True
            stage.replace_known(path, plistlib.dumps(value), stage.digest(path))
        stage.run(['codesign', '--verify', '--strict', str(guest)])
        stage.require(stage.digest(guest) == stage.digest(binary), 'Ramdisk helper readback differs')
    finally:
        stage.run(['hdiutil', 'detach', device])
    stage.require(stage.digest(SOURCE) == SOURCE_SHA, 'Public original ramdisk changed')
    record = {'state': 'prepared', 'ramdisk_path': str(image), 'ramdisk_sha256': stage.digest(image),
              'trustcache_path': str(tc), 'trustcache_sha256': stage.digest(tc),
              'source_sha256': stage.digest(build/HELPER_SOURCE), 'helper_sha256': stage.digest(binary),
              'public_original_sha256': SOURCE_SHA, 'secure_root_policy_changed': False,
              'sep_restore_or_erase_requested': False, 'fresh_ns6_zero_verified': True, 'ready': False}
    record['preloaded_controller_online_requested'] = online_preloaded
    if scope_diagnostics:
        manifest['effaceable_ramdisk_scope_rejection'] = manifest['effaceable_ramdisk']
    if device_identity:
        manifest['effaceable_ramdisk_device_identity_predecessor'] = manifest['effaceable_ramdisk']
    if library_install_name:
        manifest['effaceable_ramdisk_library_predecessor'] = manifest['effaceable_ramdisk']
    if wait_for_service:
        manifest['effaceable_ramdisk_matching_predecessor'] = manifest['effaceable_ramdisk']
    if online_preloaded:
        manifest['effaceable_ramdisk_online_predecessor'] = manifest['effaceable_ramdisk']
    manifest['effaceable_ramdisk'] = record
    stage.profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-uuid', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--authorized-lab', action='store_true')
    parser.add_argument('--scope-diagnostics', action='store_true')
    parser.add_argument('--device-identity', action='store_true')
    parser.add_argument('--library-install-name', action='store_true')
    parser.add_argument('--wait-for-service', action='store_true')
    parser.add_argument('--online-preloaded', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        target, manifest = stage.validate(args.vm_uuid)
        require_fresh(target, manifest, args.scope_diagnostics, args.device_identity, args.library_install_name, args.wait_for_service, args.online_preloaded)
        print(json.dumps({'read_only': True, 'ready': False})); return
    stage.require(args.authorized_lab, 'Explicit --authorized-lab required')
    print(json.dumps(stage_ramdisk(args.vm_uuid, args.scope_diagnostics, args.device_identity, args.library_install_name, args.wait_for_service, args.online_preloaded), indent=2))


if __name__ == '__main__': main()
