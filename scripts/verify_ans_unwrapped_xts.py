#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: validate explicitly enabled synthetic ANS unwrapped XTS I/O.
# Target: new ARM64 QEMU virt process and temporary 16 MiB fixture only.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""Independent AES-XTS oracle; never opens iOS firmware or checkpoint disks."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PROPERTY = "apple-ans-lab-unwrapped-xts"
DATA_ADDRESS = 0x40005000
IOSQ = 0x40020000
IOCQ = 0x40024000
LBA = 7
FILE_UNIT = 0x1122334455667780
UNIT_SIZE = 4096
# Public, synthetic and intentionally non-secret; no guest/device keys accepted.
SYNTHETIC_KEY = bytes(range(32))
PLAINTEXT = bytes((i * 37 + (i >> 5) + 17) & 255 for i in range(8192))
CLEAR = bytes((i * 19 + 11) & 255 for i in range(4096))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def oracle():
    result = bytearray()
    for index in range(2):
        # Explicit synthetic convention, not a validated hardware ABI.
        tweak = (FILE_UNIT + index).to_bytes(16, "little")
        encryptor = Cipher(algorithms.AES(SYNTHETIC_KEY), modes.XTS(tweak)).encryptor()
        block = PLAINTEXT[index * UNIT_SIZE:(index + 1) * UNIT_SIZE]
        result.extend(encryptor.update(block) + encryptor.finalize())
    require(result != PLAINTEXT, "independent oracle unexpectedly returned plaintext")
    return bytes(result)


def io_command(opcode, cid, flags=0, lba=LBA, units=2, unit=FILE_UNIT,
               extension=None, mptr=0, control=0):
    command = bytearray(128)
    struct.pack_into("<BBHI", command, 0, opcode, flags, cid, 1)
    struct.pack_into("<Q", command, 16, mptr)
    struct.pack_into("<QQ", command, 24, DATA_ADDRESS,
                     DATA_ADDRESS + UNIT_SIZE if units > 1 else 0)
    struct.pack_into("<QHH", command, 40, lba, units - 1, control)
    struct.pack_into("<Q", command, 56, unit)
    if extension is not None:
        require(len(extension) == 64, "fixture extension must have exactly 64 bytes")
        command[64:] = extension
    return bytes(command)


def admin_command(opcode, cid, pointer, dword10, dword11):
    command = bytearray(64)
    struct.pack_into("<BBHI", command, 0, opcode, 0, cid, 0)
    struct.pack_into("<Q", command, 24, pointer)
    struct.pack_into("<II", command, 40, dword10, dword11)
    return bytes(command)


