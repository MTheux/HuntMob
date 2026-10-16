#!/usr/bin/env python3
"""Swap only the known owned wrapper/TC for fresh auxiliary bootstrap or restore.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is read-only. No guest starts,
Keychain root delivery, SEP initialization, or historical image access occurs.
"""
import argparse
import json
import plistlib
import re
import shutil
from pathlib import Path

import stage_ios_virtual_profile as stage
import stage_ios_virtual_auxiliary as auxiliary
import prepare_ios_virtual_profile as profile


def require(condition, message):
    profile.require(condition, message)


def checked_layout(container, reserve, require_auxiliary):
    volumes = container['Volumes']
    systems = [v for v in volumes if v.get('Roles') == ['System'] and v.get('Encryption') is False]
    require(len(systems) == 1, 'Expected the owned stock System')
    require(systems[0]['DeviceIdentifier'] == container['ContainerReference']+'s1', 'System slot changed')
    expected = {1:['System']}
    if not require_auxiliary:
        placeholder = auxiliary.volume_by_guid(container, reserve['APFSVolumeUUID'])
        require(all(placeholder.get(k) == reserve[k] for k in ('Name','Roles','APFSVolumeUUID','Encryption')) and
                placeholder.get('DeviceIdentifier') == container['ContainerReference']+'s2' and
                not placeholder.get('MountPoint'), 'Owned empty Data reservation changed')
        expected[2]=['Data']
    else:
        require(not any(v.get('APFSVolumeUUID')==reserve['APFSVolumeUUID'] or
                        'Data' in v.get('Roles',[]) for v in volumes),
                'Restore requires the owned placeholder already deleted and no Data')
        expected.update({3:['xART'],4:['Hardware'],5:['Preboot']})
    require(len(volumes) == len(expected), 'Unexpected volumes in owned bootstrap container')
    for index, roles in expected.items():
        matches=[v for v in volumes if v.get('DeviceIdentifier') == container['ContainerReference']+'s'+str(index)]
        require(len(matches)==1 and matches[0].get('Roles')==roles and matches[0].get('Encryption') is False,
                'Auxiliary bootstrap layout differs')
    return '/dev/'+systems[0]['DeviceIdentifier']


def cdhash(binary):
    result=stage.run(['codesign','-d','--verbose=4',str(binary)])
    hashes=re.findall(rb'^CDHash=([0-9a-f]{40})$',result.stderr,re.MULTILINE)
    require(len(hashes)==1,'Cannot bind helper CodeDirectory')
    return hashes[0].decode()


