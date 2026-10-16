#!/usr/bin/env python3
"""Stage a single-use resume for one already-created experimental Data UUID.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a read-only manifest plan.
--apply changes only the known own helper/trustcache and an empty System/mnt2.
It never mounts Data, reads Keychain, starts a VM, runs ClassD/newfs, or restores
SEP. Encryption metadata is an identity guard, not proof of protected storage.
"""
import argparse
import json
import os
import plistlib
import re
import shutil
import stat
from pathlib import Path

import stage_ios_virtual_profile as stage
from install_auxiliary_bootstrap_vm import cdhash

VM_UUID = '52c79047-1d89-4a97-bf6b-cc2d6b9d742c'
DATA_UUID = '6CBC240D-0C5B-4E26-A078-1D3C02181D3E'
OLD_USERDATA = 'ebdd71c955293076f2ee7f8c6baeece984c456de938005417ead27a93db5d283'
OLD_WRAPPER = '1f789b11afd2268ab32fea4f37018a821eba08510e19f45f9343117fa5f313f4'
OLD_TC = '4846f3581d773718323c7169ee28558e500fed0a0fd8e36be687250eabea0e1d'
OLD_SOURCE = 'f18c4920e0dfbf69db49c8ab8392f36e1c122a5f56582a8c5a4f2dadfceb65be'
NEW_SOURCE = '1926ac9eddc4cccfa9fe22d94f8c40fc84a869a0b09a7d296e8468bb1b4c6953'
SCOPE_SHA = '4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050'
STOCK_TC = 'af33b3466bd828bf1ccaa1ab35d060bfcce62ade26ee74acf176501b00ea0d7f'
OBSERVATION = 'observation-20261015-145518'
OBSERVATION_SHA = 'f9c514dfa53d45ee394cf7c512076a2a472a24e21b5bb2d3f0c87adab47a40f5'
BOOT_LOG_SHA = '1dfad01ba44855c9cf669eca4e554916b410eb503bea049394c66311e94917ee'
VOLUMES = {
    1: ('System', 'AzulSeed18A5351d.N104N841DeveloperOS', '5133F48D-5D9E-499B-A8BA-45E692E36FD9', False),
    2: ('Data', 'Data', DATA_UUID, True),
    3: ('xART', 'xART', '0892314C-095A-432F-BA2D-51D059B6F8E1', False),
    4: ('Hardware', 'Hardware', '25C3A085-8359-4B72-8084-015AACBDB49B', False),
    5: ('Preboot', 'Preboot', '58777F82-EDFF-4269-A704-2FDB6032155B', False),
}


def check_predecessor(manifest):
    prior = manifest.get('virtual_staging', {})
    stage.require(manifest.get('vm_uuid') == VM_UUID and manifest.get('root_provisioned') is True and
                  manifest.get('old_cohort_cloned') is False and manifest.get('ready') is False and
                  prior.get('phase') == 'data-checkpoint' and
                  prior.get('helper_sha256') == {'init_data_protection': OLD_WRAPPER,
                                                'huntmob-prepare-userdata': OLD_USERDATA} and
                  prior.get('source_sha256', {}).get('prepare_userdata_virtual_v1.c') == OLD_SOURCE and
                  prior.get('source_sha256', {}).get('virtual_v1_scope.h') == SCOPE_SHA and
                  prior.get('trustcache_sha256') == OLD_TC and
                  manifest.get('data_after_effaceable_helper', {}).get('helper_sha256') == OLD_USERDATA and
                  manifest.get('effaceable_initialized_and_cold_verified') and
                  'created_data_resume' not in manifest,
                  'Only the exact known created-Data predecessor is accepted once')
    return prior


