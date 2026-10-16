#!/usr/bin/env python3
"""Bounded disk boot of an owned experimental iOS clone, never a physical device."""
import argparse
import json
import plistlib
import socket
import subprocess
import time
import re
from pathlib import Path
from boot_ios_research import RESEARCH, SEP_ENGINE_SHA, SEP_INPUTS, IPSW_SHA, digest, command

NORMAL_SEP_SHA = 'c386e1c55009a583963c5357a9d1ba4ddf760bd741182d8a928fdae2bf6479d3'
SEP_PROFILES = {
    'serving': ('sep-firmware.n104.serving.img4', NORMAL_SEP_SHA),
    'encrypted-lab': ('sep-firmware.n104.encrypted-lab.img4', '172f794c8ae94df08d8e74f7a620569576c7dad3a610d3975d420c7826cfbb63'),
    'restore-preload': ('sep-firmware.n104.RELEASE.new.img4', '500610b4521aa7981ea939303df14783831bda573a83947c45dbb54f73202616'),
}
SEP_OBSERVATION_SITES = {'panic': 0x2400067b4, 'keybag-selection': 0x24000644c,
                         'img4-evaluation': 0x2400086e4,
                         'nonce-comparison': 0x24000b2f4,
                         'restore-nonce-comparison': 0x24000b2a0,
                         'context-validation': 0x24000b1e8,
                         'context-result': 0x2400066ac,
                         'normal-nonce-availability': 0x24000b2e4}


def normal_sep_machine(machine, profile='serving'):
    """Use serving SEP for disk boot: the engine overrides guest firmware loads."""
    filename, expected = SEP_PROFILES[profile]
    normal = RESEARCH / 'firmware' / filename
    if normal.is_symlink() or digest(normal) != expected:
        raise SystemExit('Pinned serving SEP firmware unavailable.')
    restore = f"sep-fw={RESEARCH/'firmware/sep-firmware.n104.RELEASE.new.img4'}"
    if machine.count(restore) != 1:
        raise SystemExit('Unexpected SEP firmware launch configuration.')
    return machine.replace(restore, f'sep-fw={normal}')


def validate_provisioning_clone(target, receipt, profile):
    parent=RESEARCH/'ios-vms/native-20261013-215607'
    if profile!='restore-preload' or not target.name.endswith('-restore-preload') or receipt.get('parent_clone')!=str(parent):
        raise SystemExit('Persistent provisioning requires the exclusive restore-preload clone.')
    for name in [f'namespace-{n}.raw' for n in range(1,8)]+['sep-nvram.raw','sep-ssc.raw']:
        current=target/name
        if current.is_symlink() or current.stat().st_nlink!=1 or current.samefile(parent/name):
            raise SystemExit('Persistent provisioning cannot share a backing file with the source clone.')


def validate_data_clone(target, receipt, profile):
    parent=RESEARCH/'ios-vms/native-20261014-erase-data-preparation'
    if profile!='serving' or not target.name.endswith('-data-checkpoint') or receipt.get('parent_clone')!=str(parent):
        raise SystemExit('Persistent Data preparation requires an exclusive checkpoint clone.')
    for name in [f'namespace-{n}.raw' for n in range(1,8)]+['sep-nvram.raw','sep-ssc.raw']:
        current=target/name
        if current.is_symlink() or current.stat().st_nlink!=1 or current.samefile(parent/name):
            raise SystemExit('Persistent Data preparation cannot share backing files.')


def decode_rsp(payload):
    """Decode GDB's escaped and run-length encoded response payload."""
    decoded=bytearray();index=0
    while index<len(payload):
        value=payload[index];index+=1
        if value in (ord('}'),ord('*')):
            if index>=len(payload):raise ValueError('Truncated debugger encoding.')
            following=payload[index];index+=1
            if value==ord('}'):
                decoded.append(following^0x20)
            else:
                count=following-29
                if not decoded or count<0 or len(decoded)+count>16384:
                    raise ValueError('Invalid debugger run length.')
                decoded.extend([decoded[-1]]*count)
        else:decoded.append(value)
    return decoded.decode('ascii')