def cases(enabled, ciphertext):
    extension = bytes(32) + SYNTHETIC_KEY
    records = [
        {"name": "create_cq", "queue": 0,
         "command": admin_command(5, 1, IOCQ, 1 | 63 << 16, 1), "status": 0},
        {"name": "create_sq", "queue": 0,
         "command": admin_command(1, 2, IOSQ, 1 | 63 << 16, 1 | 1 << 16), "status": 0},
        {"name": "clear_write", "command": io_command(1, 3, lba=0, units=1),
         "before": CLEAR, "after": CLEAR, "status": 0},
        {"name": "clear_read", "command": io_command(2, 4, lba=0, units=1),
         "before": bytes([0x5a]) * 4096, "after": CLEAR, "status": 0},
    ]
    if enabled:
        records.extend([
            {"name": "unwrapped_two_unit_write", "command": io_command(1, 5, flags=8, extension=extension),
             "before": PLAINTEXT, "after": PLAINTEXT, "status": 0},
            {"name": "unwrapped_two_unit_read", "command": io_command(2, 6, flags=8, extension=extension),
             "before": bytes([0xc3]) * 8192, "after": PLAINTEXT, "status": 0},
            {"name": "independent_ciphertext_read", "command": io_command(2, 7),
             "before": bytes([0x3c]) * 8192, "after": ciphertext, "status": 0},
        ])
        malformed = bytearray(extension)
        malformed[0] = 1
        reserved = bytearray(extension)
        reserved[16] = 1
        variants = [
            ("wrapped", {"flags": 4, "extension": extension}),
            ("contradictory", {"flags": 12, "extension": extension}),
            ("malformed_extension", {"flags": 8, "extension": bytes(malformed)}),
            ("malformed_reserved_prefix", {"flags": 8, "extension": bytes(reserved)}),
            ("missing_key_extension", {"flags": 8, "extension": bytes(64)}),
            ("exceeds_one_mib", {"flags": 8, "extension": extension, "units": 257}),
            ("equal_key_halves", {"flags": 8, "extension": bytes(32) + bytes(range(16)) * 2}),
            ("unsupported_metadata_pointer", {"flags": 8, "extension": extension, "mptr": DATA_ADDRESS}),
            ("unsupported_control", {"flags": 8, "extension": extension, "control": 0x4000}),
            ("unsupported_sgl", {"flags": 0x48, "extension": extension}),
            ("unsupported_fused", {"flags": 0x09, "extension": extension, "expected_status": 2}),
            ("unit_sequence_overflow", {"flags": 8, "extension": extension, "unit": (1 << 64) - 1}),
        ]
    else:
        variants = [("default_disabled_unwrapped", {"flags": 8, "extension": extension})]
    cid = 10
    for name, kwargs in variants:
        kwargs = dict(kwargs)
        expected_status = kwargs.pop("expected_status", 0x4002)
        for opcode in (1, 2):
            sentinel = bytes([0x80 + cid]) * 8192
            records.append({"name": name + ("_write" if opcode == 1 else "_read"),
                            "command": io_command(opcode, cid, **kwargs), "before": sentinel,
                            "after": sentinel, "status": expected_status, "rejection": True})
            cid += 1
            records.append({"name": name + "_backing_check",
                            "command": io_command(2, cid), "before": bytes([0x29]) * 8192,
                            "after": ciphertext if enabled else bytes(8192), "status": 0})
            cid += 1
    require(len([r for r in records if r.get("queue", 1) == 1]) < 64,
            "fixture exceeded its bounded queue")
    return records


START = r""".text
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
"""

HELPERS = r"""
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
.Lcopy_to_dma:
    ldr x1, =0x40005000
.Lcopy_loop:
    ldrb w3, [x0], #1
    strb w3, [x1], #1
    subs x2, x2, #1
    b.ne .Lcopy_loop
    dsb sy
    ret
.Lcheck_dma:
    ldr x1, =0x40005000
.Lcheck_loop:
    ldrb w3, [x0], #1
    ldrb w4, [x1], #1
    cmp w3, w4
    b.ne .Lfail
    subs x2, x2, #1
    b.ne .Lcheck_loop
    ret
.Lsubmit:
    ldr x3, =0x40001000
    cbz w1, .Ladmin_queue
    ldr x3, =0x40020000
    add x3, x3, x2, lsl #7
    ldp x4, x5, [x0, #64]
    stp x4, x5, [x3, #64]
    ldp x4, x5, [x0, #80]
    stp x4, x5, [x3, #80]
    ldp x4, x5, [x0, #96]
    stp x4, x5, [x3, #96]
    ldp x4, x5, [x0, #112]
    stp x4, x5, [x3, #112]
    b .Lcopy_command
.Ladmin_queue:
    add x3, x3, x2, lsl #6
.Lcopy_command:
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
    cbz w1, .Lcompletion_address
    ldr x5, =0x40024000
.Lcompletion_address:
    add x5, x5, x2, lsl #4
.Lpoll:
    ldrh w0, [x5, #14]
    tbz w0, #0, .Lpoll
    lsr w0, w0, #1
    str w4, [x3, #4]
    dsb sy
    ret
.balign 8
.Lpass:
    .asciz "HUNTMOB_ANS_UNWRAPPED_XTS_PASS\n"
.Lfailed:
    .asciz "HUNTMOB_ANS_UNWRAPPED_XTS_FAIL\n"
.balign 8
.Lexitparams:
    .quad 0x20026, 0
"""


