#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: real NVMe protected-I/O refusal and synthetic disk persistence.
# Target: new ARM64 QEMU virt instance and temporary synthetic disk only.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""Build a freestanding ARM64 fixture; no firmware/checkpoint is opened."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path


def command(opcode, cid, flags=0, nsid=0, prp1=0, dwords=()):
    data = bytearray(64)
    struct.pack_into("<BBHI", data, 0, opcode, flags, cid, nsid)
    struct.pack_into("<Q", data, 24, prp1)
    for index, value in enumerate(dwords):
        struct.pack_into("<I", data, 40 + index * 4, value)
    return data


def fixture(guard):
    requests = [(0, command(5, 1, prp1=0x40004000, dwords=(1 | 15 << 16, 1)), 0, False),
                (0, command(1, 2, prp1=0x40003000, dwords=(1 | 15 << 16, 1 | 1 << 16)), 0, False),
                (1, command(1, 10, nsid=1, prp1=0x40005000, dwords=(0, 0, 0)), 0, False),
                (1, command(2, 11, nsid=1, prp1=0x40005000, dwords=(0, 0, 0)), 0, True)]
    for mode in (4, 8, 12):
        for opcode in (2, 1):
            requests.append((1, command(opcode, 100 + mode + opcode, flags=mode,
                             nsid=1, prp1=0x40005000, dwords=(0, 0, 0)),
                             0x4002 if guard else 0, guard))
    asm = r""".text
.globl _start
_start:
    ldr x0, =0x41000000
    mov sp, x0
    ldr x0, =0x3f008010
    mov w1, #0x10000000
    str w1, [x0]
    str wzr, [x0, #4]
    ldr x0, =0x3f008004
    mov w1, #6
    strh w1, [x0]
    ldr x0, =0x10000000
    mov w1, #0xf000f
    str w1, [x0, #0x24]
    ldr w1, =0x40001000
    str w1, [x0, #0x28]
    str wzr, [x0, #0x2c]
    ldr w1, =0x40002000
    str w1, [x0, #0x30]
    str wzr, [x0, #0x34]
    ldr w1, =0x470001
    str w1, [x0, #0x14]
    ldr w1, [x0, #0x1c]
    tbz w1, #0, .Lfail
    adr x1, .Lready
    mov x0, #4
    hlt #0xf000
"""
    indices = {0: 0, 1: 0}
    for index, (queue, data, status, check_buffer) in enumerate(requests):
        fill = 0xa5 if index < 4 else 0x50 + index
        # Clear read uses a different sentinel so actual readback is verified.
        if index == 3:
            fill = 0x5a
        asm += f"""
    mov w0, #{fill}
    bl .Lfill
    adr x0, .Lcommand{index}
    mov w1, #{queue}
    mov x2, #{indices[queue]}
    bl .Lsubmit
    mov w1, #{status}
    cmp w0, w1
    b.ne .Lfail
"""
        if index == 3 or check_buffer:
            expected = 0xa5 if index == 3 else fill
            asm += f"""    mov w0, #{expected}
    bl .Lcheck
"""
        asm += f"""    adr x1, .Lstep{index}
    mov x0, #4
    hlt #0xf000
"""
        indices[queue] += 1
    asm += r"""
    adr x1, .Lpass
    b .Lexit
.Lfail:
    adr x1, .Lfailed
.Lexit:
    mov x0, #4
    hlt #0xf000
    adr x1, .Lexitparams
    mov x0, #0x20
    hlt #0xf000
    b .
.Lfill:
    ldr x1, =0x40005000
    mov x2, #4096
.Lfill_loop:
    strb w0, [x1], #1
    subs x2, x2, #1
    b.ne .Lfill_loop
    ret
.Lcheck:
    ldr x1, =0x40005000
    mov x2, #4096
.Lcheck_loop:
    ldrb w3, [x1], #1
    cmp w3, w0
    b.ne .Lfail
    subs x2, x2, #1
    b.ne .Lcheck_loop
    ret
.Lsubmit:
    ldr x3, =0x40001000
    add x3, x3, x1, lsl #13
    add x3, x3, x2, lsl #6
    cbz w1, .Ladmin_stride
    add x3, x3, x2, lsl #6
.Ladmin_stride:
    ldp x4, x5, [x0]
    stp x4, x5, [x3]
    ldp x4, x5, [x0, #16]
    stp x4, x5, [x3, #16]
    ldp x4, x5, [x0, #32]
    stp x4, x5, [x3, #32]
    ldp x4, x5, [x0, #48]
    stp x4, x5, [x3, #48]
    dsb sy
    ldr x3, =0x10001000
    add x3, x3, x1, lsl #3
    add w4, w2, #1
    str w4, [x3]
    ldr x5, =0x40002000
    add x5, x5, x1, lsl #13
    add x5, x5, x2, lsl #4
.Lpoll:
    ldrh w0, [x5, #14]
    tbz w0, #0, .Lpoll
    lsr w0, w0, #1
    str w4, [x3, #4]
    dsb sy
    ret
.balign 8
.Lready:
    .asciz "READY\n"
.Lpass:
    .asciz "HUNTMOB_NVME_PROBE_PASS\n"
.Lfailed:
    .asciz "HUNTMOB_NVME_PROBE_FAIL\n"
.balign 8
.Lexitparams:
    .quad 0x20026, 0
"""
    for index, (_, data, _, _) in enumerate(requests):
        asm += f'.Lstep{index}:\n    .asciz "STEP_{index}_OK\\n"\n'
        asm += f""".balign 8
.Lcommand{index}:
    .byte """ + ",".join(str(b) for b in data) + "\n".replace("\\n", "\n")
    asm += "\n.ltorg\n".replace("\\n", "\n")
    return asm


