#!/usr/bin/env python3
# AUTHORIZED TESTING ONLY — ISOLATED LAB.
# Target: new paused t8030 processes, public roots and disposable disks only.
"""Actual own DATA-v2 policy validation, without native/Apple cipher claims.

No user root, disk, firmware, profile or arbitrary engine inputs are accepted.
"""
import argparse
import hashlib
import json
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import boot_ios_virtual_profile as boot
import verify_virtual_sep_ans_mmio as m

ENGINE = 'ed75f41e695f118a1038967322413278701f8cafbfbac513daca2012f9980f64'
PATCH = 'ans-own-data-v2-profile.patch'
PROPERTY = 'huntmob-virtual-data-profile'
NATIVE, LEGACY = 0x1b040, 0x1b140


def oracle_envelope(flags, context=m.PUBLIC_CONTEXT, bank=0):
    scope = m.PUBLIC_VM_ID.bytes + bytes([bank]) + context
    cipher = m.cbc(m.kdf('HuntMob.VirtualSEP.v1/inline-wrap', scope), m.PUBLIC_DEK)
    mac = m.cbc(m.kdf('HuntMob.VirtualSEP.v1/inline-auth', scope),
                cipher+bytes(12)+struct.pack('<I', flags))[-16:]
    return struct.pack('<I', flags)+bytes(12)+mac+cipher


def envelope(devices, flags, bank=0, context=m.PUBLIC_CONTEXT):
    cipher = devices.aess(0x246 if bank else 0x206, m.PUBLIC_DEK)
    auth = devices.aess(0x48 if bank else 8, cipher)
    mac = devices.aess(0xc8 if bank else 0x88, auth[-16:]+bytes(12)+struct.pack('<I', flags))[-16:]
    blob = struct.pack('<I', flags)+bytes(12)+mac+cipher
    m.require(blob == oracle_envelope(flags, context, bank), 'Envelope differs from independent oracle')
    return blob


def xts(unit):
    ciphertext = bytearray()
    for index in range(2):
        cipher = Cipher(algorithms.AES(m.PUBLIC_DEK), modes.XTS((unit+index).to_bytes(16,'little'))).encryptor()
        ciphertext += cipher.update(m.io.PLAINTEXT[index*4096:(index+1)*4096])+cipher.finalize()
    m.require(ciphertext != m.io.PLAINTEXT, 'Oracle returned plaintext')
    return bytes(ciphertext)


def with_profile(argv, profile, identity=True):
    argv = list(argv)
    index = argv.index('-M')+1
    parts = argv[index].split(',')
    if not identity:
        parts = [p for p in parts if not p.startswith(('huntmob-virtual-sep-root-secret=', 'huntmob-virtual-sep-vm-id='))]
    if profile is not None:
        parts.append(PROPERTY+'='+profile)
    argv[index] = ','.join(parts)
    return argv


def flush(devices):
    command = bytearray(m.io.io_command(0, devices.cid))
    struct.pack_into('<I', command, 4, 0xffffffff)
    devices.submit('flush-all', bytes(command))


def immutable(machine):
    machine.qf.write((json.dumps({'execute':'qom-set', 'arguments':
                      {'path':'/machine','property':PROPERTY,'value':'v1'}, 'id':'immutable-public-test'})+'\n').encode())
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        response = json.loads(machine.qf.readline())
        if response.get('id') != 'immutable-public-test':
            continue
        m.require(response.get('error',{}).get('desc') == 'Own DATA profile is immutable after initialization',
                  'QOM setter was not rejected by the expected immutability contract')
        m.require(machine.command('qom-get', {'path':'/machine','property':PROPERTY}) == 'v2',
                  'Rejected setter changed the profile')
        return
    raise RuntimeError('Immutable-property response deadline')


def startup_rejection(engine, folder, profile, identity):
    folder.mkdir()
    argv, _ = m.prepare(engine, folder)
    argv = with_profile(argv, profile, identity)
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=10)
    expected = (b'Only own DATA profiles v1 and v2 are supported' if profile=='v3' else
                b'Own DATA-v2 requires a complete virtual SEP identity')
    m.require(result.returncode != 0 and expected in result.stderr,
              'Invalid configuration did not fail with the exact startup guard')
    return {'profile':profile,'identity_supplied':identity,'rejected_before_guest_execution':True}