def checked_layout(container, whole_device):
    """Pure exact-UUID/role/index contract; never mounts or unlocks Data."""
    stage.require(re.fullmatch(r'/dev/disk[0-9]+', whole_device) and
                  container.get('PhysicalStores') and
                  len(container['PhysicalStores']) == 1 and
                  container['PhysicalStores'][0].get('DeviceIdentifier') == whole_device[5:]+'s1',
                  'Container is not exclusively on the newly owned loop partition')
    reference = container.get('ContainerReference', '')
    stage.require(re.fullmatch(r'disk[0-9]+', reference), 'Invalid APFS container reference')
    volumes = container.get('Volumes', [])
    stage.require(len(volumes) == 5, 'Exactly System/Data/xART/Hardware/Preboot required')
    by_id = {v.get('DeviceIdentifier'): v for v in volumes}
    stage.require(len(by_id) == 5, 'Duplicate APFS volume identifiers')
    for index, (role, name, expected_uuid, encrypted) in VOLUMES.items():
        volume = by_id.get(reference+'s'+str(index), {})
        stage.require(volume.get('Roles') == [role] and volume.get('Name') == name and
                      volume.get('APFSVolumeUUID') == expected_uuid and
                      volume.get('Encryption') is encrypted and not volume.get('MountPoint'),
                      'Existing volume identity, role, encryption or mount state differs')
        if index == 2:
            stage.require(volume.get('Locked') is True,
                          'The exact encrypted Data must remain locked and unmounted on host')
    return '/dev/'+reference+'s1'


def owned_layout(device):
    containers = stage.profile.run_plist(['/usr/sbin/diskutil', 'apfs', 'list', '-plist'])['Containers']
    owned = [c for c in containers if any(v.get('DeviceIdentifier') == device[5:]+'s1'
                                        for v in c.get('PhysicalStores', []))]
    stage.require(len(owned) == 1, 'Ambiguous owned APFS container')
    return checked_layout(owned[0], device)