def fixture(records):
    asm = [START]
    literals = []
    indices = {0: 0, 1: 0}
    def literal(label, data):
        literals.append(f".balign 8\n.{label}:\n    .byte " + ",".join(map(str, data)) + "\n")
    for index, row in enumerate(records):
        literal(f"Lcommand{index}", row["command"])
        before = row.get("before")
        if before:
            literal(f"Lbefore{index}", before)
            asm.append(f"    adr x0, .Lbefore{index}\n    mov x2, #{len(before)}\n    bl .Lcopy_to_dma\n")
        queue = row.get("queue", 1)
        asm.append(f"    adr x0, .Lcommand{index}\n    mov w1, #{queue}\n"
                   f"    mov x2, #{indices[queue]}\n    bl .Lsubmit\n    mov w1, #{row['status']}\n"
                   "    cmp w0, w1\n    b.ne .Lfail\n")
        indices[queue] += 1
        after = row.get("after")
        if after:
            literal(f"Lafter{index}", after)
            asm.append(f"    adr x0, .Lafter{index}\n    mov x2, #{len(after)}\n    bl .Lcheck_dma\n")
        step = f"STEP_{index}_{row['name']}_OK"
        literals.append(f'.Lstep{index}:\n    .asciz "{step}\\n"\n')
        asm.append(f"    adr x1, .Lstep{index}\n    mov x0, #4\n    hlt #0xf000\n")
    asm.append(HELPERS)
    asm.extend(literals)
    asm.append("\n.ltorg\n")
    return "".join(asm)


def restart_cases(ciphertext):
    """Read only after process restart; explicitly provide synthetic raw key again."""
    return [
        {"name": "restart_create_cq", "queue": 0,
         "command": admin_command(5, 1, IOCQ, 1 | 63 << 16, 1), "status": 0},
        {"name": "restart_create_sq", "queue": 0,
         "command": admin_command(1, 2, IOSQ, 1 | 63 << 16, 1 | 1 << 16), "status": 0},
        {"name": "restart_clear_read", "command": io_command(2, 3, lba=0, units=1),
         "before": bytes([0x4f]) * 4096, "after": CLEAR, "status": 0},
        {"name": "restart_unwrapped_read", "command": io_command(2, 4, flags=8,
                            extension=bytes(32) + SYNTHETIC_KEY),
         "before": bytes([0x4a]) * 8192, "after": PLAINTEXT, "status": 0},
        {"name": "restart_ciphertext_read", "command": io_command(2, 5),
         "before": bytes([0x4b]) * 8192, "after": ciphertext, "status": 0},
    ]