def exercise(engine, folder, profile):
    folder.mkdir()
    argv, original = m.prepare(engine, folder)
    argv = with_profile(argv, profile)
    machine = m.PausedMachine(argv, folder)
    expected = bytearray(m.DISK_BYTES)
    checks=[]
    try:
        expected_profile = 'v1' if profile is None else profile
        m.require(machine.command('qom-get',{'path':'/machine','property':PROPERTY}) == expected_profile,
                  'QOM getter disagrees with selected profile')
        if profile == 'v2':
            immutable(machine)
        devices=m.Devices(machine)
        devices.aess(0x200)
        devices.initialize_nvme()
        devices.program()
        native,legacy=(envelope(devices,f) for f in (NATIVE,LEGACY))
        flush(devices)
        baseline={key:boot.digest(folder/key) for key in original}
        startup=sorted(key for key in original if original[key]!=baseline[key])
        m.require(startup==['namespace-5.raw'],'Unexpected startup backing mutation')
        left,right=bytes([0xa7])*64,bytes([0xbc])*4096
        machine.write(m.DATA-64,left);machine.write(m.DATA+8192,right)
        sentinel=bytes([0x9d])*8192

        def invariant():
            m.require((folder/'namespace-1.raw').read_bytes()==expected,'Whole public backing differs')
            m.require(all(boot.digest(folder/key)==value for key,value in baseline.items()
                          if key!='namespace-1.raw'),'Unrelated backing changed')
            m.require(machine.read(m.DATA-64,len(left))==left and
                      machine.read(m.DATA+8192,len(right))==right,'DMA sentinel changed')

        def submit(name, opcode, blob=None, status=0, before=sentinel, after=sentinel, lba=7, unit=m.io.FILE_UNIT):
            command=m.io.io_command(opcode,devices.cid,flags=4 if blob else 0,
                                    extension=blob,lba=lba,unit=unit)
            devices.submit(name,command,status=status,before=before,after=after)
            checks.append({'name':name,'opcode':opcode,'status':status})

        def reject_pair(name,blob):
            for opcode in (1,2):
                submit(name,opcode,blob,status=0x4002)
                invariant()

        if profile is None:
            reject_pair('default-v1-native-format-closed',native)
            flush(devices);invariant()
        else:
            for label,blob,lba,unit in [('native',native,7,m.io.FILE_UNIT),
                                       ('legacy',legacy,19,m.io.FILE_UNIT+0x100)]:
                cipher=xts(unit)
                submit(label+'-write',1,blob,before=m.io.PLAINTEXT,after=m.io.PLAINTEXT,lba=lba,unit=unit)
                expected[lba*4096:(lba+2)*4096]=cipher
                invariant()
                submit(label+'-read',2,blob,after=m.io.PLAINTEXT,lba=lba,unit=unit)
                submit(label+'-ciphertext-read',2,None,after=cipher,lba=lba,unit=unit)
                invariant()
            for label,blob in [('native',native),('legacy',legacy)]:
                changed=bytearray(blob);changed[1]^=1
                reject_pair(label+'-cross-flip-without-remac',bytes(changed))
                reserved=bytearray(blob);reserved[4]^=1
                reject_pair(label+'-reserved-tamper',bytes(reserved))
            for flags in (NATIVE^1,LEGACY^1):
                reject_pair('unsupported-format-valid-MAC-'+hex(flags),envelope(devices,flags))
            # AESS can produce candidate bank1 envelopes before KEY publication.
            # They cannot be consumed by the currently published bank0 context.
            other_context=bytes([0x74])*28
            devices.program(other_context,bank=1,latch=False)
            for flags in (NATIVE,LEGACY):
                reject_pair('unpublished-wrong-bank-'+hex(flags),
                            envelope(devices,flags,bank=1,context=other_context))
            devices.key(4)
            reject_pair('revoked-native-context',native)
            reject_pair('revoked-legacy-context',legacy)
            submit('clear-read-after-revocation',2,None,after=xts(m.io.FILE_UNIT))
            invariant()
            # Reinitialize the already-supported own provider, not a fallback.
            devices.program()
            submit('new-lease-native-read',2,native,after=m.io.PLAINTEXT)
            invariant()
            # Actual controller reset revokes the lease before drain and clears
            # queues. New protected requests cannot return stale plaintext.
            machine.w32(m.ANS+0x14,0)
            m.require(machine.r32(m.ANS+0x1c)&3==0,'Controller reset did not clear RDY')
            devices=m.Devices(machine)
            devices.initialize_nvme()
            reject_pair('controller-reset-native-context',native)
            reject_pair('controller-reset-legacy-context',legacy)
            submit('clear-read-after-controller-reset',2,None,after=xts(m.io.FILE_UNIT))
            flush(devices);invariant()
        m.require(machine.command('query-status')['running'] is False,'CPUs unexpectedly executed')
    finally:
        machine.close()
    m.require((folder/'namespace-1.raw').read_bytes()==expected and
              all(boot.digest(folder/key)==value for key,value in baseline.items()
                  if key!='namespace-1.raw'),'Backing differs after flush and shutdown')
    return {'profile':expected_profile,'checks':checks,'startup_changes':startup,
            'backing_sha256':hashlib.sha256(expected).hexdigest(),
            'whole_16MiB_matches_oracle':True,'other_eight_backings_unchanged':True,
            'DMA_guards_unchanged':True,'getter_correct':True,'post_init_setter_rejected':profile=='v2'}