def boot_observations(content, timed_out=False):
    """Separate observed startup stages from a usable, independently tested OS."""
    panic='panic(cpu' in content
    sep_alive='SEP/OS is alive' in content
    protection_failed='boot task failure: data-protection' in content or 'Boot task failed: data-protection' in content
    return {'panic_observed':panic,'sep_os_alive_observed':sep_alive,
            'stock_data_protection_verifier_invoked':'HuntMob: invoking stock Data Protection verifier' in content,
            'normal_nonce_init_completed_observed':'HuntMob: stock normal SEP nonce initialization' in content
                and 'HuntMob: releasing restore Gigalocker' in content,
            'data_protection_failure_observed':protection_failed,
            'observation_time_limit_reached':timed_out,
            'validation_status':('failed-data-protection' if protection_failed else 'failed-panic' if panic
                                 else 'observation-time-limit' if timed_out else 'incomplete'),
            'full_restore_validated':False,'springboard_validated':False,'ipa_execution_validated':False}


def quit_owned_vm(qmp_socket):
    """Ask the already-owned VM to flush/close its complete drive cohort."""
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3);client.connect(str(qmp_socket))
            deadline=time.monotonic()+3
            stream=client.makefile('rwb')
            def receive():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('QMP shutdown deadline reached.')
                client.settimeout(remaining)
                raw=stream.readline(65537)
                if not raw or len(raw)>65536:raise ValueError('Invalid QMP response.')
                return json.loads(raw)
            if 'QMP' not in receive():return False
            for name in ('qmp_capabilities','quit'):
                stream.write((json.dumps({'execute':name})+'\n').encode());stream.flush()
                while True:
                    response=receive()
                    if 'error' in response:return False
                    if 'return' in response:break
            return True
    except (OSError,ValueError):return False


