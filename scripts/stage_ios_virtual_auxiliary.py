#!/usr/bin/env python3
"""Prepare NEW xART/Hardware/Preboot volumes in the owned experimental cohort.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Never clones an old keybag or locker.
A new empty unencrypted placeholder reserves Data slot2 while auxiliary slots
3/4/5 are created; only that exact newly created placeholder may be deleted.
"""
import argparse
import json
import os
import shutil
from pathlib import Path

import stage_ios_virtual_profile as stage
import prepare_ios_virtual_profile as profile


def require(condition, message):
    profile.require(condition, message)


def owned_container(device):
    listing = profile.run_plist(['/usr/sbin/diskutil', 'apfs', 'list', '-plist'])['Containers']
    owned = [item for item in listing if [store.get('DeviceIdentifier') for store in
              item.get('PhysicalStores', [])] == [device.removeprefix('/dev/') + 's1']]
    require(len(owned) == 1, 'Expected one exact owned APFS physical store')
    return owned[0]


def volume_by_guid(container, guid):
    matches = [v for v in container['Volumes'] if v.get('APFSVolumeUUID') == guid]
    require(len(matches) == 1, 'New volume UUID is no longer unique in its owned container')
    return matches[0]


def add_volume(target, manifest, device, before, container_id, name, role, index, expected_roles):
    image = target / 'namespace-1.raw'
    profile.verify_attachment(image, manifest['backings'][image.name], device, before)
    old = owned_container(device)
    require(old['ContainerReference'] == container_id, 'Container identity changed')
    old_ids = {v['APFSVolumeUUID'] for v in old['Volumes']}
    stage.run(['/usr/sbin/diskutil', 'apfs', 'addVolume', container_id, 'APFSX', name,
               '-role', role, '-nomount'], timeout=60)
    new = owned_container(device)
    additions = [v for v in new['Volumes'] if v['APFSVolumeUUID'] not in old_ids]
    require(len(additions) == 1, 'APFS did not create exactly one new volume')
    volume = additions[0]
    require(volume.get('Name') == name and volume.get('Roles') == expected_roles and
            volume.get('DeviceIdentifier') == container_id + 's' + str(index) and
            volume.get('Encryption') is False and not volume.get('MountPoint'),
            'New volume role/index/encryption differs from the fresh layout')
    return {key: volume[key] for key in ('Name', 'Roles', 'DeviceIdentifier', 'APFSVolumeUUID', 'Encryption')}


