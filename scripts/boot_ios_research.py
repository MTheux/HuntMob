#!/usr/bin/env python3
"""Prepare and measure a bounded, isolated iPhone 11 recovery boot.

AUTHORIZED TESTING ONLY — ISOLATED LAB. No physical device access, no firmware
redistribution, no public sockets. Recovery userspace is not SpringBoard.
"""
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path, PurePosixPath

RESEARCH = Path.home() / '.huntmob/research'
BUILD = '18A5351d'
IPSW_SHA = '706742ed60327a5247c29ccc5bf7e6ce9bbf11dd30a468f8f6fc9da76bdca96d'
ENGINE_SHA = '32f061571b004b79e7111f520583bd231f9f4f7d3a9b3be22586d4e3ae492902'
SEP_ENGINE_SHA = 'dd379dbe74a05fd1a333ad70953bba919b2477fff3b1facd143b29702dcc0a25'
SEP_INPUTS = {
    'AppleSEPROM-Cebu-B1': 'e3b11f624e3382a203c1f781b889b407554668936c86b0e2d41d229976317a1b',
    'sep-firmware.n104.RELEASE.new.img4': '500610b4521aa7981ea939303df14783831bda573a83947c45dbb54f73202616',
}
SOURCE = ('https://updates.cdn-apple.com/2020SummerSeed/fullrestores/001-35886/'
          '5FE9BE2E-17F8-41C8-96BB-B76E2B225888/'
          'iPhone11,8,iPhone12,1_14.0_18A5351d_Restore.ipsw')


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def prepare(archive, target):
    """Extract only the selected manifest components, preserving originals."""
    with zipfile.ZipFile(archive) as source:
        manifest = plistlib.loads(source.read('BuildManifest.plist'))
        if manifest.get('ProductBuildVersion') != BUILD or 'iPhone12,1' not in manifest.get('SupportedProductTypes', []):
            raise ValueError('Only the pinned iPhone 11 build 18A5351d is accepted.')
        identities = [i for i in manifest['BuildIdentities']
                      if i['Info'].get('DeviceClass') == 'n104ap'
                      and i['Info'].get('Variant') == 'Research Developer Erase Install (IPSW)']
        if len(identities) != 1:
            raise ValueError('Ambiguous or missing research erase identity.')
        selected = identities[0]['Manifest']
        paths = {key: selected[key]['Info']['Path'] for key in
                 ['KernelCache', 'DeviceTree', 'RestoreRamDisk', 'RestoreTrustCache']}
        # Flatten into a new, exclusive directory: no archive pathname is used
        # for a destination and no caller-owned existing files are overwritten.
        for name in paths.values():
            entry = source.getinfo(name)
            parts = PurePosixPath(name)
            if parts.is_absolute() or '..' in parts.parts or entry.file_size > 1024**3:
                raise ValueError('Unsafe firmware component.')
        target.mkdir(mode=0o700, parents=True, exist_ok=False)
        files = {}
        for key, name in paths.items():
            destination = target / key
            with source.open(name) as content, destination.open('xb') as output:
                shutil.copyfileobj(content, output)
            files[key] = {'path': str(destination), 'archive_path': name,
                          'sha256': digest(destination), 'bytes': destination.stat().st_size}
        return {'schema': 1, 'model': 't8030', 'product': 'iPhone12,1',
                'version': manifest['ProductVersion'], 'build': BUILD,
                'source_url': SOURCE, 'ipsw_sha256': digest(archive),
                'files': files, 'firmware_modified': False}


