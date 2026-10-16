#!/usr/bin/env python3
"""Finish only the verified guest-created owned auxiliary layout.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Copies this fresh cohort's public
Preboot files and deletes only the UUID-bound newly reserved Data placeholder.
"""
import argparse
import json
import os
from pathlib import Path

import stage_ios_virtual_profile as stage
import stage_ios_virtual_auxiliary as auxiliary
import prepare_ios_virtual_profile as profile


def require(condition, message):
    profile.require(condition, message)


def finish(vm_id):
    target, manifest = stage.validate(vm_id)
    require(manifest.get('auxiliary_bootstrap', {}).get('state') == 'installed' and
            not manifest.get('auxiliary_volumes_staged'), 'Only the current auxiliary bootstrap can be completed')
    record = manifest['auxiliary_staging_in_progress']
    reserve = record['new_empty_placeholder']
    runs = sorted(target.glob('observation-*'))
    require(bool(runs), 'No guest observation exists')
    observation = json.loads((runs[-1] / 'observation.json').read_text())
    content = (runs[-1] / 'boot.log').read_text(errors='replace')
    require(observation.get('provisioning_checkpoint_observed') is True and
            observation.get('qmp_quit_accepted') is True and
            'virtual v1 auxiliary volumes prepared' in content,
            'Guest auxiliary checkpoint and flushed QMP shutdown required')
    device, before = stage.attach_backing(target, manifest)
    mounted = []
    try:
        container = auxiliary.owned_container(device)
        cid = container['ContainerReference']
        volumes = container['Volumes']
        require(len(volumes) == 5, 'Expected exactly five freshly prepared volumes')
        expected = {1: ['System'], 2: ['Data'], 3: ['xART'], 4: ['Hardware'], 5: ['Preboot']}
        indexed = {}
        for index, roles in expected.items():
            matches = [v for v in volumes if v['DeviceIdentifier'] == cid + 's' + str(index)]
            require(len(matches) == 1 and matches[0].get('Roles') == roles and matches[0].get('Encryption') is False
                    and not matches[0].get('MountPoint'), 'Owned fresh auxiliary role/index/encryption differs')
            indexed[index] = matches[0]
        placeholder = indexed[2]
        require(all(placeholder.get(key) == reserve[key] for key in ('APFSVolumeUUID', 'Name', 'Roles', 'Encryption')),
                'Placeholder UUID changed; deletion refused')
        require(indexed[1]['APFSVolumeUUID'] == record['system_uuid'], 'System UUID changed')
        require(all(indexed[i]['Name'] == n for i, n in ((3, 'xART'), (4, 'Hardware'), (5, 'Preboot'))),
                'Guest auxiliary names differ')
        record['created_volumes'] = [{key: indexed[i][key] for key in
            ('Name', 'Roles', 'DeviceIdentifier', 'APFSVolumeUUID', 'Encryption')} for i in (3, 4, 5)]
        for name, index, options in (('NativeAuxSystemReadOnly', 1, 'rdonly,nobrowse,noowners'),
                                     ('NativeAuxPrebootMount', 5, 'nobrowse,noowners')):
            mount = target / name
            mount.mkdir(mode=0o700)
            stage.run(['/sbin/mount_apfs', '-o', options, '/dev/' + indexed[index]['DeviceIdentifier'], str(mount)])
            mounted.append(mount)
        system, preboot = mounted
        ticket = manifest['virtual_staging']['preboot_ticket_sha384'].upper()
        source = system / 'private/preboot' / ticket
        require(source.is_dir() and not source.is_symlink(), 'Own public Preboot source missing')
        destination = preboot / ticket
        require(not destination.exists(), 'New Preboot is not empty for this ticket')
        copied = {}
        for directory, folders, files in os.walk(source, followlinks=False):
            output = destination / Path(directory).relative_to(source)
            output.mkdir(mode=0o755, parents=True, exist_ok=True)
            for name in folders:
                require(not (Path(directory) / name).is_symlink(), 'Public firmware directory symlink refused')
            for name in files:
                file = Path(directory) / name
                require(file.is_file() and not file.is_symlink(), 'Public firmware file symlink refused')
                stage.write_new(output / name, file.read_bytes(), 0o644)
                require(stage.digest(output / name) == stage.digest(file), 'Public Preboot copy differs')
                copied[str((output / name).relative_to(preboot))] = stage.digest(file)
        require(copied.get(ticket + '/usr/standalone/firmware/sep-firmware.img4') == stage.SEP['serving'][1],
                'Serving SEP is not installed in the actual new Preboot volume')
        record['preboot_file_sha256'] = copied
        profile.verify_attachment(target / 'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        current = auxiliary.owned_container(device)
        match = auxiliary.volume_by_guid(current, reserve['APFSVolumeUUID'])
        require(all(match.get(key) == reserve[key] for key in ('Name', 'Roles', 'Encryption')) and
                match['DeviceIdentifier'] == cid + 's2' and not match.get('MountPoint'),
                'Only the known newly reserved placeholder may be removed')
        stage.run(['/usr/sbin/diskutil', 'apfs', 'deleteVolume', '/dev/' + match['DeviceIdentifier']], timeout=60)
        final = auxiliary.owned_container(device)
        require(len(final['Volumes']) == 4 and not any('Data' in v.get('Roles', []) or
                v['DeviceIdentifier'] == cid + 's2' or v['APFSVolumeUUID'] == reserve['APFSVolumeUUID']
                for v in final['Volumes']), 'Fresh Data slot was not released')
        record.update(placeholder_deleted=True, data_slot_2_absent=True, completed=True,
                      auxiliaries_formatted_by_original_ios_tool=True,
                      placeholder_used_only_before_sep_mkb=True,
                      preboot_firmware_readback_matches=True,
                      guest_checkpoint=str(runs[-1]), ready=False)
        stage.write_new(target / 'auxiliary-staging-completed.json', json.dumps(record, indent=2).encode())
    finally:
        for mount in reversed(mounted):
            stage.run(['/sbin/umount', str(mount)])
        profile.verify_attachment(target / 'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        stage.run(['/usr/bin/hdiutil', 'detach', device])
    manifest.update(auxiliary_volumes_staged=True, auxiliary_layout=record, owned_device_detached=True)
    profile.write_manifest(target, manifest)
    return {'completed': True, 'placeholder_deleted': True, 'preboot_readback_matches': True, 'ready': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--vm-uuid', required=True)
    args = parser.parse_args()
    print(json.dumps(finish(args.vm_uuid)))


if __name__ == '__main__':
    main()