def check_mountpoint(path, create=False):
    """Accept only an absent mountpoint or an ordinary empty directory."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if create:
            path.mkdir(mode=0o755)
            stage.require(stat.S_ISDIR(path.lstat().st_mode) and not any(path.iterdir()),
                          'New mountpoint readback failed')
        return False
    stage.require(stat.S_ISDIR(metadata.st_mode) and not os.path.ismount(path) and
                  not any(path.iterdir()), 'System/mnt2 must be an empty ordinary unmounted directory')
    return True


def check_observation(target):
    directory = target/OBSERVATION
    observation, log = directory/'observation.json', directory/'boot.log'
    stage.require(directory.is_dir() and not directory.is_symlink() and
                  not observation.is_symlink() and not log.is_symlink() and
                  stage.digest(observation) == OBSERVATION_SHA and stage.digest(log) == BOOT_LOG_SHA,
                  'The preceding Data-creation observation changed')
    proof = json.loads(observation.read_text())
    stage.require(proof.get('vm_uuid') == VM_UUID and proof.get('qmp_quit_accepted') is True and
                  proof.get('effaceable_ramdisk_requested') is False and
                  proof.get('sep_profile') == 'serving' and proof.get('aess_rejected_command_count') == 0,
                  'The preceding native Data attempt does not match the owned scope')


def check_files(target, manifest, prior):
    old_build = target/'virtual-helper-data-after-effaceable-v1'
    wrapper = target/'virtual-helper-build-data-checkpoint/init_data_protection'
    for path, expected in ((old_build/'huntmob-prepare-userdata', OLD_USERDATA),
                           (old_build/'prepare_userdata_virtual_v1.c', OLD_SOURCE),
                           (old_build/'virtual_v1_scope.h', SCOPE_SHA),
                           (wrapper, OLD_WRAPPER),
                           (stage.PROVISIONING/'prepare_userdata_virtual_v1.c', NEW_SOURCE),
                           (stage.PROVISIONING/'virtual_v1_scope.h', SCOPE_SHA)):
        stage.require(path.is_file() and not path.is_symlink() and stage.digest(path) == expected,
                      'Bound helper/source changed')
    entitlements = stage.PROVISIONING/'userdata-entitlements.plist'
    stage.require(not entitlements.is_symlink() and
                  entitlements.read_bytes() == (old_build/'userdata-entitlements.plist').read_bytes(),
                  'Resume cannot change helper entitlements')
    tc, base = target/'firmware/VirtualTrustCache', target/'firmware/RestoreTrustCache'
    record = manifest['firmware']['files']['RestoreTrustCache']
    stage.require(Path(record['path']) == tc and record['sha256'] == OLD_TC and
                  not tc.is_symlink() and stage.digest(tc) == OLD_TC and
                  not base.is_symlink() and stage.digest(base) == STOCK_TC,
                  'Bound trustcache changed')
    check_observation(target)
    return old_build, wrapper, tc, base


def compile_helper(build):
    build.mkdir(mode=0o700, exist_ok=False)
    for name in ('prepare_userdata_virtual_v1.c', 'virtual_v1_scope.h', 'userdata-entitlements.plist'):
        shutil.copyfile(stage.PROVISIONING/name, build/name)
    stage.require(stage.digest(build/'prepare_userdata_virtual_v1.c') == NEW_SOURCE and
                  stage.digest(build/'virtual_v1_scope.h') == SCOPE_SHA, 'Copied resume sources differ')
    sdk = stage.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.decode().strip()
    binary = build/'huntmob-prepare-userdata'
    stage.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios14.0',
               '-isysroot', sdk, '-Wall', '-Wextra', '-Werror', '-O2',
               '-DHUNTMOB_VM_UUID="'+VM_UUID+'"', '-DHUNTMOB_EFFACEABLE_OBSERVE_ONLY=0',
               '-DHUNTMOB_RESUME_CREATED_DATA=1', '-DHUNTMOB_EXPECTED_DATA_UUID="'+DATA_UUID+'"',
               str(build/'prepare_userdata_virtual_v1.c'), '-o', str(binary)], timeout=60)
    stage.run(['codesign', '-s', '-', '--force', '--identifier', 'com.huntmob.virtual-sep.prepare-userdata',
               '--entitlements', str(build/'userdata-entitlements.plist'), str(binary)])
    stage.run(['codesign', '--verify', '--strict', str(binary)])
    actual = stage.run(['codesign', '-d', '--entitlements', ':-', str(binary)])
    stage.require(plistlib.loads(actual.stdout) == plistlib.loads((build/'userdata-entitlements.plist').read_bytes()),
                  'Compiled resume entitlements differ')
    return binary


def attach_owned(target, manifest):
    """Recover only this invocation's exact image if attach fails midway."""
    profile = stage.profile
    previous = profile.whole_devices(profile.image_inventory())
    try:
        return stage.attach_backing(target, manifest)
    except Exception:
        image = target/'namespace-1.raw'
        try:
            device = profile.discover_owned_attachment(image, manifest['backings'][image.name], previous)
        except (ValueError, OSError):
            raise
        stage.run(['/usr/bin/hdiutil', 'detach', device])
        raise


