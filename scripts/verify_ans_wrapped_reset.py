#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: observe wrapped-context revocation and pending-read DMA across reset.
# Target: script-created ARM64 virt process and temporary 16 MiB disk only.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""Independent CC.EN reset fixture; never opens firmware or user disks.

Exit 1 and ok=false record an observed baseline failure. A passing synthetic
controller test does not establish SEP revocation or native iOS readiness.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import verify_ans_wrapped_xts as wrapped


transport = wrapped.transport
SENTINEL = bytes([0x5B]) * 8192
PASS = "HUNTMOB_ANS_WRAPPED_RESET_PASS"

RESET = r"""
    adr x1, .Lreset_entering
    mov x0, #4
    hlt #0xf000
    ldr x0, =0x10000000
    str wzr, [x0, #0x14]
    dsb sy
.Lreset_wait_not_ready:
    ldr w1, [x0, #0x1c]
    tbnz w1, #0, .Lreset_wait_not_ready
    adr x1, .Lreset_completed
    mov x0, #4
    hlt #0xf000
"""

RESTART = r"""
    // Completion phase bits from the old queues must not satisfy new polls.
    ldr x0, =0x40001000
    mov x1, #0x2000
.Lzero_admin_queues:
    str xzr, [x0], #8
    subs x1, x1, #8
    b.ne .Lzero_admin_queues
    ldr x0, =0x40020000
    mov x1, #0x6000
.Lzero_io_queues:
    str xzr, [x0], #8
    subs x1, x1, #8
    b.ne .Lzero_io_queues
    dsb sy
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
    dsb sy
.Lreset_wait_ready:
    ldr w1, [x0, #0x1c]
    tbnz w1, #1, .Lfail
    tbz w1, #0, .Lreset_wait_ready
"""

DELAY = r"""
    // Allow the throttled read to enter its asynchronous backend wait.
    mrs x8, cntfrq_el0
    mov x9, #20
    udiv x8, x8, x9
    mrs x9, cntvct_el0
    add x8, x8, x9
.Lpending_delay:
    mrs x9, cntvct_el0
    cmp x9, x8
    b.lo .Lpending_delay
"""


def row(name, opcode, cid, before=None, after=None, status=0, **kwargs):
    result = {"name": name, "command": transport.io_command(opcode, cid, **kwargs),
              "status": status}
    if before is not None:
        result["before"] = before
    if after is not None:
        result["after"] = after
    return result


