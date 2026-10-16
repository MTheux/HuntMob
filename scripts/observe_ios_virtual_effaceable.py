#!/usr/bin/env python3
"""Install a diagnostic or resume preparation after its verified cold checkpoint.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a read-only plan. No guest
start, Keychain access, effaceable formatting, ClassD initialization or Data
creation occurs in this installer. The resume helper requests fresh protected
Data preparation only on the subsequent explicitly authorized guest boot.
The stock verifier and wrapper remain unchanged.
"""
import argparse
import json
import plistlib
import shutil
from pathlib import Path

import stage_ios_virtual_profile as stage
from install_auxiliary_bootstrap_vm import cdhash

OLD_USERDATA = 'ec68178a1543881236c658233b375e0ee58525d0689e34573676c864e3f01801'
OLD_WRAPPER = '1f789b11afd2268ab32fea4f37018a821eba08510e19f45f9343117fa5f313f4'
OLD_TC = 'eaad1db9c2b9e9a71f2232b24ee8408c6a8813a6a4f5135d9e9350ea578ebe09'
OBSERVER_USERDATA = 'f9efbf6a4016590aed40a9956f6e23534fc741b12ee9f454386234fdfa17155d'
OBSERVER_TC = '79c5a270e5a90772bbfadf9e9694ab475c846ed5dd98048b5fe905f6a8171434'


def check_predecessor(manifest, resume=False):
    prior = manifest['virtual_staging']
    stage.require(prior['phase'] == 'data-checkpoint' and
                  prior['helper_sha256'] == {'init_data_protection': OLD_WRAPPER,
                                            'huntmob-prepare-userdata': OBSERVER_USERDATA if resume else OLD_USERDATA} and
                  prior['trustcache_sha256'] == (OBSERVER_TC if resume else OLD_TC) and
                  (manifest.get('effaceable_initialized_and_cold_verified') and
                   not manifest.get('data_after_effaceable_helper') if resume
                   else not manifest.get('effaceable_query_observer')),
                  'Only the exact preceding fresh Data helper may be replaced once')
    return prior