def install(vm_id):
    stage.require(vm_id == VM_UUID, 'Only the single owned profile is accepted')
    target, manifest = stage.validate(vm_id)
    prior = check_predecessor(manifest)
    stage.require(not any(target.glob('observation-*/qmp.sock')), 'A VM socket is present')
    old_build, wrapper, tc, base = check_files(target, manifest, prior)
    build = target/'virtual-helper-resume-created-data-v1'
    binary = compile_helper(build)
    custom = stage.merged_trustcache(base.read_bytes(), [cdhash(wrapper), cdhash(binary)], vm_id)
    stage.write_new(build/'previous-VirtualTrustCache', tc.read_bytes())
    stage.write_new(build/'previous-virtual-profile.json', (target/'virtual-profile.json').read_bytes())
    stage.write_new(build/'previous-huntmob-prepare-userdata', (old_build/'huntmob-prepare-userdata').read_bytes(), 0o755)
    record = {'state': 'applying', 'Data_UUID': DATA_UUID, 'source_sha256': NEW_SOURCE,
              'helper_sha256': stage.digest(binary), 'preceding_helper_sha256': OLD_USERDATA,
              'preceding_trustcache_sha256': OLD_TC, 'observation_sha256': OBSERVATION_SHA,
              'ClassD_requested': False, 'newfs_requested': False, 'host_Data_mount_requested': False,
              'storage_integrity_validated': False, 'ready': False}
    # Persist the single-use attempt before any filesystem mutation. A partial
    # failure cannot silently retry against a different helper or Data volume.
    manifest['created_data_resume'] = record
    stage.profile.write_manifest(target, manifest)
    mount = target/'SystemStage-resume-created-data-v1'
    mount.mkdir(mode=0o700, exist_ok=False)
    device, before = attach_owned(target, manifest)
    mounted = False
    try:
        system = owned_layout(device)
        stage.run(['/sbin/mount_apfs', '-o', 'nobrowse,noowners', system, str(mount)])
        mounted = True
        for relative, sha in (('usr/libexec/seputil', stage.STOCK_SHA),
                              ('usr/libexec/huntmob-original/init_data_protection', stage.STOCK_SHA),
                              ('usr/libexec/init_data_protection', OLD_WRAPPER),
                              ('usr/libexec/huntmob-prepare-userdata', OLD_USERDATA)):
            path = stage.safe_path(mount, relative)
            stage.require(not path.is_symlink() and stage.digest(path) == sha, 'Guest predecessor changed')
        marker = stage.safe_path(mount, 'usr/libexec/huntmob-prepare-data')
        restore = stage.safe_path(mount, 'usr/libexec/huntmob-restore-sep.img4')
        stage.require(not marker.is_symlink() and marker.read_bytes() == b'HUNTMOB VIRTUAL SEP V1 FRESH DATA\n' and
                      not restore.exists() and not restore.is_symlink(), 'Wrong normal Data phase')
        mountpoint = stage.safe_path(mount, 'mnt2')
        check_mountpoint(mountpoint)
        stage.profile.verify_attachment(target/'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        check_mountpoint(mountpoint, create=True)
        guest = stage.safe_path(mount, 'usr/libexec/huntmob-prepare-userdata')
        stage.replace_known(guest, binary.read_bytes(), OLD_USERDATA)
        stage.run(['codesign', '--verify', '--strict', str(guest)])
        stage.require(stage.digest(guest) == stage.digest(binary), 'Resume helper readback differs')
        stage.replace_known(tc, custom, OLD_TC)
        check_mountpoint(mountpoint)
    finally:
        if mounted:
            stage.run(['/sbin/umount', str(mount)])
        stage.profile.verify_attachment(target/'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        stage.run(['/usr/bin/hdiutil', 'detach', device])
    record.update(state='installed', trustcache_sha256=stage.digest(tc), System_mnt2_precreated_empty=True,
                  Data_never_mounted_on_host=True, stock_verifier_unchanged=True, stock_wrapper_unchanged=True)
    prior['source_sha256']['prepare_userdata_virtual_v1.c'] = NEW_SOURCE
    prior['helper_sha256']['huntmob-prepare-userdata'] = record['helper_sha256']
    prior['trustcache_sha256'] = record['trustcache_sha256']
    manifest['firmware']['files']['RestoreTrustCache'].update(sha256=record['trustcache_sha256'], bytes=tc.stat().st_size)
    stage.profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-uuid', choices=[VM_UUID], required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--authorized-lab', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        target, manifest = stage.validate(args.vm_uuid)
        prior = check_predecessor(manifest)
        check_files(target, manifest, prior)
        print(json.dumps({'read_only': True, 'Data_UUID': DATA_UUID, 'ready': False,
                          'host_Data_mount_requested': False, 'no_ClassD_no_newfs_on_resume': True}))
        return
    stage.require(args.authorized_lab, 'Explicit --authorized-lab required')
    print(json.dumps(install(args.vm_uuid), indent=2))


if __name__ == '__main__':
    main()