def fixture(scenario, blob, ciphertext):
    pending = scenario == "pending_read_reset"
    first = wrapped.queues()
    if pending:
        first.append(row("warm_clear_read", 2, 3, before=bytes(4096), after=transport.CLEAR,
                         lba=0, units=1))
        request = row("pending_wrapped_read_posted", 2, 4, before=SENTINEL,
                      flags=4, extension=blob)
        request["async"] = True
        first.append(request)
        second = []
    else:
        first.extend([
            row("clear_write", 1, 3, before=transport.CLEAR, after=transport.CLEAR,
                lba=0, units=1),
            row("wrapped_write", 1, 4, before=transport.PLAINTEXT, after=transport.PLAINTEXT,
                flags=4, extension=blob),
            row("ciphertext_before_reset", 2, 5, before=SENTINEL, after=ciphertext),
        ])
        opcode = 2 if scenario == "reset_then_read" else 1
        second = wrapped.queues() + [
            row("ciphertext_after_reset", 2, 3, before=SENTINEL, after=ciphertext),
            row("revoked_wrapped_request", opcode, 4, before=SENTINEL, after=SENTINEL,
                status=0x4002, flags=4, extension=blob),
            row("independent_raw_read_after_reset", 2, 5, before=SENTINEL,
                after=transport.PLAINTEXT, flags=8, extension=bytes(32) + wrapped.RAW_DEK),
            row("ciphertext_after_rejection", 2, 6, before=SENTINEL, after=ciphertext),
        ]
    assembly = [transport.START.replace("    mov sp, x0\n", "    mov sp, x0\n    mov w6, #0\n")]
    literals, names = [], []

    def literal(label, data):
        literals.append(f".balign 8\n.{label}:\n    .byte " + ",".join(map(str, data)) + "\n")

    def emit(steps):
        indices = {0: 0, 1: 0}
        for item in steps:
            index = len(names)
            name = f"{index}_{item['name']}"
            names.append(name)
            literal(f"Lcommand{index}", item["command"])
            literals.append(f'.Lbegin{index}:\n    .asciz "BEGIN_{name}\\n"\n')
            assembly.append(f"    adr x1, .Lbegin{index}\n    mov x0, #4\n    hlt #0xf000\n")
            if item.get("before"):
                literal(f"Lbefore{index}", item["before"])
                assembly.append(f"    adr x0, .Lbefore{index}\n    mov x2, #{len(item['before'])}\n    bl .Lcopy_to_dma\n")
            queue = item.get("queue", 1)
            assembly.append(f"    adr x0, .Lcommand{index}\n    mov w1, #{queue}\n    mov x2, #{indices[queue]}\n")
            if item.get("async"):
                assembly.append("    mov w6, #1\n    bl .Lsubmit\n    mov w6, #0\n")
            else:
                assembly.append(f"    bl .Lsubmit\n    mov w1, #{item['status']}\n    cmp w0, w1\n    b.ne .Lfail\n")
            indices[queue] += 1
            if item.get("after"):
                literal(f"Lafter{index}", item["after"])
                assembly.append(f"    adr x0, .Lafter{index}\n    mov x2, #{len(item['after'])}\n    bl .Lcheck_dma\n")
            literals.append(f'.Lstep{index}:\n    .asciz "STEP_{name}_OK\\n"\n')
            assembly.append(f"    adr x1, .Lstep{index}\n    mov x0, #4\n    hlt #0xf000\n")

    emit(first)
    if pending:
        assembly.append(DELAY)
        literal("Lpending_sentinel", SENTINEL)
        assembly.append("    adr x0, .Lpending_sentinel\n    mov x2, #8192\n    bl .Lcheck_dma\n")
        literals.append('.Lpending_before:\n    .asciz "PENDING_DMA_UNCHANGED_BEFORE_RESET\\n"\n')
        assembly.append("    adr x1, .Lpending_before\n    mov x0, #4\n    hlt #0xf000\n")
    assembly.append(RESET)
    if pending:
        assembly.append("    adr x0, .Lpending_sentinel\n    mov x2, #8192\n    bl .Lcheck_dma\n")
        literals.append('.Lpending_preserved:\n    .asciz "PENDING_DMA_PRESERVED_AFTER_RESET\\n"\n')
        assembly.append("    adr x1, .Lpending_preserved\n    mov x0, #4\n    hlt #0xf000\n")
    else:
        assembly.append(RESTART)
        emit(second)
    helpers = transport.HELPERS.replace("HUNTMOB_ANS_UNWRAPPED_XTS_PASS", PASS)
    helpers = helpers.replace("    str w4, [x3]\n    ldr x5, =0x40002000\n",
                              "    str w4, [x3]\n    cbnz w6, .Lasync_posted\n    ldr x5, =0x40002000\n")
    helpers = helpers.replace(".balign 8\n.Lpass:", ".Lasync_posted:\n    ret\n.balign 8\n.Lpass:")
    require_once = "cbnz w6, .Lasync_posted"
    wrapped.require(helpers.count(require_once) == 1, "transport assembly template changed")
    assembly.append(helpers)
    literals.append('.Lreset_entering:\n    .asciz "BEFORE_RESET_CC_DISABLE\\n"\n')
    literals.append('.Lreset_completed:\n    .asciz "CONTROLLER_RESET_RDY_ZERO\\n"\n')
    assembly.extend(literals)
    assembly.append("\n.ltorg\n")
    return "".join(assembly), names