def prepare_binary(target, manifest, action):
    record=manifest.get('auxiliary_bootstrap')
    if action in ('refresh-restore','refresh-timeouts','refresh-registration'):
        predecessor={'refresh-timeouts':'restore_helper_refresh',
                     'refresh-registration':'restore_helper_diagnostics'}
        destination={'refresh-timeouts':'restore_helper_diagnostics',
                     'refresh-registration':'restore_helper_registration'}
        require(record and record.get('state')=='restored-original' and
                (not manifest.get('restore_helper_refresh') if action=='refresh-restore'
                 else manifest.get(predecessor[action]) and not manifest.get(destination[action])),
                'Restore refresh requires its known preceding helper and is single-use')
        expected=manifest['virtual_staging']['helper_sha256']['init_data_protection']
        original=target/'auxiliary-bootstrap-build/original-init_data_protection'
        require(not original.is_symlink() and stage.digest(original)==record['original_wrapper_sha256'],
                'Preserved original restore wrapper changed')
        if action=='refresh-restore':
            require(stage.digest(original)==expected,'Original restored wrapper no longer current')
        else:
            refresh=manifest[predecessor[action]]
            prior=target/('virtual-helper-restore-refresh/init_data_protection' if action=='refresh-timeouts'
                          else 'virtual-helper-restore-timeout-diagnostics/init_data_protection')
            require(not prior.is_symlink() and stage.digest(prior)==expected==refresh['wrapper_sha256'] and
                    refresh['original_wrapper_sha256']==record['original_wrapper_sha256'],
                    'Preceding reviewed restore wrapper changed')
            for name,sha in refresh['source_sha256'].items():
                require(stage.digest(prior.parent/name)==sha==manifest['virtual_staging']['source_sha256'][name],
                        'Preceding reviewed helper source changed')
        require(stage.digest(stage.PROVISIONING/'virtual_v1_scope.h')==
                manifest['virtual_staging']['source_sha256']['virtual_v1_scope.h'],
                'Restore refresh may not change the per-profile scope contract')
        build=target/('virtual-helper-restore-refresh' if action=='refresh-restore'
                     else 'virtual-helper-restore-timeout-diagnostics' if action=='refresh-timeouts'
                     else 'virtual-helper-restore-registration')
        build.mkdir(mode=0o700)
        for name in ('init_storage_virtual_v1.c','virtual_v1_scope.h'):
            shutil.copyfile(stage.PROVISIONING/name,build/name)
        sdk=stage.run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.decode().strip()
        binary=build/'init_data_protection'
        stage.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios14.0','-isysroot',sdk,
                   '-Wall','-Wextra','-Werror','-O2','-DHUNTMOB_VM_UUID="'+manifest['vm_uuid']+'"',
                   str(build/'init_storage_virtual_v1.c'),'-o',str(binary)],timeout=60)
        stage.run(['codesign','-s','-','--force','--identifier','com.apple.seputil',str(binary)])
        stage.run(['codesign','--verify','--strict',str(binary)])
        actual=stage.run(['codesign','-d','--entitlements',':-',str(binary)])
        require(not actual.stdout.strip(), 'Refreshed restore wrapper must have no extra entitlements')
        return binary,record
    if action=='restore-original':
        require(record and record.get('state')=='installed','Bootstrap is not installed')
        original=target/'auxiliary-bootstrap-build/original-init_data_protection'
        require(not original.is_symlink() and stage.digest(original)==record['original_wrapper_sha256'],
                'Saved original owned wrapper changed')
        return original,record
    if action=='authorize-bootstrap':
        require(record and record.get('state')=='installed' and
                not record.get('parent_xart_entitlement_authorized'),
                'Only the existing unauthorized bootstrap may be authorized once')
        original=target/'auxiliary-bootstrap-build/init_data_protection'
        require(not original.is_symlink() and stage.digest(original)==record['bootstrap_wrapper_sha256'] and
                manifest['virtual_staging']['helper_sha256']['init_data_protection']==record['bootstrap_wrapper_sha256'],
                'Existing compiled bootstrap identity changed')
        for name,expected in record['source_sha256'].items():
            require(stage.digest(target/'auxiliary-bootstrap-build'/name)==expected,
                    'Existing bootstrap source changed')
        build=target/'auxiliary-bootstrap-authorization'
        build.mkdir(mode=0o700)
        binary=build/'init_data_protection'
        stage.write_new(binary,original.read_bytes(),0o755)
        entitlements=build/'parent-xart-entitlement.plist'
        stage.write_new(entitlements,plistlib.dumps({'com.apple.private.apfs.xart':True}))
        stage.run(['codesign','-s','-','--force','--identifier','com.apple.seputil',
                   '--entitlements',str(entitlements),str(binary)])
        stage.run(['codesign','--verify','--strict',str(binary)])
        # The ':' raw-XML display form remains needed on this host: bare '-'
        # prints a human-readable dictionary rather than a parseable plist.
        actual=stage.run(['codesign','-d','--entitlements',':-',str(binary)])
        require(plistlib.loads(actual.stdout)=={'com.apple.private.apfs.xart':True},
                'Bootstrap must have only the required parent xART entitlement')
        return binary,record
    require(not record,'Bootstrap already attempted; do not repeat formatting')
    build=target/'auxiliary-bootstrap-build'
    build.mkdir(mode=0o700)
    for name in ('init_auxiliary_virtual_v1.c','virtual_v1_scope.h'):
        shutil.copyfile(stage.PROVISIONING/name,build/name)
    sdk=stage.run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.decode().strip()
    binary=build/'init_data_protection'
    stage.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios14.0','-isysroot',sdk,
               '-Wall','-Wextra','-Werror','-O2','-DHUNTMOB_VM_UUID="'+manifest['vm_uuid']+'"',
               str(build/'init_auxiliary_virtual_v1.c'),'-o',str(binary)],timeout=60)
    stage.run(['codesign','-s','-','--force','--identifier','com.apple.seputil',str(binary)])
    stage.run(['codesign','--verify','--strict',str(binary)])
    return binary,{'state':'prepared','source_sha256':{name:stage.digest(build/name) for name in
                   ('init_auxiliary_virtual_v1.c','virtual_v1_scope.h')},'ready':False}