def install(vm_id, resume=False):
    target, manifest = stage.validate(vm_id)
    prior = check_predecessor(manifest, resume)
    expected_userdata = OBSERVER_USERDATA if resume else OLD_USERDATA
    expected_tc = OBSERVER_TC if resume else OLD_TC
    if resume:
        path = stage.PROJECT/'artifacts/validation/ios-effaceable-cold-persistence-v1-2026-10-15.json'
        proof = json.loads(path.read_text())
        stage.require(stage.digest(path) == manifest['effaceable_initialized_and_cold_verified']['receipt_sha256'] and
                      proof.get('effaceable_query') == {'status': 0, 'count': 1, 'formatted': True} and
                      proof.get('qmp_quit_accepted') is True and proof.get('panic_observed') is False and
                      proof.get('original_Data_Protection_verifier_passed') is True,
                      'Cold persistence and original verifier must be confirmed before Data preparation')
    stage.require(not any(target.glob('observation-*/qmp.sock')), 'A VM socket is present')
    old_build = target / 'virtual-helper-build-data-checkpoint'
    old_userdata_build = target/'virtual-helper-effaceable-query-v1' if resume else old_build
    for name, sha in prior['source_sha256'].items():
        location = old_userdata_build if name == 'prepare_userdata_virtual_v1.c' else old_build
        stage.require(stage.digest(location / name) == sha, 'Preceding helper source changed')
    for name, sha in prior['helper_sha256'].items():
        location = old_userdata_build if name == 'huntmob-prepare-userdata' else old_build
        stage.require(stage.digest(location / name) == sha, 'Preceding helper binary changed')
    scope = 'virtual_v1_scope.h'
    stage.require(stage.digest(stage.PROVISIONING / scope) == prior['source_sha256'][scope],
                  'Observer may not change the scope contract')
    tc = target / 'firmware/VirtualTrustCache'
    base = target / 'firmware/RestoreTrustCache'
    stage.require(not tc.is_symlink() and stage.digest(tc) == expected_tc and
                  stage.digest(base) == 'af33b3466bd828bf1ccaa1ab35d060bfcce62ade26ee74acf176501b00ea0d7f',
                  'Pinned trustcache changed')
    build = target / ('virtual-helper-data-after-effaceable-v1' if resume else 'virtual-helper-effaceable-query-v1')
    build.mkdir(mode=0o700)
    for name in ('prepare_userdata_virtual_v1.c', scope, 'userdata-entitlements.plist'):
        shutil.copyfile(stage.PROVISIONING / name, build / name)
    stage.require((build/'userdata-entitlements.plist').read_bytes() ==
                  (old_userdata_build/'userdata-entitlements.plist').read_bytes(), 'Entitlements changed')
    sdk = stage.run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.decode().strip()
    binary = build / 'huntmob-prepare-userdata'
    stage.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios14.0',
               '-isysroot', sdk, '-Wall', '-Wextra', '-Werror', '-O2',
               '-DHUNTMOB_VM_UUID="'+vm_id+'"', '-DHUNTMOB_EFFACEABLE_OBSERVE_ONLY='+('0' if resume else '1'),
               str(build/'prepare_userdata_virtual_v1.c'), '-o', str(binary)], timeout=60)
    stage.run(['codesign', '-s', '-', '--force', '--identifier',
               'com.huntmob.virtual-sep.prepare-userdata', '--entitlements',
               str(build/'userdata-entitlements.plist'), str(binary)])
    stage.run(['codesign', '--verify', '--strict', str(binary)])
    actual = stage.run(['codesign', '-d', '--entitlements', ':-', str(binary)])
    stage.require(plistlib.loads(actual.stdout) == plistlib.loads((build/'userdata-entitlements.plist').read_bytes()),
                  'Observer entitlements differ')
    custom = stage.merged_trustcache(base.read_bytes(),
                                   [cdhash(old_build/'init_data_protection'), cdhash(binary)], vm_id)
    stage.write_new(build/'previous-VirtualTrustCache', tc.read_bytes())
    stage.write_new(build/'previous-virtual-profile.json', (target/'virtual-profile.json').read_bytes())
    mount = target/('SystemStage-data-after-effaceable-v1' if resume else 'SystemStage-effaceable-query-v1')
    mount.mkdir(mode=0o700)
    device, before = stage.attach_backing(target, manifest)
    mounted = False
    try:
        # Reject an existing Data volume, including a failed partial creation.
        system = stage.owned_system(device)
        stage.run(['/sbin/mount_apfs', '-o', 'nobrowse,noowners', system, str(mount)])
        mounted = True
        for relative, sha in [('usr/libexec/seputil', stage.STOCK_SHA),
                              ('usr/libexec/huntmob-original/init_data_protection', stage.STOCK_SHA),
                              ('usr/libexec/init_data_protection', OLD_WRAPPER),
                              ('usr/libexec/huntmob-prepare-userdata', expected_userdata)]:
            path = stage.safe_path(mount, relative)
            stage.require(not path.is_symlink() and stage.digest(path) == sha, 'Guest predecessor changed')
        marker = stage.safe_path(mount, 'usr/libexec/huntmob-prepare-data')
        stage.require(not marker.is_symlink() and marker.read_bytes() == b'HUNTMOB VIRTUAL SEP V1 FRESH DATA\n' and
                      not stage.safe_path(mount, 'usr/libexec/huntmob-restore-sep.img4').exists(),
                      'Only normal Data preparation is accepted')
        guest = stage.safe_path(mount, 'usr/libexec/huntmob-prepare-userdata')
        stage.write_new(build/'previous-huntmob-prepare-userdata', guest.read_bytes(), 0o755)
        stage.profile.verify_attachment(target/'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        stage.replace_known(guest, binary.read_bytes(), expected_userdata)
        stage.run(['codesign', '--verify', '--strict', str(guest)])
        stage.require(stage.digest(guest) == stage.digest(binary), 'Observer readback differs')
        stage.replace_known(tc, custom, expected_tc)
    finally:
        if mounted:
            stage.run(['/sbin/umount', str(mount)])
        stage.profile.verify_attachment(target/'namespace-1.raw', manifest['backings']['namespace-1.raw'], device, before)
        stage.run(['/usr/bin/hdiutil', 'detach', device])
    record = {'source_sha256': stage.digest(build/'prepare_userdata_virtual_v1.c'),
              'helper_sha256': stage.digest(binary), 'trustcache_sha256': stage.digest(tc),
              'observe_only': not resume, 'format_attempted': False, 'ClassD_attempted': False,
              'fresh_protected_Data_preparation_requested': resume,
              'stock_verifier_unchanged': True, 'ready': False}
    prior['source_sha256']['prepare_userdata_virtual_v1.c'] = record['source_sha256']
    prior['helper_sha256']['huntmob-prepare-userdata'] = record['helper_sha256']
    prior['trustcache_sha256'] = record['trustcache_sha256']
    manifest['firmware']['files']['RestoreTrustCache'].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    manifest['data_after_effaceable_helper' if resume else 'effaceable_query_observer'] = record
    stage.profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-uuid', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--authorized-lab', action='store_true')
    parser.add_argument('--resume-after-effaceable', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        _, manifest = stage.validate(args.vm_uuid)
        check_predecessor(manifest, args.resume_after_effaceable)
        print(json.dumps({'read_only': True, 'ready': False})); return
    stage.require(args.authorized_lab, 'Explicit --authorized-lab required')
    print(json.dumps(install(args.vm_uuid, args.resume_after_effaceable), indent=2))


if __name__ == '__main__':
    main()