def exercise(engine, scenario, clang, objcopy):
    blob, ciphertext = wrapped.envelope(), wrapped.oracle()
    pending = scenario == "pending_read_reset"
    with tempfile.TemporaryDirectory(prefix="huntmob-wrapped-reset-public-") as directory:
        root = Path(directory)
        source, obj, image = (root / ("fixture" + ext) for ext in (".S", ".o", ".bin"))
        assembly, names = fixture(scenario, blob, ciphertext)
        source.write_text(assembly)
        for argv in ([clang, "--target=aarch64-none-elf", "-c", str(source), "-o", str(obj)],
                     [objcopy, "-O", "binary", str(obj), str(image)]):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=25)
            wrapped.require(result.returncode == 0, "fixture compilation failed: " + result.stderr[-600:])
        disk = root / "synthetic.raw"
        expected = bytearray(wrapped.DISK_BYTES)
        expected[:4096] = transport.CLEAR
        expected[transport.LBA * 4096:(transport.LBA + 2) * 4096] = ciphertext
        disk.write_bytes(expected if pending else bytes(wrapped.DISK_BYTES))
        secret = root / "public-context.bin"
        secret.write_bytes(wrapped.PUBLIC_CONTEXT)
        os.chmod(secret, 0o600)
        drive = f"file={disk},format=raw,if=none,id=testdisk"
        if pending:
            drive += ",throttling.bps-read=4096"
        result = subprocess.run([
            str(engine), "-M", "virt,highmem=off", "-cpu", "max", "-accel", "tcg", "-m", "64",
            "-display", "none", "-serial", "none", "-monitor", "none", "-nic", "none",
            "-kernel", str(image), "-semihosting-config", "enable=on,target=native",
            "-object", f"secret,id=public-context,file={secret},format=raw",
            "-drive", drive, "-device",
            "nvme,serial=HuntMobReset,addr=1,id=testnvme,is-apple-ans=on,"
            f"{wrapped.PROPERTY}=on,{wrapped.CONTEXT_PROPERTY}=public-context,"
            "apple-ans-lab-unwrapped-xts=on",
            "-device", "nvme-ns,drive=testdisk,bus=testnvme,nsid=1,logical_block_size=4096,physical_block_size=4096",
            "-trace", "enable=pci_nvme_apple_ans_complete",
            "-trace", "enable=pci_nvme_apple_ans_submit",
        ], capture_output=True, text=True, timeout=25)
        output = result.stdout + result.stderr
        begin = re.findall(r"^BEGIN_([a-zA-Z0-9_]+)$", output, re.MULTILINE)
        completed = re.findall(r"^STEP_([a-zA-Z0-9_]+)_OK$", output, re.MULTILINE)
        events = [dict(zip(("sqid", "cid", "opcode", "status"), match)) for match in re.findall(
            r"pci_nvme_apple_ans_complete sqid=(\d+) cid=(\d+) opcode=(0x[0-9a-f]+) status=(0x[0-9a-f]+)", output)]
        passed = result.returncode == 0 and PASS in output and completed == names
        pending_at_entry = None
        if pending:
            # Semihost markers and QEMU trace records must share stderr so
            # concatenating stdout/stderr cannot manufacture their ordering.
            stream = result.stderr
            entry = stream.find("BEFORE_RESET_CC_DISABLE")
            submit = stream.find("pci_nvme_apple_ans_submit sqid=1 cid=4 opcode=0x02")
            completion = stream.find("pci_nvme_apple_ans_complete sqid=1 cid=4 opcode=0x02")
            pending_at_entry = ("PENDING_DMA_UNCHANGED_BEFORE_RESET" in stream and
                                entry >= 0 and 0 <= submit < entry and
                                (completion < 0 or completion > entry))
            passed = passed and pending_at_entry
        unchanged = disk.read_bytes() == expected
        return {
            "scenario": scenario, "ok": passed and unchanged,
            "guest_exit_code": result.returncode,
            "controller_rdy_zero_observed": "CONTROLLER_RESET_RDY_ZERO" in output,
            "last_started_stage": begin[-1] if begin else None,
            "completed_stages": completed, "expected_stage_count": len(names),
            "pending_dma_preserved": "PENDING_DMA_PRESERVED_AFTER_RESET" in output if pending else None,
            "pending_request_outstanding_at_reset_entry": pending_at_entry,
            "post_reset_protected_requests_refused": passed if not pending else None,
            "independent_raw_read_after_reset_verified": any(
                name.endswith("independent_raw_read_after_reset") for name in completed),
            "clear_backing_preserved": unchanged, "completion_metadata": events,
            "failure_output_was_present": "HUNTMOB_ANS_UNWRAPPED_XTS_FAIL" in output,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--authorized-lab", action="store_true", required=True)
    parser.add_argument("--clang", default=shutil.which("clang") or "clang")
    parser.add_argument("--objcopy", default=shutil.which("llvm-objcopy") or "/opt/homebrew/opt/llvm/bin/llvm-objcopy")
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    before = hashlib.sha256(engine.read_bytes()).hexdigest()
    sources = (Path(__file__).resolve(), Path(wrapped.__file__).resolve(),
               Path(transport.__file__).resolve())
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    reports = [exercise(engine, scenario, args.clang, args.objcopy)
               for scenario in ("reset_then_read", "reset_then_write", "pending_read_reset")]
    wrapped.require(hashlib.sha256(engine.read_bytes()).hexdigest() == before,
                    "engine changed during validation")
    wrapped.require(all(hashlib.sha256(path.read_bytes()).hexdigest() == source_hashes[path.name]
                        for path in sources), "synthetic test source changed during validation")
    ok = all(report["ok"] for report in reports)
    print(json.dumps({
        "schema": "huntmob.ans-wrapped-reset-public-fixture.v1", "ok": ok,
        "engine_sha256": before, "test_source_sha256": source_hashes, "reports": reports,
        "scope": "script-created virt and temporary 16 MiB disk; public synthetic context only",
        "ready": False, "native_sep_revocation_validated": False,
        "hardware_context_source_validated": False, "guest_abi_validated": False,
        "data_protection_validated": False, "springboard_validated": False,
    }, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