def exercise(engine, enabled, clang, objcopy, ciphertext, trace=False):
    records = cases(enabled, ciphertext)
    with tempfile.TemporaryDirectory(prefix="huntmob-ans-unwrapped-") as td:
        root = Path(td)
        disk = root / "synthetic.raw"
        disk.write_bytes(bytes(16 * 1024 * 1024))
        controller = "nvme,serial=HuntMobFixture,addr=1,id=testnvme,is-apple-ans=on"
        # Omit property entirely for the default-off control.
        if enabled:
            controller += f",{PROPERTY}=on"
        diagnostics = ["-trace", "enable=pci_nvme_apple_ans_complete"] if trace else []

        def run_guest(steps, suffix):
            source, obj, image = (root / f"fixture-{suffix}{ext}" for ext in (".S", ".o", ".bin"))
            source.write_text(fixture(steps))
            for argv in ([clang, "--target=aarch64-none-elf", "-c", str(source), "-o", str(obj)],
                         [objcopy, "-O", "binary", str(obj), str(image)]):
                result = subprocess.run(argv, capture_output=True, text=True, timeout=25)
                require(result.returncode == 0, "fixture compilation failed: " + result.stderr[-600:])
            result = subprocess.run([
                str(engine), "-M", "virt,highmem=off", "-cpu", "max", "-accel", "tcg",
                "-m", "64", "-display", "none", "-serial", "none", "-monitor", "none",
                "-nic", "none", "-kernel", str(image), "-semihosting-config", "enable=on,target=native",
                "-drive", f"file={disk},format=raw,if=none,id=testdisk",
                "-device", controller,
                "-device", "nvme-ns,drive=testdisk,bus=testnvme,nsid=1,logical_block_size=4096,physical_block_size=4096",
            ] + diagnostics, capture_output=True, text=True, timeout=25)
            output = result.stdout + result.stderr
            require(result.returncode == 0 and "HUNTMOB_ANS_UNWRAPPED_XTS_PASS" in output,
                    "actual-controller validation failed: " + output[-1200:])
            for index, row in enumerate(steps):
                require(f"STEP_{index}_{row['name']}_OK" in output, "missing guest validation receipt")

        run_guest(records, "initial")
        expected = bytearray(16 * 1024 * 1024)
        expected[:4096] = CLEAR
        if enabled:
            expected[LBA * UNIT_SIZE:(LBA + 2) * UNIT_SIZE] = ciphertext
        stored = disk.read_bytes()
        require(stored == expected, "full synthetic backing differs from independent expected bytes")
        if enabled:
            require(PLAINTEXT not in stored, "synthetic plaintext leaked into backing")
            # New process, same temporary backing, no storage WRITE commands.
            # This validates raw fixture persistence, not APFS/SEP key persistence.
            restarted = restart_cases(ciphertext)
            require(all(row.get("queue", 1) == 0 or row["command"][0] == 2
                        for row in restarted), "restart fixture must issue storage READ only")
            run_guest(restarted, "restarted")
            require(disk.read_bytes() == stored, "read-only restart changed synthetic backing")
        return {"property_omitted_default_off": not enabled, "opt_in_enabled": enabled,
                "clear_io_verified": True, "two_units": enabled, "unit_bytes": UNIT_SIZE,
                "file_unit_differs_from_physical_lba": FILE_UNIT != LBA,
                "ciphertext_matches_independent_oracle": enabled,
                "protected_read_roundtrip_verified": enabled,
                "fresh_process_read_verified": enabled,
                "fresh_process_backing_unchanged": enabled,
                "synthetic_raw_key_explicitly_supplied_after_restart": enabled,
                "sep_or_apfs_persistence_validated": False,
                "rejected_requests": [row["name"] for row in records if row.get("rejection")],
                "rejection_dma_unchanged_and_backing_verified_each_time": True,
                "completed_requests": len(records), "restart_requests": 5 if enabled else 0,
                "backing_sha256": hashlib.sha256(stored).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--authorized-lab", action="store_true", required=True)
    parser.add_argument("--trace-diagnostics", action="store_true", help="Log command identity and completion status only")
    parser.add_argument("--clang", default=shutil.which("clang") or "clang")
    parser.add_argument("--objcopy", default=shutil.which("llvm-objcopy") or "/opt/homebrew/opt/llvm/bin/llvm-objcopy")
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    engine_sha256 = hashlib.sha256(engine.read_bytes()).hexdigest()
    ciphertext = oracle()
    reports = [exercise(engine, False, args.clang, args.objcopy, ciphertext, args.trace_diagnostics),
               exercise(engine, True, args.clang, args.objcopy, ciphertext, args.trace_diagnostics)]
    require(hashlib.sha256(engine.read_bytes()).hexdigest() == engine_sha256,
            "engine changed during validation; refuse to attribute results")
    print(json.dumps({"version": 1, "ok": True, "ready": False,
                      "hardware_abi_validated": False, "wrapped_key_support": False,
                      "oracle": "Python cryptography AES-128-XTS, explicit synthetic convention",
                      "engine_sha256": engine_sha256,
                      "reports": reports}, indent=2))

if __name__ == "__main__":
    main()
