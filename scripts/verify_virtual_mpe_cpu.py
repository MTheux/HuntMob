#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: execute public code on the genuine SEP CPU/private ROMD consumer.
# Target: new paused t8030 process and disposable public disks only.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""Own VirtualMPE-v1 integration; no guest firmware is executed.

Uses the owned pinned firmware only to instantiate the production machine. AP
PCs run public B. loops; SEP runs a public freestanding fixture. No root/context,
firmware or disk inputs are accepted. Host debugger remains in the trusted base.
"""
import argparse
import hashlib
import json
import re
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path

import verify_virtual_sep_ans_mmio as transport

PRIVATE = 0x340000000
OUTPUT = transport.DATA
SPIN = 0x800150000
MISC1 = 0x241240000
LENGTH = 64 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def compile_fixture(folder, kind):
    if kind == 'stores-exclusive-smc':
        body = r'''
    ldr x0, =0x800105000
    ldr x2, =0x340004000
    mov x3, #17
    str x3, [x2]
    ldr x4, [x2]
    cmp x4, x3
    b.ne .Lfail
    mov x6, #16
.Lexclusive:
    ldaxr x4, [x2]
    add x4, x4, #1
    stlxr w5, x4, [x2]
    cbz w5, .Lexclusive_done
    subs x6, x6, #1
    b.ne .Lexclusive
    b .Lfail
.Lexclusive_done:
    cmp x4, #18
    b.ne .Lfail
    // A second store in the same line must preserve the committed value.
    str xzr, [x2, #8]
    ldr x9, [x2]
    cmp x9, #18
    b.ne .Lfail
    str x4, [x0, #8]
    bl .Ltarget
    cmp w5, #1
    b.ne .Lfail
    adr x7, .Ltarget
    mov w8, #0x45
    movk w8, #0x5280, lsl #16
    str w8, [x7]
    ldr w9, [x7, #4]
    str w9, [x7, #4]
    dsb ish
    ic ivau, x7
    dsb ish
    isb
    bl .Ltarget
    cmp w5, #2
    b.ne .Lfail
    str x5, [x0, #16]
    mrs x8, id_aa64mmfr1_el1
    str x8, [x0, #24]
    b .Lpass
.Ltarget:
    mov w5, #1
    ret
'''
    elif kind == 'mmu-hardware-access-flag':
        body = r'''
    ldr x0, =0x800105000
    mrs x8, id_aa64mmfr1_el1
    str x8, [x0, #24]
    and x9, x8, #15
    cbz x9, .Lfail
    // Two public 4KiB tables in the private ROMD cache. VA40/PA40 identity.
    ldr x2, =0x340008000
    ldr x3, =0x340009003
    str x3, [x2]
    ldr x2, =0x340009000
    ldr x3, =0x340000301
    str x3, [x2, #104]
    ldr x3, =0x800000701
    str x3, [x2, #256]
    ldr x2, =0x340008000
    msr ttbr0_el1, x2
    mov x3, #255
    msr mair_el1, x3
    ldr x3, =0x8200803518
    msr tcr_el1, x3
    dsb ish
    tlbi vmalle1
    dsb ish
    isb
    mrs x4, sctlr_el1
    orr x5, x4, #1
    msr sctlr_el1, x5
    isb
    // Instruction fetch must set AF in a descriptor stored in private ROMD.
    ldr x2, =0x340009068
    ldr x3, [x2]
    tbz x3, #10, .Lfail
    str x3, [x0, #32]
    msr sctlr_el1, x4
    isb
    // With MMU off, no subsequent PTW can silently set AF again. A normal
    // write to another word of the same authenticated line reloads its
    // canonical ciphertext. AF must survive that RMW, proving its update
    // reached the device rather than only the plaintext ROMD cache.
    str xzr, [x2, #8]
    ldr x3, [x2]
    tbz x3, #10, .Lfail
    str x3, [x0, #32]
    b .Lpass
'''
    else:
        raise ValueError('Unknown bounded fixture')
    assembly = '.text\n.globl _start\n.globl _fixture_done\n_start:\n' + body + r'''
.Lpass:
    ldr x0, =0x800105000
    ldr x1, =0x4d5045ff
    str x1, [x0]
    b .Lfixture_done
.Lfail:
    ldr x0, =0x800105000
    mov x1, #0xdead
    str x1, [x0]
_fixture_done:
.Lfixture_done:
    b .Lfixture_done
'''
    source, obj, image = (folder / ('public-fixture' + ext) for ext in ('.S', '.o', '.bin'))
    source.write_text(assembly)
    clang = shutil.which('clang') or '/usr/bin/clang'
    objcopy = shutil.which('llvm-objcopy') or '/opt/homebrew/opt/llvm/bin/llvm-objcopy'
    nm = shutil.which('llvm-nm') or '/opt/homebrew/opt/llvm/bin/llvm-nm'
    objdump = shutil.which('llvm-objdump') or '/opt/homebrew/opt/llvm/bin/llvm-objdump'
    subprocess.run([clang, '--target=aarch64-none-elf', '-c', str(source), '-o', str(obj)],
                   capture_output=True, check=True, timeout=20)
    relocations = subprocess.run([objdump, '-r', str(obj)], capture_output=True,
                                 check=True, text=True, timeout=10).stdout
    require(re.search(r'\bR_AARCH64_\w+', relocations) is None,
            'Raw fixture has unresolved relocations; never execute it')
    subprocess.run([objcopy, '-O', 'binary', str(obj), str(image)],
                   capture_output=True, check=True, timeout=20)
    symbols = subprocess.run([nm, '--defined-only', str(obj)], capture_output=True,
                             check=True, text=True, timeout=10).stdout
    done = re.findall(r'^([0-9a-fA-F]+) T _fixture_done$', symbols, re.MULTILINE)
    require(len(done) == 1, 'Fixture breakpoint symbol unavailable')
    return image.read_bytes(), int(done[0], 16)


def configure(machine):
    dev = transport.Devices(machine)
    dev.aess(0x200)
    dev.aess(0x211, bytes(range(16)) * 2)
    machine.w32(MISC1 + 0x80, 0)
    dev.aess(0x200)  # Must preserve the first independent MPE latch.
    dev.aess(0x251, bytes(range(16, 32)) * 2)
    machine.w32(MISC1 + 0x80, 0x100)
    start = (machine.r32(0x2000006a0) & 0x3fffff) << 12
    end = ((machine.r32(0x2000006a4) & 0x3fffff) << 12) + 4096
    secondary = (start + 2320 * (LENGTH >> 10) + 16383) & ~16383
    require(start < end and end - start == 240 * 1024 * 1024, 'Pinned TZ shape changed')
    for register, value in [(0x300, start >> 10), (0x318, secondary >> 10), (0x310, LENGTH >> 10),
                            (0x400, 0), (0x408, (LENGTH >> 9) - 1), (0x410, 1),
                            (0x410, 0), (0x400, 0), (0x408, 0)]:
        machine.w32(MISC1 + register, value)
    return start


def private_debugger(machine):
    require('multiprocess+' in machine.rsp('qSupported:multiprocess+'), 'Multiprocess debugger required')
    for process in (2, 3):
        require(machine.rsp(f'vAttach;{process:x}').startswith('T'), 'CPU cluster attach failed')
    # Production PMGR power-on; no CPU object or firmware patch.
    machine.w32(0x23b080c00, 0)
    machine.write(SPIN, bytes.fromhex('00000014'))
    threads, reply = [], machine.rsp('qfThreadInfo')
    while reply != 'l':
        require(reply.startswith('m') and len(threads) <= 8, 'Unexpected debugger thread inventory')
        threads.extend(reply[1:].split(','))
        reply = machine.rsp('qsThreadInfo')
    sep = [name for name in threads if re.fullmatch(r'p0?3\.0?7', name)]
    require(len(sep) == 1 and len(threads) == 7, 'Pinned SEP CPU identity changed')
    # Round-robin TCG needs the AP scheduling positions runnable. Their only
    # executable instruction is our public spin; no Apple code is resumed.
    for name in threads:
        if name != sep[0]:
            require(machine.rsp('Hg' + name) == 'OK', 'AP selection failed')
            require(machine.rsp('P20=' + struct.pack('<Q', SPIN).hex()) == 'OK', 'AP spin PC setup failed')
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        info = bytes.fromhex(machine.rsp('qThreadExtraInfo,' + sep[0])).decode()
        if '[running]' in info:
            break
        time.sleep(.005)
    else:
        raise RuntimeError('Production SEP power-on did not complete')
    require(machine.rsp('Hg' + sep[0]) == 'OK', 'SEP selection failed')
    require(machine.rsp('Qqemu.PhyMemMode:0') == 'OK', 'SEP virtual debug mode unavailable')
    return sep[0]


def run_case(engine, kind):
    engine_sha = transport.boot.digest(engine)
    with tempfile.TemporaryDirectory(prefix='hm-mpecpu-', dir='/tmp') as directory:
        folder = Path(directory)
        code, done = compile_fixture(folder, kind)
        argv, _ = transport.prepare(engine, folder)
        m = transport.PausedMachine(argv, folder)
        try:
            tz = configure(m)
            sep = private_debugger(m)
            m.write(PRIVATE, code)
            # This is the actual production initialization consumer, not an ACK.
            require(m.rsp('Qqemu.PhyMemMode:1') == 'OK', 'Physical debug mode unavailable')
            started = time.monotonic()
            m.w32(MISC1 + 0x414, 1)
            initialization_seconds = time.monotonic() - started
            require(m.r32(MISC1 + 0x414) & 1, 'MPE did not initialize')
            require(m.rsp('Qqemu.PhyMemMode:0') == 'OK', 'SEP view unavailable')
            require(m.read(PRIVATE, len(code)) == code, 'Private code cache readback mismatch')
            require(m.rsp('P20=' + struct.pack('<Q', PRIVATE).hex()) == 'OK', 'SEP fixture PC setup failed')
            require(m.rsp(f'Z1,{PRIVATE + done:x},4') == 'OK', 'Public fixture breakpoint unavailable')
            try:
                stopped = m.rsp('vCont;c')
            except (TimeoutError, socket.timeout):
                m.gdb.sendall(b'\x03')
                while m.gdb.recv(1) != b'$':
                    pass
                packet = bytearray()
                while True:
                    char = m.gdb.recv(1)
                    if char == b'#':
                        break
                    packet += char
                m.gdb.recv(2)
                m.gdb.sendall(b'+')
                pc = int.from_bytes(bytes.fromhex(m.rsp('p20')), 'little')
                m.rsp('Qqemu.PhyMemMode:1')
                marker = int.from_bytes(m.read(OUTPUT, 8), 'little')
                require(pc == PRIVATE + done and marker == 0x4d5045ff,
                        f'Public CPU fixture timeout, PC={pc:#x}, marker={marker:#x}')
                stopped = packet.decode('ascii')
            require(re.fullmatch(r'T0[25]thread:p0?3\.0?7;', stopped) is not None, 'Fixture did not stop on SEP breakpoint')
            require(int.from_bytes(bytes.fromhex(m.rsp('p20')), 'little') == PRIVATE + done,
                    'SEP stopped at unexpected PC')
            require(m.rsp('Qqemu.PhyMemMode:1') == 'OK', 'AP physical view unavailable')
            output = struct.unpack('<5Q', m.read(OUTPUT, 40))
            require(output[0] == 0x4d5045ff,
                    'Public CPU fixture reported failure (hafdbs=' + str(output[3] & 15) +
                    ', af_observed_before_rmw=' + str(bool(output[4] & 0x400)) + ')')
            if kind == 'stores-exclusive-smc':
                require(output[1] == 18 and output[2] == 2, 'Store/exclusive/SMC result mismatch')
            else:
                require(output[3] & 15 and output[4] & 0x400, 'Hardware access flag not written')
            aperture_cipher = m.read(PRIVATE, 64)
            physical_cipher = m.read(0x800000000 + tz, 64)
            require(aperture_cipher == physical_cipher and aperture_cipher != code[:64],
                    'AP physical aperture/backing differs or exposes plaintext')
            m.write(PRIVATE, bytes([0xa7]) * 64)
            m.write(0x800000000 + tz, bytes([0xb8]) * 64)
            require(m.read(PRIVATE, 64) == aperture_cipher and
                    m.read(0x800000000 + tz, 64) == aperture_cipher, 'Denied AP write changed ciphertext')
            require(m.rsp('Qqemu.PhyMemMode:0') == 'OK', 'SEP view unavailable after denied AP write')
            # SMC deliberately changed one instruction; the entry remains intact.
            require(m.read(PRIVATE, 16) == code[:16], 'Denied AP write changed private code')
            require(m.command('query-status')['running'] is False, 'Public CPU fixture remained running')
            result = {'case': kind, 'passed': True, 'actual_sep_cpu_executed_private_romd': True,
                      'completion_stop_reply': stopped,
                      'ordinary_store': kind == 'stores-exclusive-smc',
                      'ldaxr_stlxr': kind == 'stores-exclusive-smc',
                      'self_modifying_code_tb_invalidated': kind == 'stores-exclusive-smc',
                      'mmu_hardware_access_flag': kind == 'mmu-hardware-access-flag',
                      'same_line_rmw_preserves_committed_changes': True,
                      'ap_aperture_and_physical_tz_ciphertext_match': True,
                      'ap_writes_leave_ciphertext_and_private_code_unchanged': True,
                      'primary_bytes_initialized': LENGTH,
                      'initialization_seconds': round(initialization_seconds, 6),
                      'fixture_sha256': hashlib.sha256(code).hexdigest(),
                      'verifier_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      'firmware_executed': False, 'host_debugger_in_trusted_base': True}
        finally:
            m.close()
        require(transport.boot.digest(engine) == engine_sha, 'Engine changed during CPU test')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-lab', required=True, action='store_true')
    parser.add_argument('--engine', type=Path, required=True)
    parser.add_argument('--case', choices=('stores-exclusive-smc', 'mmu-hardware-access-flag'),
                        default='stores-exclusive-smc')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    result = run_case(engine, args.case)
    result.update(schema=1, engine_sha256=transport.boot.digest(engine), native_ready=False,
                  apple_mpe_equivalence=False, data_protection_validated=False,
                  springboard_validated=False, ipa_execution_validated=False)
    data = json.dumps(result, indent=2) + '\n'
    if args.output:
        with args.output.open('x') as out:
            out.write(data)
    print(data, end='')


if __name__ == '__main__':
    main()