def exercise(engine, apple_ans, baseline, clang, objcopy):
    guarded = apple_ans and not baseline
    with tempfile.TemporaryDirectory(prefix="huntmob-ans-fixture-") as td:
        root = Path(td)
        source, obj, image = root / "fixture.S", root / "fixture.o", root / "fixture.bin"
        source.write_text(fixture(guarded))
        subprocess.run([clang, "--target=aarch64-none-elf", "-c", str(source), "-o", str(obj)],
                       check=True, capture_output=True, timeout=25)
        subprocess.run([objcopy, "-O", "binary", str(obj), str(image)],
                       check=True, capture_output=True, timeout=25)
        disk = root / "synthetic.raw"
        disk.write_bytes(bytes(16 * 1024 * 1024))
        result = subprocess.run([
            str(engine), "-M", "virt,highmem=off", "-cpu", "max", "-accel", "tcg",
            "-m", "64", "-display", "none", "-serial", "none", "-monitor", "none",
            "-nic", "none", "-kernel", str(image), "-semihosting-config", "enable=on,target=native",
            "-drive", f"file={disk},format=raw,if=none,id=testdisk",
            "-device", "nvme,serial=HuntMobFixture,addr=1,id=testnvme," + f"is-apple-ans={'on' if apple_ans else 'off'}",
            "-device", "nvme-ns,drive=testdisk,bus=testnvme,nsid=1,logical_block_size=4096,physical_block_size=4096",
        ], capture_output=True, text=True, timeout=25)
        if "HUNTMOB_NVME_PROBE_PASS" not in result.stdout + result.stderr:
            raise RuntimeError("synthetic guest NVMe validation failed: " + (result.stdout + result.stderr)[-600:])
        data = disk.read_bytes()
        expected = bytes([0xa5 if guarded else 0x59]) * 4096 + bytes(len(data) - 4096)
        if data != expected:
            raise RuntimeError("synthetic backing differs from expected protected-I/O behavior")
        return {"apple_ans": apple_ans, "guard_expected": guarded, "clear_io_verified": True,
                "protected_reads_writes_checked": 6, "rejected_status": "0x4002" if guarded else None,
                "protected_dma_and_backing_unchanged": guarded,
                "synthetic_backing_sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--authorized-lab", action="store_true", required=True)
    parser.add_argument("--baseline", action="store_true", help="Negative control: require unguarded Apple ANS")
    parser.add_argument("--clang", default=shutil.which("clang") or "clang")
    parser.add_argument("--objcopy", default=shutil.which("llvm-objcopy") or "/opt/homebrew/opt/llvm/bin/llvm-objcopy")
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    reports = [exercise(engine, True, args.baseline, args.clang, args.objcopy),
               exercise(engine, False, args.baseline, args.clang, args.objcopy)]
    print(json.dumps({"ok": True, "reports": reports}, indent=2))

if __name__ == "__main__":
    main()