def run():
    engine=boot.CANDIDATE/'build/qemu-system-aarch64'
    receipt_path=boot.CANDIDATE/'build-receipt.json'
    receipt=json.loads(receipt_path.read_text())
    sources=boot.reviewed_sources(boot.CANDIDATE/'source',boot.PATCHES)
    m.require(receipt.get('state')=='compiled' and receipt['binary_sha256']==ENGINE and
              boot.digest(engine)==ENGINE and PATCH in receipt['patch_sha256'] and
              receipt['reviewed_source_sha256']==sources,'Only the exact reviewed DATA-v2 candidate may run')
    with tempfile.TemporaryDirectory(prefix='hm-own-data-v2-',dir='/tmp') as directory:
        root=Path(directory)
        default=exercise(engine,root/'v1-default',None)
        v2=exercise(engine,root/'v2','v2')
        startup=[startup_rejection(engine,root/'unknown-v3','v3',True),
                 startup_rejection(engine,root/'v2-no-identity','v2',False)]
    m.require(boot.digest(engine)==ENGINE and boot.reviewed_sources(boot.CANDIDATE/'source',boot.PATCHES)==sources,
              'Candidate changed during validation')
    return {'schema':'huntmob.own-DATA-v2.controller.v1','engine_sha256':ENGINE,
            'build_receipt_sha256':boot.digest(receipt_path),'patch_sha256':receipt['patch_sha256'][PATCH],
            'harness_sha256':boot.digest(Path(__file__)),'default_v1':default,'own_v2':v2,
            'startup_guards':startup,'own_cipher_contract':'AES128-XTS,32-byte pair,4096-byte units',
            'file_units_differ_from_LBA':True,'both_formats_roundtrip_and_oracle_passed':True,
            'cross_flip_unknown_reserved_wrong_bank_rejected':True,
            'revocation_and_controller_reset_no_plaintext_fallback':True,
            'public_fixture_only':True,'cpus_paused':True,'firmware_executed':False,
            'private_profile_accessed':False,'Keychain_accessed':False,
            'Apple_hardware_equivalence':False,'native_Data_Protection_validated':False,'ready':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab',action='store_true',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    m.require(not args.output.exists(),'Never overwrite an existing receipt')
    result=run()
    with args.output.open('x') as output:
        json.dump(result,output,indent=2);output.write('\n')
    print(json.dumps({'engine_sha256':ENGINE,'default_v1_checks':len(result['default_v1']['checks']),
                      'v2_checks':len(result['own_v2']['checks']),'startup_guard_cases':2,'ready':False}))


if __name__=='__main__':main()
