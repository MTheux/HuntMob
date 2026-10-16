#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: exercise the own-identity SEP -> ANS model through real device MMIO.
# Target: this script's new paused t8030 process and disposable public disks.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""Production-device integration, with public fixtures and no OS execution.

No root, disk, firmware or context inputs are accepted. Firmware is read only
from the existing pinned owned receipt. The only engine input is an executable.
GDB's physical-memory transport drives the genuine AESS, KEY and ANS handlers;
it does not call a test provider stub. The model is not Apple SEP equivalence.
"""
import argparse
import hashlib
import hmac
import json
import os
import socket
import struct
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import boot_ios_research as boot
import verify_ans_unwrapped_xts as io

PUBLIC_ROOT = bytes(range(32))
PUBLIC_VM_ID = uuid.UUID('00112233-4455-6677-8899-aabbccddeeff')
PUBLIC_CONTEXT = bytes(range(32, 60))
PUBLIC_DEK = bytes(range(96, 128))
FLAGS = 0x1b140
DISK_BYTES = 16 * 1024 * 1024
AESS = 0x241040000
KEY = 0x2411c0000
ANS = 0x27acc0000
ANS_RTK = 0x277400000
ASQ, ACQ = 0x800100000, 0x800101000
DATA, IOSQ, IOCQ = 0x800105000, 0x800120000, 0x800124000
EXPECTED_FIRMWARE = {
    'KernelCache': 'cfb260879625327b06d5549abc42a84daa86bebf6a894403aad7633ee94148a3',
    'DeviceTree': 'dbd9be96c4b18f48a1842879237ae8f27043b894a2ed6139e396dbedca232411',
    'RestoreRamDisk': '4013d9b3bb6c7fa0ff82397effc032b6afdb6f3c5e1672782698119dd9b3f704',
    'RestoreTrustCache': 'af33b3466bd828bf1ccaa1ab35d060bfcce62ade26ee74acf176501b00ea0d7f',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def cbc(key, payload, iv=bytes(16)):
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return enc.update(payload) + enc.finalize()


def kdf(label, context):
    frame = struct.pack('>I', 1) + label.encode('ascii') + b'\x00' + context + struct.pack('>I', 256)
    return hmac.new(PUBLIC_ROOT, frame, hashlib.sha256).digest()


def expected_envelope(context, bank=0):
    scope = PUBLIC_VM_ID.bytes + bytes([bank]) + context
    wrap = kdf('HuntMob.VirtualSEP.v1/inline-wrap', scope)
    auth = kdf('HuntMob.VirtualSEP.v1/inline-auth', scope)
    ciphertext = cbc(wrap, PUBLIC_DEK)
    mac = cbc(auth, ciphertext + bytes(12) + struct.pack('<I', FLAGS))[-16:]
    return struct.pack('<I', FLAGS) + bytes(12) + mac + ciphertext


def expected_storage():
    out = bytearray()
    for index in range(2):
        enc = Cipher(algorithms.AES(PUBLIC_DEK), modes.XTS((io.FILE_UNIT + index).to_bytes(16, 'little'))).encryptor()
        out += enc.update(io.PLAINTEXT[index * 4096:(index + 1) * 4096]) + enc.finalize()
    require(out != io.PLAINTEXT, 'XTS oracle returned plaintext')
    return bytes(out)


class PausedMachine:
    """Local UNIX sockets only; all operations have bounded deadlines."""
    def __init__(self, argv, folder):
        self.folder = folder
        self.log = (folder / 'engine.log').open('ab')
        self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                        stdout=self.log, stderr=subprocess.STDOUT,
                                        start_new_session=True, cwd=folder)
        self.qmp = self.gdb = None
        try:
            self.qmp = self.connect(folder / 'qmp.sock')
            self.qf = self.qmp.makefile('rwb', buffering=0)
            require('QMP' in json.loads(self.qf.readline()), 'QMP greeting unavailable')
            self.command('qmp_capabilities')
            require(self.command('query-status')['running'] is False, 'VM must remain paused')
            tree = self.command('human-monitor-command', {'command-line': 'info mtree'})
            for name, address in [('sep.aess_base', AESS), ('sep.key_base', KEY),
                                  ('alias apple-ans.nvme', ANS), ('apple-a7iop.ANS2.regs', ANS_RTK)]:
                require(any(name in line and f'{address:016x}-' in line for line in tree.splitlines()),
                        'Pinned device MMIO map mismatch: ' + name)
            self.gdb = self.connect(folder / 'gdb.sock')
            require(self.rsp('Qqemu.PhyMemMode:1') == 'OK', 'GDB physical mode unavailable')
            require(self.rsp('qqemu.PhyMemMode') == '1', 'GDB physical mode not active')
        except Exception:
            self.close()
            raise

    def connect(self, path):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(self.process.poll() is None, 'Owned emulator exited during startup; see private engine log')
            sock = socket.socket(socket.AF_UNIX)
            sock.settimeout(3)
            try:
                sock.connect(str(path))
                return sock
            except (FileNotFoundError, ConnectionRefusedError):
                sock.close()
                time.sleep(.03)
        raise RuntimeError('Owned emulator socket startup timeout')

    def command(self, name, args=None):
        self.qf.write((json.dumps({'execute': name, 'arguments': args or {}}) + '\n').encode())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            line = self.qf.readline()
            require(bool(line), 'QMP disconnected')
            result = json.loads(line)
            if 'return' in result:
                return result['return']
            require('error' not in result, 'QMP command failed: ' + name)
        raise RuntimeError('QMP response deadline exceeded')

    def rsp(self, message):
        packet = message.encode('ascii')
        self.gdb.sendall(b'$' + packet + b'#' + f'{sum(packet) % 256:02x}'.encode())
        deadline = time.monotonic() + 4
        while self.gdb.recv(1) != b'$':
            require(time.monotonic() < deadline, 'GDB packet deadline exceeded')
        payload = bytearray()
        while time.monotonic() < deadline:
            char = self.gdb.recv(1)
            require(bool(char), 'GDB disconnected')
            if char == b'#':
                checksum = self.gdb.recv(2)
                require(len(checksum) == 2 and int(checksum, 16) == sum(payload) % 256,
                        'GDB checksum mismatch')
                self.gdb.sendall(b'+')
                return payload.decode('ascii')
            payload += char
            require(len(payload) <= 4096, 'GDB response exceeded bounded fixture packet')
        raise RuntimeError('GDB response deadline exceeded')

    def write(self, address, payload):
        for offset in range(0, len(payload), 512):
            chunk = payload[offset:offset + 512]
            require(self.rsp(f'M{address + offset:x},{len(chunk):x}:' + chunk.hex()) == 'OK',
                    'Owned physical write failed')

    def read(self, address, length):
        out = bytearray()
        for offset in range(0, length, 512):
            count = min(512, length - offset)
            data = self.rsp(f'm{address + offset:x},{count:x}')
            require(len(data) == count * 2 and not data.startswith('E'), 'Owned physical read failed')
            out += bytes.fromhex(data)
        return bytes(out)

    def w32(self, address, value):
        self.write(address, struct.pack('<I', value))

    def r32(self, address):
        return int.from_bytes(self.read(address, 4), 'little')

    def close(self):
        if self.process.poll() is None:
            try:
                if self.qmp is not None:
                    self.command('quit')
            except Exception:
                self.process.terminate()
            try:
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=6)
        for sock in (self.gdb, self.qmp):
            if sock is not None:
                sock.close()
        self.log.close()


class Devices:
    def __init__(self, machine):
        self.m = machine
        self.completed = []
        self.tail = [0, 0]
        self.head = [0, 0]
        self.cid = 1
        self.aess_commands = []
        self.key_controls = []

    def aess(self, command, payload=None, expect=True):
        if payload is not None:
            require(len(payload) == 32, 'AESS input requires 32 fixture bytes')
            for offset in range(0, 32, 4):
                self.m.write(AESS + 0x40 + offset, payload[offset:offset + 4])
        self.m.w32(AESS + 8, command)
        self.m.w32(AESS + 4, 1)
        status, interrupt = self.m.r32(AESS + 4), self.m.r32(AESS + 0xc)
        success = not(status & 0x600) and not(status & 2) and (interrupt & 3) == 1
        require(bool(success) is expect, 'AESS command status mismatch for ' + hex(command))
        self.aess_commands.append({'command': command, 'accepted': expect})
        return self.m.read(AESS + 0x60, 32)

    def program(self, context=PUBLIC_CONTEXT, bank=0, latch=True):
        self.aess(0x241 if bank else 0x201, struct.pack('<I', 0x7772616b) + context)
        self.aess(0x245 if bank else 0x205)
        self.aess(0x2c1 if bank else 0x281, struct.pack('<I', 0x6175746b) + context)
        self.aess(0x244 if bank else 0x204)
        if latch:
            for control in (bank, 2 + bank, 10 + bank):
                self.key(control)

    def key(self, control):
        self.m.w32(KEY + 8, control)
        self.key_controls.append(control)

    def envelope(self, context=PUBLIC_CONTEXT, bank=0):
        cipher = self.aess(0x246 if bank else 0x206, PUBLIC_DEK)
        authentication = self.aess(0x48 if bank else 8, cipher)
        mac = self.aess(0xc8 if bank else 0x88,
                        authentication[-16:] + bytes(12) + struct.pack('<I', FLAGS))[-16:]
        blob = struct.pack('<I', FLAGS) + bytes(12) + mac + cipher
        require(blob == expected_envelope(context, bank), 'MMIO envelope differs from independent own-model oracle')
        return blob

    def initialize_nvme(self):
        # Genuine RTKit start enables the existing controller's PCI bus master.
        self.m.w32(ANS_RTK + 0x44, 0x10)
        require(self.m.r32(ANS + 8) != 0, 'NVMe version register unavailable')
        for address in (ASQ, ACQ, IOSQ, IOCQ):
            self.m.write(address, bytes(8192))
        self.m.w32(ANS + 0x24, 0xf000f)
        self.m.write(ANS + 0x28, struct.pack('<Q', ASQ))
        self.m.write(ANS + 0x30, struct.pack('<Q', ACQ))
        self.m.w32(ANS + 0x14, 0x470001)
        require(self.m.r32(ANS + 0x1c) & 3 == 1, 'ANS controller did not become ready')
        self.submit('create_cq', io.admin_command(5, self.cid, IOCQ, 1 | 63 << 16, 1), queue=0)
        self.submit('create_sq', io.admin_command(1, self.cid, IOSQ, 1 | 63 << 16, 1 | 1 << 16), queue=0)

    def submit(self, name, command, queue=1, status=0, before=None, after=None):
        command = bytearray(command)
        struct.pack_into('<H', command, 2, self.cid)
        if queue:
            # Rewrite the old virt harness's public DMA addresses to owned t8030 RAM.
            units = struct.unpack_from('<H', command, 48)[0] + 1
            struct.pack_into('<QQ', command, 24, DATA, DATA + 4096 if units > 1 else 0)
        if before is not None:
            self.m.write(DATA, before)
        require(self.tail[queue] < (64 if queue else 16), 'Fixture queue bound exceeded')
        base = IOSQ if queue else ASQ
        self.m.write(base + self.tail[queue] * (128 if queue else 64), command)
        self.tail[queue] += 1
        self.m.w32(ANS + 0x1000 + queue * 8, self.tail[queue])
        cqe_address = (IOCQ if queue else ACQ) + self.head[queue] * 16
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            cqe = self.m.read(cqe_address, 16)
            if struct.unpack_from('<H', cqe, 14)[0] & 1:
                break
            time.sleep(.003)
        else:
            raise RuntimeError('ANS completion deadline: ' + name)
        actual_cid, completion = struct.unpack_from('<HH', cqe, 12)
        require(actual_cid == self.cid and completion >> 1 == status,
                f'ANS completion mismatch: {name} (status {completion >> 1:#x})')
        self.head[queue] += 1
        self.m.w32(ANS + 0x1004 + queue * 8, self.head[queue])
        if after is not None:
            require(self.m.read(DATA, len(after)) == after, 'DMA differs from oracle: ' + name)
        self.completed.append({'name': name, 'status': status})
        self.cid += 1

    def storage(self, name, opcode, blob=None, before=None, after=None, status=0):
        self.submit(name, io.io_command(opcode, self.cid, flags=4 if blob else 0,
                                       extension=blob), before=before, after=after, status=status)


def prepare(engine, folder):
    receipt = json.loads((boot.RESEARCH / 'ios-vms/native-20261013-215607/receipt.json').read_text())
    require(receipt.get('build') == '18A5351d', 'Owned firmware build receipt mismatch')
    for name, expected in EXPECTED_FIRMWARE.items():
        item = receipt['files'][name]
        path = Path(item['path'])
        require(not path.is_symlink() and boot.digest(path) == expected and item['sha256'] == expected,
                'Owned firmware hash mismatch: ' + name)
    for name, expected in boot.SEP_INPUTS.items():
        path = boot.RESEARCH / 'firmware' / name
        require(not path.is_symlink() and boot.digest(path) == expected, 'Owned SEP firmware hash mismatch')
    args = boot.command(engine, folder, receipt['files'], sep=True,
                        companion_profile='x86_64', tcg_thread='single', create_disks=True)
    args.remove('-snapshot')
    # nstype=1 encodes a boot root namespace with a >=1 GiB minimum. This paused
    # controller fixture deliberately uses a standard CSI_NVM namespace, not APFS.
    args = [arg.replace('nsid=1,nstype=1,', 'nsid=1,nstype=0,') for arg in args]
    with (folder / 'namespace-1.raw').open('r+b') as out:
        out.truncate(DISK_BYTES)
    public = folder / 'PUBLIC-root-fixture.bin'
    public.write_bytes(PUBLIC_ROOT)
    public.chmod(0o600)
    index = args.index('-M') + 1
    args[index] += (',huntmob-virtual-sep-root-secret=public-root'
                    ',huntmob-virtual-sep-vm-id=' + str(PUBLIC_VM_ID))
    args += ['-object', f'secret,id=public-root,file={public},format=raw', '-S',
             '-gdb', f'unix:{folder}/gdb.sock,server=on,wait=off']
    return args, {p.name: boot.digest(p) for p in folder.glob('*.raw')}


def backing_check(folder, expected):
    actual = (folder / 'namespace-1.raw').read_bytes()
    require(actual == expected, 'Complete 16 MiB fixture differs from storage oracle')
    require(io.PLAINTEXT not in actual, 'Plaintext marker persisted in fixture storage')
    return hashlib.sha256(actual).hexdigest()


def run(engine):
    engine_hash = boot.digest(engine)
    with tempfile.TemporaryDirectory(prefix='hm-vsep-', dir='/tmp') as directory:
        folder = Path(directory)
        argv, originals = prepare(engine, folder)
        expected_disk = bytearray(DISK_BYTES)
        ciphertext = expected_storage()
        sentinel = bytes([0xa7]) * 8192
        m = PausedMachine(argv, folder)
        try:
            initialized = {name: boot.digest(folder / name) for name in originals}
            initialization_changes = [name for name in originals if originals[name] != initialized[name]]
            require(initialization_changes == ['namespace-5.raw'], 'Unexpected blank-backing initialization')
            initialized_nvram = (folder / 'namespace-5.raw').read_bytes()
            initialized_offsets = [index for index, value in enumerate(initialized_nvram) if value]
            require(bool(initialized_offsets) and len(initialized_nvram) == 8192, 'NVRAM initialization shape mismatch')
            d = Devices(m)
            d.aess(0x200)
            d.initialize_nvme()
            d.program(latch=False)
            blob = d.envelope()
            d.storage('before_any_latch_rejected', 1, blob, sentinel, sentinel, 0x4002)
            backing_check(folder, expected_disk)
            d.key(0)
            d.storage('before_auth_latch_rejected', 1, blob, sentinel, sentinel, 0x4002)
            backing_check(folder, expected_disk)
            d.key(2)
            d.key(10)
            d.storage('published_two_unit_write', 1, blob, io.PLAINTEXT, io.PLAINTEXT)
            expected_disk[io.LBA * 4096:(io.LBA + 2) * 4096] = ciphertext
            backing_check(folder, expected_disk)
            d.storage('published_two_unit_read', 2, blob, sentinel, io.PLAINTEXT)
            d.storage('ciphertext_independent_read', 2, None, sentinel, ciphertext)
            for name, offset in [('flags', 0), ('reserved', 4), ('tag', 16), ('ciphertext', 63)]:
                invalid = bytearray(blob)
                invalid[offset] ^= 1
                for opcode in (1, 2):
                    d.storage('tampered_' + name + ('_write' if opcode == 1 else '_read'),
                              opcode, bytes(invalid), sentinel, sentinel, 0x4002)
                    backing_check(folder, expected_disk)
            # Reprogramming invalidates active bank0 before either new latch.
            changed_context = bytes([0x63]) * 28
            d.aess(0x201, struct.pack('<I', 0x7772616b) + changed_context)
            d.storage('candidate_reprogram_revoked', 2, blob, sentinel, sentinel, 0x4002)
            d.program(changed_context)
            changed_blob = d.envelope(changed_context)
            require(changed_blob != blob, 'Different public context produced same envelope')
            d.storage('new_context_reads_same_file_dek', 2, changed_blob, sentinel, io.PLAINTEXT)
            d.storage('old_context_blob_rejected', 2, blob, sentinel, sentinel, 0x4002)
            d.program(PUBLIC_CONTEXT)
            blob = d.envelope()
            # Secondary publication must not erase a coherent primary pair.
            d.program(bytes([0x74]) * 28, bank=1)
            d.storage('primary_survives_secondary_publication', 2, blob, sentinel, io.PLAINTEXT)
            d.key(4)
            d.storage('own_model_key_control4_revoked', 2, blob, sentinel, sentinel, 0x4002)
            d.program()
            d.storage('cached_context_replay_new_lease', 2, blob, sentinel, io.PLAINTEXT)
            d.aess(0x200)
            d.storage('engine_init_revoked', 2, blob, sentinel, sentinel, 0x4002)
            d.program()
            d.storage('replay_after_engine_init', 2, blob, sentinel, io.PLAINTEXT)
            # UID uses own VM identity, not the globally constant legacy UID.
            m.w32(AESS + 0x1c, 0x21)
            d.aess(0x40)
            m.w32(AESS + 0x14, 2)
            uid = d.aess(2, bytes(range(32)))
            uid_key = kdf('HuntMob.VirtualSEP.v1/UID0', PUBLIC_VM_ID.bytes + struct.pack('>I', 0x21))
            first = cbc(uid_key, bytes(range(32)))
            expected_uid = cbc(uid_key, first, first[-16:])
            require(uid == expected_uid, 'UID0 MMIO differs from independent own-model oracle')
            d.aess(0x50)
            m.w32(AESS + 0x14, 1)
            uid1 = d.aess(0x12, bytes(range(32)))
            uid1_key = kdf('HuntMob.VirtualSEP.v1/UID1', PUBLIC_VM_ID.bytes + struct.pack('>I', 0x21))
            require(uid1 == cbc(uid1_key, bytes(range(32))), 'UID1 MMIO differs from own-model oracle')
            # Native SEPOS repeats this UID seed-control traffic after its
            # inline pair was published. 0x80 clears the caller software-key
            # domain; it must not destroy programmable wrapping/auth banks.
            d.program()
            m.w32(AESS + 0x18, 0xb)
            for _ in range(8):
                d.aess(0x240)
                d.aess(0x80)
                d.aess(0x202, bytes(range(32)))
            require(d.envelope() == blob, 'UID seed controls destroyed or changed inline envelope')
            d.storage('primary_survives_native_uid_seed_controls', 2, blob, sentinel, io.PLAINTEXT)
            d.aess(0x12, bytes(range(32)), expect=False)
            require(m.command('query-status')['running'] is False, 'Fixture unexpectedly executed CPUs')
            first_receipt = {'completions': d.completed, 'aess_operations': d.aess_commands,
                             'key_control_operations': d.key_controls}
        finally:
            m.close()
        backing_hash = backing_check(folder, expected_disk)
        for name, digest in initialized.items():
            if name != 'namespace-1.raw':
                require(boot.digest(folder / name) == digest, 'Unrelated post-realize backing changed: ' + name)
        # Actual process restart: no new storage WRITE, same private temporary
        # fixture and public identity, fresh production provider/AESS/KEY state.
        for name in ('qmp.sock', 'gdb.sock', 'usb.sock'):
            path = folder / name
            if path.exists():
                require(path.is_socket(), 'Unexpected fixture socket replacement')
                path.unlink()
        require(boot.digest(engine) == engine_hash, 'Engine changed during integration')
        before_restart = {name: boot.digest(folder / name) for name in initialized}
        m = PausedMachine(argv, folder)
        try:
            restarted_baselines = {name: boot.digest(folder / name) for name in initialized}
            restart_initialization_changes = [name for name in before_restart if before_restart[name] != restarted_baselines[name]]
            require(set(restart_initialization_changes) <= {'namespace-5.raw'}, 'Unexpected restart initialization writes')
            d = Devices(m)
            d.aess(0x200)
            d.initialize_nvme()
            d.program(latch=False)
            blob = d.envelope()
            d.storage('restart_before_latches_rejected', 2, blob, sentinel, sentinel, 0x4002)
            d.key(0)
            d.key(2)
            d.key(10)
            d.storage('restart_protected_read', 2, blob, sentinel, io.PLAINTEXT)
            d.storage('restart_ciphertext_read', 2, None, sentinel, ciphertext)
            # AESS unrecoverable errors are sticky until a full reset. Keep
            # this separate negative case last in the fresh restart process.
            d.aess(0x20b, bytes(range(32)))
            d.aess(0x80)
            d.aess(0x89, expect=False)
            require(m.command('query-status')['running'] is False, 'Restart unexpectedly executed CPUs')
            restart_receipt = {'completions': d.completed, 'aess_operations': d.aess_commands,
                               'key_control_operations': d.key_controls}
        finally:
            m.close()
        backing_check(folder, expected_disk)
        for name, digest in restarted_baselines.items():
            if name != 'namespace-1.raw':
                require(boot.digest(folder / name) == digest, 'Restart MMIO altered unrelated post-realize backing')
        require(boot.digest(engine) == engine_hash, 'Engine changed before final receipt')
        return {
            'schema': 1, 'date': '2026-10-15', 'passed': True,
            'authorized_lab': True, 'engine_sha256': engine_hash,
            'profile': 'HuntMob.VirtualSEP.v1 experimental own identity',
            'transport': 'local UNIX GDB RSP physical-memory writes; production device handlers',
            'firmware_build': '18A5351d', 'firmware_hashes_verified': True,
            'firmware_executed': False, 'cpu_execution_enabled': False,
            'public_test_root_only': True, 'host_context_secret_fixture_used': False,
            'actual_aess_key_ans_devices': True, 'aess_envelope_independent_oracle': True,
            'uid_mmio_independent_oracle': True, 'key_latches_required_before_ans': True,
            'two_4096_byte_xts_units_file_iv_distinct_from_lba': True,
            'full_16mib_backing_matches_oracle': True,
            'rejections_preserve_dma_and_backing': True,
            'fresh_process_read_roundtrip': True, 'fresh_process_no_storage_writes': True,
            'eight_other_new_backings_unchanged_during_mmio': True,
            'machine_start_initialization_changes': initialization_changes,
            'namespace5_initialization_nonzero_bytes': len(initialized_offsets),
            'namespace5_initialization_changed_offset_min': min(initialized_offsets),
            'namespace5_initialization_changed_offset_max': max(initialized_offsets),
            'namespace5_initialization_source': 't8030.c:595 apple_nvram_save after parsing/setting boot NVRAM',
            'restart_machine_initialization_changes': restart_initialization_changes,
            'other_backings_zero_to_final_unchanged': False, 'existing_lab_images_opened': False,
            'backing_sha256': backing_hash, 'initial': first_receipt, 'restart': restart_receipt,
            'hardware_abi_validated': False, 'apple_sep_equivalence': False,
            'data_protection_validated': False, 'springboard_validated': False,
            'ipa_execution_validated': False, 'native_ready': False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', required=True, action='store_true')
    parser.add_argument('--engine', required=True, type=Path)
    parser.add_argument('--output', type=Path, help='New JSON receipt; existing files are not overwritten')
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    require(engine.is_file() and os.access(engine, os.X_OK), 'Engine must be executable')
    result = run(engine)
    data = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as out:
            out.write(data)
    print(data, end='')


if __name__ == '__main__':
    main()