def command(engine, target, files, restore=False, sep=False, companion_profile="arm64", tcg_thread="multi", create_disks=True):
    if tcg_thread not in {"single", "multi"}:
        raise ValueError("Unsupported TCG thread mode.")
    if companion_profile not in {"arm64", "x86_64"}:
        raise ValueError("Unsupported owned companion profile.")
    companion = RESEARCH / ('ios-companion-x86_64' if companion_profile == 'x86_64' else 'ios-companion')
    usb = companion/'usb.sock' if restore else target/'usb.sock'
    machine = f"t8030,trustcache={files['RestoreTrustCache']['path']},usb-conn-type=unix,usb-conn-addr={usb}"
    if restore or sep:
        machine += f",ticket={companion/'root_ticket.der'}"
    if sep:
        # Upstream documented debug recipe; affects only the isolated guest.
        machine += f",kaslr-off=true,sep-rom={RESEARCH/'firmware/AppleSEPROM-Cebu-B1'},sep-fw={RESEARCH/'firmware/sep-firmware.n104.RELEASE.new.img4'}"
    args = [str(engine), '-M', machine,
            '-kernel', files['KernelCache']['path'], '-dtb', files['DeviceTree']['path'],
            '-initrd', files['RestoreRamDisk']['path'], '-accel', 'tcg,thread='+tcg_thread,
            '-smp', '7' if sep else '1', '-m', '4G', '-display', 'none', '-monitor', 'none',
            '-qmp', f'unix:{target}/qmp.sock,server=on,wait=off',
            '-serial', 'stdio', '-nic', 'none', '-audiodev', 'none,id=lab-audio',
            '-append', 'tlto_us=-1 mtxspin=-1 agm-genuine=1 agm-authentic=1 agm-trusted=1 serial=3 -v wdt=-1 -vm_compressor_wk_sw']
    if not restore:
        args.append('-snapshot')
    if sep:
        for name, size in [('sep-nvram',64*1024),('sep-ssc',128*1024)]:
            disk = target/(name+'.raw')
            if create_disks:
                with disk.open('xb') as output:
                    output.truncate(size)
            elif disk.is_symlink() or not disk.is_file() or disk.stat().st_size != size:
                raise ValueError('Invalid owned SEP disk.')
            args += ['-drive',f'file={disk},if=pflash,format=raw']
    sizes = [32*1024**3, 8*1024**2, 128*1024, 8*1024, 8*1024, 4*1024, 1024**2]
    for nsid, size in enumerate(sizes, 1):
        disk = target / f'namespace-{nsid}.raw'
        if create_disks:
            with disk.open('xb') as output:
                output.truncate(size)
        elif disk.is_symlink() or not disk.is_file() or disk.stat().st_size != size:
            raise ValueError('Invalid owned namespace disk.')
        args += ['-drive', f'file={disk},format=raw,if=none,id=disk{nsid}',
                 '-device', f"{'apple-nvram,id=nvram' if nsid == 5 else 'nvme-ns'},drive=disk{nsid},bus=nvme-bus.0,nsid={nsid},nstype={8 if nsid == 7 else nsid},logical_block_size=4096,physical_block_size=4096"]
    return args


def check_companion_ready(companion):
    ready=companion/'ready.json'
    if ready.is_symlink() or not ready.is_file():
        raise ValueError('Prepare and verify companion tools before recovery boot (120-second guest timeout).')
    receipt=json.loads(ready.read_text())
    if receipt.get('tools_build_complete') is not True or receipt.get('ipsw_sha256') != IPSW_SHA:
        raise ValueError('Owned companion preparation is incomplete.')