def prepare(vm_id):
    target, manifest = stage.validate(vm_id)
    require(manifest['virtual_staging']['phase'] == 'restore-checkpoint' and
            not manifest.get('auxiliary_volumes_staged') and not (target / 'auxiliary-staging-started.json').exists(),
            'Auxiliary staging is only for the first owned restore profile')
    device, before = stage.attach_backing(target, manifest)
    mounted = []
    try:
        initial = owned_container(device)
        volumes = initial['Volumes']
        container = initial['ContainerReference']
        require(len(volumes) == 1 and volumes[0].get('Roles') == ['System'] and
                volumes[0]['DeviceIdentifier'] == container + 's1' and volumes[0].get('Encryption') is False,
                'Only pristine System may exist before auxiliary creation')
        system_guid = volumes[0]['APFSVolumeUUID']
        record = {'schema': 'huntmob.virtual-sep-auxiliary-layout.v1', 'ready': False,
                  'vm_uuid': vm_id, 'system_uuid': system_guid, 'created_volumes': [],
                  'historical_data_or_keys_copied': False}
        stage.write_new(target / 'auxiliary-staging-started.json', json.dumps(record, indent=2).encode())
        reserve = add_volume(target, manifest, device, before, container,
                             'HuntMobEmptyDataSlot', 'D', 2, ['Data'])
        record['new_empty_placeholder'] = reserve
        manifest['auxiliary_staging_in_progress'] = record
        profile.write_manifest(target, manifest)
        for name, role, index, roles in [('xART', 'X', 3, ['xART']),
                                         ('Hardware', 'H', 4, ['Hardware']),
                                         ('Preboot', 'B', 5, ['Preboot'])]:
            volume = add_volume(target, manifest, device, before, container, name, role, index, roles)
            record['created_volumes'].append(volume)
            profile.write_manifest(target, manifest)
        system_mount = target / 'AuxiliarySystemReadOnly'
        preboot_mount = target / 'AuxiliaryPrebootMount'
        for mount in (system_mount, preboot_mount):
            mount.mkdir(mode=0o700)
        stage.run(['/sbin/mount_apfs', '-o', 'rdonly,nobrowse,noowners',
                   '/dev/' + volumes[0]['DeviceIdentifier'], str(system_mount)])
        mounted.append(system_mount)
        preboot = record['created_volumes'][-1]
        stage.run(['/sbin/mount_apfs', '-o', 'nobrowse,noowners',
                   '/dev/' + preboot['DeviceIdentifier'], str(preboot_mount)])
        mounted.append(preboot_mount)
        ticket = manifest['virtual_staging']['preboot_ticket_sha384'].upper()
        source = system_mount / 'private/preboot' / ticket
        require(source.is_dir() and not source.is_symlink(), 'Owned staged Preboot tree missing')
        destination = preboot_mount / ticket
        require(not destination.exists(), 'Fresh Preboot unexpectedly contains this ticket')
        copied = {}
        for directory, folders, files in os.walk(source, followlinks=False):
            relative = Path(directory).relative_to(source)
            output = destination / relative
            output.mkdir(mode=0o755, parents=True, exist_ok=True)
            for name in folders:
                require(not (Path(directory) / name).is_symlink(), 'Preboot source directory symlink refused')
            for name in files:
                file = Path(directory) / name
                require(file.is_file() and not file.is_symlink(), 'Preboot source symlink/non-file refused')
                stage.write_new(output / name, file.read_bytes(), 0o644)
                require(stage.digest(output / name) == stage.digest(file), 'Preboot readback mismatch')
                copied[str((output / name).relative_to(preboot_mount))] = stage.digest(file)
        expected_sep = ticket + '/usr/standalone/firmware/sep-firmware.img4'
        require(copied.get(expected_sep) == stage.SEP['serving'][1], 'Serving SEP is not bound to the new Preboot')
        record['preboot_file_sha256'] = copied
        # Delete only the placeholder this invocation created, still unencrypted,
        # never mounted or associated with MKB. No existing Data is accepted.
        profile.verify_attachment(target / 'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        current = owned_container(device)
        placeholder = volume_by_guid(current, reserve['APFSVolumeUUID'])
        require(placeholder.get('DeviceIdentifier') == reserve['DeviceIdentifier'] and
                placeholder.get('Name') == 'HuntMobEmptyDataSlot' and placeholder.get('Roles') == ['Data'] and
                placeholder.get('Encryption') is False and not placeholder.get('MountPoint'),
                'Empty newly created placeholder changed; deletion refused')
        stage.run(['/usr/sbin/diskutil', 'apfs', 'deleteVolume', '/dev/' + reserve['DeviceIdentifier']], timeout=60)
        final = owned_container(device)
        require(not any(v['APFSVolumeUUID'] == reserve['APFSVolumeUUID'] or
                        'Data' in v.get('Roles', []) or v.get('DeviceIdentifier') == container + 's2'
                        for v in final['Volumes']), 'Data placeholder still present')
        require([v['APFSVolumeUUID'] for v in final['Volumes'] if v.get('Roles') == ['System']] == [system_guid],
                'Original stock System identity changed')
        for created in record['created_volumes']:
            actual = volume_by_guid(final, created['APFSVolumeUUID'])
            require(all(actual.get(key) == created[key] for key in
                        ('Roles', 'DeviceIdentifier', 'Name', 'APFSVolumeUUID')),
                    'New auxiliary identity or role changed')
        record.update(placeholder_deleted=True, data_slot_2_absent=True, completed=True)
        stage.write_new(target / 'auxiliary-staging-completed.json', json.dumps(record, indent=2).encode())
    finally:
        for mount in reversed(mounted):
            stage.run(['/sbin/umount', str(mount)])
        profile.verify_attachment(target / 'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        stage.run(['/usr/bin/hdiutil', 'detach', device])
    manifest.update(auxiliary_volumes_staged=True, auxiliary_layout=record,
                    owned_device_detached=True)
    profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--vm-uuid', required=True)
    args = parser.parse_args()
    result = prepare(args.vm_uuid)
    print(json.dumps({key: result[key] for key in ('completed', 'placeholder_deleted', 'data_slot_2_absent', 'ready')}))


if __name__ == '__main__':
    main()