def install(vm_id,action):
    target,manifest=stage.validate(vm_id)
    staging=manifest['virtual_staging']
    require(staging['phase']=='restore-checkpoint','Only the first restore phase is accepted')
    progress=manifest.get('auxiliary_staging_in_progress',{})
    reserve=progress.get('new_empty_placeholder')
    require(reserve and reserve.get('Name')=='HuntMobEmptyDataSlot' and reserve.get('Roles')==['Data'] and
            reserve.get('Encryption') is False,'Exact new empty Data reservation required')
    binary,record=prepare_binary(target,manifest,action)
    userdata=target/'virtual-helper-build-restore-checkpoint/huntmob-prepare-userdata'
    require(not userdata.is_symlink() and stage.digest(userdata)==staging['helper_sha256']['huntmob-prepare-userdata'],
            'Data helper changed')
    base=target/'firmware/RestoreTrustCache'
    require(stage.digest(base)=='af33b3466bd828bf1ccaa1ab35d060bfcce62ade26ee74acf176501b00ea0d7f',
            'Pinned stock trustcache changed')
    custom=stage.merged_trustcache(base.read_bytes(),[cdhash(binary),cdhash(userdata)],vm_id)
    tc=Path(manifest['firmware']['files']['RestoreTrustCache']['path'])
    require(tc==target/'firmware/VirtualTrustCache' and not tc.is_symlink() and
            stage.digest(tc)==staging['trustcache_sha256'],'Owned trustcache changed')
    expected=staging['helper_sha256']['init_data_protection']
    if action in ('restore-original','authorize-bootstrap'):
        require(expected==record['bootstrap_wrapper_sha256'],'Current wrapper is not the installed bootstrap')
    device,before=stage.attach_backing(target,manifest)
    mount=target/('AuxiliaryWrapper-'+action)
    mounted=False
    try:
        system=checked_layout(auxiliary.owned_container(device),reserve,
                              action in ('restore-original','refresh-restore','refresh-timeouts','refresh-registration'))
        mount.mkdir(mode=0o700)
        stage.run(['/sbin/mount_apfs','-o','nobrowse,noowners',system,str(mount)])
        mounted=True
        require(stage.digest(stage.safe_path(mount,'usr/libexec/seputil'))==stage.STOCK_SHA and
                stage.digest(stage.safe_path(mount,'usr/libexec/huntmob-original/init_data_protection'))==stage.STOCK_SHA,
                'Stock utility/verifier changed')
        require(stage.digest(stage.safe_path(mount,'usr/libexec/huntmob-prepare-userdata'))==stage.digest(userdata) and
                stage.digest(stage.safe_path(mount,'usr/libexec/huntmob-restore-sep.img4'))==stage.SEP['restore'][1] and
                not stage.safe_path(mount,'usr/libexec/huntmob-prepare-data').exists(),'Preparation markers/helper changed')
        wrapper=stage.safe_path(mount,'usr/libexec/init_data_protection')
        require(not wrapper.is_symlink() and stage.digest(wrapper)==expected,'Current owned wrapper changed')
        if action=='bootstrap':
            original=target/'auxiliary-bootstrap-build/original-init_data_protection'
            stage.write_new(original,wrapper.read_bytes(),0o755)
            require(stage.digest(original)==expected,'Original wrapper backup mismatch')
            record['original_wrapper_sha256']=expected
        profile.verify_attachment(target/'namespace-1.raw',manifest['backings']['namespace-1.raw'],device,before)
        stage.replace_known(wrapper,binary.read_bytes(),expected)
        stage.run(['codesign','--verify','--strict',str(wrapper)])
        require(stage.digest(wrapper)==stage.digest(binary),'Wrapper readback mismatch')
        stage.replace_known(tc,custom,staging['trustcache_sha256'])
    finally:
        if mounted: stage.run(['/sbin/umount',str(mount)])
        profile.verify_attachment(target/'namespace-1.raw',manifest['backings']['namespace-1.raw'],device,before)
        stage.run(['/usr/bin/hdiutil','detach',device])
    new_hash=stage.digest(binary)
    if action=='bootstrap':record.update(state='installed',bootstrap_wrapper_sha256=new_hash)
    elif action=='authorize-bootstrap':
        record.update(state='installed',parent_xart_entitlement_authorized=True,
                      unauthorized_bootstrap_wrapper_sha256=record['bootstrap_wrapper_sha256'],
                      bootstrap_wrapper_sha256=new_hash,
                      bootstrap_entitlements={'com.apple.private.apfs.xart':True},
                      authorization_source_changed=False)
    elif action in ('refresh-restore','refresh-timeouts','refresh-registration'):
        refreshed={name:stage.digest(binary.parent/name) for name in
                   ('init_storage_virtual_v1.c','virtual_v1_scope.h')}
        staging['source_sha256'].update(refreshed)
        key={'refresh-restore':'restore_helper_refresh','refresh-timeouts':'restore_helper_diagnostics',
             'refresh-registration':'restore_helper_registration'}[action]
        manifest[key]={'original_wrapper_sha256':record['original_wrapper_sha256'],
                    'wrapper_sha256':new_hash,'source_sha256':refreshed,
                    'existing_gigalocker_resume_allowed':True,'extra_entitlements':False,'ready':False}
    else:record['state']='restored-original'
    manifest['auxiliary_bootstrap']=record
    staging['helper_sha256']['init_data_protection']=new_hash
    staging['trustcache_sha256']=stage.digest(tc)
    manifest['firmware']['files']['RestoreTrustCache'].update(sha256=stage.digest(tc),bytes=tc.stat().st_size)
    profile.write_manifest(target,manifest)
    return {'action':action,'wrapper_sha256':new_hash,'trustcache_sha256':stage.digest(tc),'ready':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-uuid',required=True)
    parser.add_argument('--action',choices=('bootstrap','authorize-bootstrap','restore-original','refresh-restore','refresh-timeouts','refresh-registration'),required=True)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--authorized-lab',action='store_true')
    args=parser.parse_args()
    if not args.apply:
        target,_=stage.validate(args.vm_uuid)
        print(json.dumps({'read_only':True,'target':str(target),'action':args.action,'ready':False}));return
    require(args.authorized_lab,'Explicit --authorized-lab required')
    print(json.dumps(install(args.vm_uuid,args.action),indent=2))


if __name__=='__main__':main()