def observe_sep_state(debug_socket, timeout=30, profile='serving', stage='panic'):
    """Read only ROM boot flags at the known panic site in the pinned lab ROM.

    Breakpoints do not patch ROM or suppress its verification. No key, entropy,
    mailbox payload or user-data memory is read.
    """
    with socket.socket(socket.AF_UNIX) as client:
        observation_deadline=time.monotonic()+timeout
        client.settimeout(min(timeout,10))
        deadline=time.monotonic()+10
        while True:
            try:
                client.connect(str(debug_socket));break
            except (FileNotFoundError,ConnectionRefusedError):
                if time.monotonic()>deadline:raise
                time.sleep(.1)
        def request(value):
            remaining=observation_deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('SEP observation deadline reached.')
            client.settimeout(remaining)
            payload=value.encode('ascii')
            client.sendall(b'$'+payload+b'#'+f'{sum(payload)%256:02x}'.encode())
            while True:
                marker=client.recv(1)
                if not marker:raise ConnectionError('Debugger disconnected.')
                if marker==b'$':break
            result=bytearray()
            while True:
                value=client.recv(1)
                if not value:raise ConnectionError('Debugger disconnected.')
                if value==b'#':break
                result+=value
                if len(result)>65536:raise ValueError('Debugger response exceeds observation limit.')
            checksum=client.recv(2)
            if checksum!=f'{sum(result)%256:02x}'.encode():
                raise ValueError('Debugger response checksum differs.')
            client.sendall(b'+')
            return decode_rsp(result)
        # SEP is a separate CPU cluster; single-process GDB sees only AP cores.
        request('qSupported:multiprocess+')
        # AP performance/efficiency cores and SEP form three CPU clusters.
        request('vAttach;2')
        request('vAttach;3')
        site=SEP_OBSERVATION_SITES[stage]
        if request(f'Z1,{site:x},4')!='OK':
            raise ValueError('SEP observation breakpoint unavailable.')
        stop=request('vCont;c')
        thread=re.search(r'thread:((?:p[a-fA-F0-9]+\.)?[a-fA-F0-9]+);',stop)
        if not thread:raise ValueError('SEP observation did not return a stopped thread.')
        if request('Hg'+thread.group(1))!='OK':raise ValueError('Cannot select SEP observer thread.')
        encoded=request('m242214720,b')
        if not re.fullmatch(r'[a-fA-F0-9]{22}',encoded):
            candidates=request('qfThreadInfo')
            if candidates.startswith('m'):
                for candidate in candidates[1:].split(','):
                    if not re.fullmatch(r'(?:p[a-fA-F0-9]+\.)?[a-fA-F0-9]+',candidate):continue
                    if request('Hg'+candidate)!='OK':continue
                    alternative=request('m242214720,b')
                    if re.fullmatch(r'[a-fA-F0-9]{22}',alternative):
                        encoded=alternative;break
        if not re.fullmatch(r'[a-fA-F0-9]{22}',encoded):
            status=encoded if re.fullmatch(r'E[0-9a-fA-F]{2}',encoded) else f'length {len(encoded)}'
            raise ValueError(f'SEP boot flags unavailable ({status}; thread {thread.group(1)}).')
        flags=bytes.fromhex(encoded)
        result={'observation_stage':stage,'rom_observation_site_reached':True,
                'memory_encryption_disabled':bool(flags[0]),
                'production_mode':bool(flags[1]),
                'secure_mode':bool(flags[2]),
                'boot_flags_initialized':bool(flags[9]&1),
                'rom_debug_request_enabled':bool(flags[10]),
                'additional_rom_checks_disabled':False}
        stack=request('p1f')
        pc=request('p20')
        if re.fullmatch(r'[a-fA-F0-9]{16}',pc):
            result['observation_pc_matches']=int.from_bytes(bytes.fromhex(pc),'little')==site
        policy=request('p17')
        if re.fullmatch(r'[a-fA-F0-9]{16}',policy):
            result['plaintext_policy_rejected']=bool(int.from_bytes(bytes.fromhex(policy),'little'))
        if stage=='keybag-selection':
            branch=request('p8')
            if re.fullmatch(r'[a-fA-F0-9]{16}',branch):
                result['keybag_branch_flag']=int.from_bytes(bytes.fromhex(branch),'little')&0xff
        if stage=='normal-nonce-availability':
            available=request('p8')
            if re.fullmatch(r'[a-fA-F0-9]{16}',available):
                result['normal_nonce_available']=bool(int.from_bytes(bytes.fromhex(available),'little')&0xff)
        if stage=='img4-evaluation':
            status=request('p0')
            if re.fullmatch(r'[a-fA-F0-9]{16}',status):
                result['img4_evaluation_return_code']=int.from_bytes(bytes.fromhex(status),'little')&0xffffffff
        if stage in ('nonce-comparison','restore-nonce-comparison','context-result'):
            comparison=request('p0')
            if re.fullmatch(r'[a-fA-F0-9]{16}',comparison):
                status=int.from_bytes(bytes.fromhex(comparison),'little')&0xffffffff
                if stage=='context-result':result['firmware_context_accepted']=bool(status)
                else:result['firmware_nonce_matches_virtual_sep']=status==0
        if stage=='context-validation':
            pointer=request('p0')
            if re.fullmatch(r'[a-fA-F0-9]{16}',pointer):
                address=int.from_bytes(bytes.fromhex(pointer),'little')
                if not 0x242200000<=address<0x242223000:
                    raise ValueError('SEP context pointer outside pinned scratch RAM.')
                for name,offset,length in [('context_mode',0,4),('nonce_property_present',0x38,1),
                                           ('production_property_present',0xb2,1),('production_property_value',0xb3,1),
                                           ('security_property_present',0xb4,1),('security_property_value',0xb5,1),
                                           ('nonce_optional_flag',0xba,1),('security_mode_selector',0xbb,1)]:
                    value=request(f'm{address+offset:x},{length:x}')
                    if re.fullmatch(r'[a-fA-F0-9]{'+str(length*2)+'}',value):
                        result[name]=int.from_bytes(bytes.fromhex(value),'little')
        if stage in ('panic','keybag-selection') and re.fullmatch(r'[a-fA-F0-9]{16}',stack):
            address=int.from_bytes(bytes.fromhex(stack),'little')
            for name,offset in [('img4_verified_flag',0xf8),('keybag_decoded_flag',0x120)]:
                value=request(f'm{address+offset:x},1')
                if re.fullmatch(r'[a-fA-F0-9]{2}',value):result[name]=bool(int(value,16))
        # Compare only the firmware container header, never log its bytes.
        physical=request('Qqemu.PhyMemMode:1')=='OK'
        header=request('m4000,40') if physical else ''
        if re.fullmatch(r'[a-fA-F0-9]{128}',header):
            actual=bytes.fromhex(header)
            expected=(RESEARCH/'firmware'/SEP_PROFILES[profile][0]).read_bytes()[:64]
            result['serving_firmware_header_matches']=actual==expected
            result['img4_container_header_present']=b'IMG4' in actual[:16]
        else:result['firmware_header_observation_available']=False
        instructions=request(f'm{site:x},8') if physical else ''
        if re.fullmatch(r'[a-fA-F0-9]{16}',instructions):
            original=(RESEARCH/'firmware/AppleSEPROM-Cebu-B1').read_bytes()
            offset=site-0x240000000
            result['site_instructions_match_original_rom']=bytes.fromhex(instructions)==original[offset:offset+8]
        if physical:request('Qqemu.PhyMemMode:0')
        request(f'z1,{site:x},4')
        # Detach every attached cluster so observation cannot hold the AP/SEP.
        for pid in ('3','2','1'):
            request('D;'+pid)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab',action='store_true',required=True)
    parser.add_argument('--vm',type=Path,required=True)
    parser.add_argument('--seconds',type=int,choices=range(10,601),default=120,metavar='10..600')
    parser.add_argument('--diagnose-sep-state',action='store_true',help='Observe boot flags through a private Unix debugger; never bypass ROM verification.')
    parser.add_argument('--sep-firmware-profile',choices=SEP_PROFILES,default='serving')
    parser.add_argument('--sep-observation-stage',choices=SEP_OBSERVATION_SITES,default='panic')
    parser.add_argument('--persist-provisioning',action='store_true',help='Persist stock SEP provisioning only in an exclusive restore-preload clone.')
    parser.add_argument('--persist-data-preparation',action='store_true',help='Persist protected Data only in an exclusive owned checkpoint clone.')
    args=parser.parse_args()
    target=args.vm.resolve(strict=True)
    if args.vm.is_symlink() or target.parent != (RESEARCH/'ios-vms').resolve() or not target.name.startswith('native-'):
        raise SystemExit('Only a direct owned native-restore clone is accepted.')
    receipt=json.loads((target/'receipt.json').read_text())
    if receipt.get('native_asr_completed') is not True or receipt.get('ipsw_sha256') != IPSW_SHA:
        raise SystemExit('Owned native restore receipt is missing or unverified.')
    if args.persist_provisioning:validate_provisioning_clone(target,receipt,args.sep_firmware_profile)
    if args.persist_data_preparation:validate_data_clone(target,receipt,args.sep_firmware_profile)
    if args.persist_data_preparation and args.persist_provisioning:
        raise SystemExit('Choose one provisioning checkpoint mode.')
    images=plistlib.loads(subprocess.check_output(['hdiutil','info','-plist'],timeout=10))['images']
    if any(image.get('image-path')==str(target/'namespace-1.raw') for image in images):
        raise SystemExit('Detach the owned filesystem image before guest boot.')
    engine=RESEARCH/'Inferno/build-huntmob/qemu-system-aarch64-sep'
    if engine.is_symlink() or digest(engine) != SEP_ENGINE_SHA:
        raise SystemExit('Pinned engine unavailable.')
    for name,expected in SEP_INPUTS.items():
        if digest(RESEARCH/'firmware'/name)!=expected:raise SystemExit('SEP input differs from preparation receipt.')
    files={}
    for name in ['KernelCache','DeviceTree','RestoreRamDisk','RestoreTrustCache']:
        path=target/name
        if path.is_symlink() or digest(path)!=receipt['files'][name]['sha256']:
            raise SystemExit('Firmware component differs from its preparation receipt.')
        files[name]={'path':str(path)}
    try:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.settimeout(1);probe.connect(str(target/'qmp.sock'))
            raise SystemExit('Owned clone already running.')
    except OSError:pass
    launch=command(engine,target,files,restore=False,sep=True,companion_profile='x86_64',tcg_thread='single',create_disks=False)
    index=launch.index('-initrd');del launch[index:index+2]
    machine_index=launch.index('-M')+1
    launch[machine_index]=normal_sep_machine(launch[machine_index],args.sep_firmware_profile)+',boot-mode=exit_recovery'
    persistent=args.persist_provisioning or args.persist_data_preparation
    if persistent:launch.remove('-snapshot')
    # Ephemeral observation: host-prepared clone remains unchanged by guest writes.
    stamp=time.strftime('%Y%m%d-%H%M%S');log=target/f'disk-boot-{stamp}.log';started=time.monotonic()
    diagnostic=None;timed_out=False;shutdown_mode='engine-exit';checkpoint_observed=False
    if args.diagnose_sep_state:
        debug_socket=target/'sep-observer.sock'
        launch+=['-S','-gdb',f'unix:{debug_socket},server=on,wait=off']
    with log.open('xb') as output:
        process=subprocess.Popen(launch,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True,cwd=target)
        try:
            if args.diagnose_sep_state:
                try:diagnostic=observe_sep_state(debug_socket,timeout=min(30,args.seconds),profile=args.sep_firmware_profile,stage=args.sep_observation_stage)
                except (OSError,ValueError) as error:
                    diagnostic={'observation_failed':type(error).__name__,'reason':str(error)[:160]}
                    process.terminate()
            deadline=started+args.seconds
            while process.poll() is None:
                if persistent:
                    with log.open('rb') as reader:
                        reader.seek(max(0,log.stat().st_size-16384))
                        checkpoint_observed=b'HuntMob: provisioning checkpoint ready;' in reader.read(16384)
                    if checkpoint_observed:
                        if not quit_owned_vm(target/'qmp.sock'):
                            raise ValueError('Owned VM checkpoint could not be closed through QMP.')
                        shutdown_mode='qmp-quit-checkpoint';process.wait(timeout=10);break
                remaining=deadline-time.monotonic()
                if remaining<=0:raise subprocess.TimeoutExpired(launch,args.seconds)
                try:process.wait(timeout=min(.25,remaining))
                except subprocess.TimeoutExpired:pass
        except (subprocess.TimeoutExpired,KeyboardInterrupt):
            timed_out=True
            if quit_owned_vm(target/'qmp.sock'):shutdown_mode='qmp-quit-time-limit'
            else:shutdown_mode='signal-fallback';process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
        except ValueError as error:
            diagnostic={'observation_failed':'ValueError','reason':str(error)[:160]}
            shutdown_mode='supervision-error'
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=10)
    content=log.read_text(errors='replace')
    observations=boot_observations(content,timed_out)
    result={'command':launch,'engine_sha256':SEP_ENGINE_SHA,'log':str(log),'elapsed_seconds':round(time.monotonic()-started,2),'engine_exit_code':process.returncode,
            'normal_sep_sha256':SEP_PROFILES[args.sep_firmware_profile][1],
            'sep_firmware_profile':args.sep_firmware_profile,
            'sep_boot_state_observation':diagnostic,
            'shutdown_mode':shutdown_mode,'provisioning_checkpoint_observed':checkpoint_observed,
            'ramdisk_enabled':False,'ephemeral_guest_writes':not persistent,'panic_observed':'panic(cpu' in content,
            'launchd_observed':'Darwin Bootstrapper' in content,'springboard_log_observed':'SpringBoard' in content,
            **observations}
    path=target/f'disk-boot-{stamp}.json';path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'receipt':str(path),'panic_observed':result['panic_observed'],'launchd_observed':result['launchd_observed'],'springboard_validated':False}))
    if result['panic_observed'] or timed_out or (diagnostic and diagnostic.get('observation_failed')):raise SystemExit(1)

if __name__=='__main__':main()