def restore_observations(log):
    """Track guest ASR progress separately from host transfer and UI readiness."""
    values=[int(value) for value in re.findall(r'ASR RESTORE PROGRESS:\s*(\d+)%',log)]
    return {'guest_asr_progress_percent': max(values) if values else None,
            'restore_stage1_exit_observed': 'Detected potentially-completed restore process.' in log,
            'full_restore_validated': False, 'springboard_validated': False,
            'ipa_execution_validated': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', action='store_true', required=True)
    parser.add_argument('--ipsw', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=90, choices=range(10, 1801), metavar='10..1800')
    parser.add_argument('--tcg-thread', choices=['single','multi'], default='multi')
    parser.add_argument('--companion-profile', choices=['arm64', 'x86_64'], default='arm64')
    parser.add_argument('--restore-session', action='store_true', help='Use only the owned local companion and new writable lab disks.')
    parser.add_argument('--sep-emulated', action='store_true', help='Use the separately prepared pinned SEP ROM/firmware and initial engine build.')
    args = parser.parse_args()
    engine = RESEARCH / ('Inferno/build-huntmob/qemu-system-aarch64-sep' if args.sep_emulated else 'Inferno/build-huntmob/qemu-system-aarch64')
    expected_engine = SEP_ENGINE_SHA if args.sep_emulated else ENGINE_SHA
    if engine.is_symlink() or digest(engine) != expected_engine:
        raise SystemExit('Engine does not match the validated build receipt.')
    if digest(args.ipsw) != IPSW_SHA:
        raise SystemExit('Firmware does not match the official-download receipt.')
    if args.restore_session:
        companion = RESEARCH / ('ios-companion-x86_64' if args.companion_profile == 'x86_64' else 'ios-companion')
        if args.companion_profile == 'x86_64':
            check_companion_ready(companion)
        if not (companion/'usb.sock').is_socket() or not (companion/'root_ticket.der').is_file():
            raise SystemExit('Owned companion or lab ticket is unavailable.')
    if args.sep_emulated:
        for name, expected in SEP_INPUTS.items():
            path = RESEARCH/'firmware'/name
            if path.is_symlink() or digest(path) != expected:
                raise SystemExit('SEP input does not match its preparation receipt.')
    root = RESEARCH / 'ios-vms'
    root.mkdir(mode=0o700, exist_ok=True)
    if root.is_symlink():
        raise SystemExit('Research VM folder cannot be a symlink.')
    target = root / ('boot-' + time.strftime('%Y%m%d-%H%M%S'))
    receipt = prepare(args.ipsw.resolve(strict=True), target)
    receipt.update(engine_sha256=expected_engine, engine_revision='cc4302a99167abec69b714cfd00c38caece7e7de',
                   springboard_validated=False, ipa_execution_validated=False,
                   guest_network_enabled=False, display_validated=False,
                   sep_profile='rom-firmware-emulated' if args.sep_emulated else 'upstream-simulated-no-data-encryption',
                   data_protection_validation_supported=False,
                   kernel_modified_in_guest_memory_by_upstream=True,
                   restore_session=args.restore_session, companion_profile=args.companion_profile, tcg_thread=args.tcg_thread)
    launch = command(engine, target, receipt['files'], args.restore_session, args.sep_emulated, args.companion_profile, args.tcg_thread)
    receipt['command'] = launch
    (target/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    started = time.monotonic()
    with (target/'boot.log').open('wb') as output:
        process = subprocess.Popen(launch, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   cwd=target, start_new_session=True)
        try:
            process.wait(timeout=args.seconds)
            receipt['stop_reason'] = 'engine-exited'
        except subprocess.TimeoutExpired:
            receipt['stop_reason'] = 'bounded-observation-ended'
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
    log = (target/'boot.log').read_text(errors='replace')
    receipt.update(elapsed_seconds=round(time.monotonic()-started, 2), exit_code=process.returncode,
                   boot_log_sha256=digest(target/'boot.log'),
                   darwin_banner_observed='Darwin Kernel Version' in log,
                   recovery_agent_observed='waiting for host to trigger start of restore' in log,
                   ramdisk_root_observed='BSD root: md0' in log,
                   panic_observed='panic(cpu' in log,
                   launchd_observed='Darwin Bootstrapper' in log,
                   recovery_userspace_observed='Darwin Bootstrapper' in log and 'BSD root: md0' in log,
                   restore_stage1_exit_observed='Detected potentially-completed restore process.' in log,
                   full_restore_validated=False)
    receipt.update(restore_observations(log))
    receipt['validation_status'] = ('failed-panic' if receipt['panic_observed'] else
        'restore-stage1-observed' if receipt['restore_stage1_exit_observed'] else
        'recovery-only' if receipt['recovery_userspace_observed'] else 'boot-not-validated')
    # Markers are observations, not a declaration of a usable app runtime.
    (target/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({'receipt': str(target/'receipt.json'),
                      'darwin_banner_observed': receipt['darwin_banner_observed'],
                      'launchd_observed': receipt['launchd_observed'],
                      'recovery_userspace_observed': receipt['recovery_userspace_observed'],
                      'restore_stage1_exit_observed': receipt['restore_stage1_exit_observed'],
                      'springboard_validated': False, 'exit_code': process.returncode,
                      'validation_status': receipt['validation_status']}))
    if receipt['panic_observed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
