#!/usr/bin/env python3
# ==========================================
# AUTHORIZED TESTING ONLY — ISOLATED LAB
# Purpose: verify the opt-in ANS wrapped-envelope model with public fixtures.
# Target: script-created ARM64 virt process and temporary 16 MiB disk only.
# WARNING: Unauthorized use is illegal.
# ==========================================
"""Actual-controller validation; accepts no firmware, disk, or key inputs.

The synthetic context is deliberately public. Success is not evidence of Apple
hardware key derivation, guest key transfer, Data Protection, or iOS readiness.
"""

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

import verify_ans_unwrapped_xts as transport


PROPERTY = "apple-ans-lab-wrapped-xts"
CONTEXT_PROPERTY = "apple-ans-lab-wrapped-xts-secret"
MARKER = "HUNTMOB_ANS_WRAPPED_XTS_PASS"
FLAGS = 0x1B140
WRAP_KEY = bytes(range(32, 64))
AUTH_KEY = bytes(range(64, 96))
PUBLIC_CONTEXT = WRAP_KEY + AUTH_KEY
RAW_DEK = bytes(range(96, 128))
DISK_BYTES = 16 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def envelope(flags=FLAGS):
    """Independent cryptography composition, without importing the C codec."""
    encryptor = Cipher(algorithms.AES(WRAP_KEY), modes.CBC(bytes(16))).encryptor()
    ciphertext = encryptor.update(RAW_DEK) + encryptor.finalize()
    authenticator = Cipher(algorithms.AES(AUTH_KEY), modes.CBC(bytes(16))).encryptor()
    mac = authenticator.update(ciphertext + bytes(12) + struct.pack("<I", flags))
    mac += authenticator.finalize()
    return struct.pack("<I", flags) + bytes(12) + mac[-16:] + ciphertext


def oracle():
    result = bytearray()
    for index in range(2):
        tweak = (transport.FILE_UNIT + index).to_bytes(16, "little")
        encryptor = Cipher(algorithms.AES(RAW_DEK), modes.XTS(tweak)).encryptor()
        block = transport.PLAINTEXT[index * 4096:(index + 1) * 4096]
        result.extend(encryptor.update(block) + encryptor.finalize())
    require(result != transport.PLAINTEXT, "oracle unexpectedly returned plaintext")
    return bytes(result)


def queues():
    return [
        {"name": "create_cq", "queue": 0,
         "command": transport.admin_command(5, 1, transport.IOCQ, 1 | 63 << 16, 1), "status": 0},
        {"name": "create_sq", "queue": 0,
         "command": transport.admin_command(1, 2, transport.IOSQ, 1 | 63 << 16, 1 | 1 << 16), "status": 0},
    ]


def records(accepted, blob, ciphertext, restart=False):
    steps = queues()
    cid = 3

    def command(name, opcode, status=0, before=None, after=None, rejection=False, **kwargs):
        nonlocal cid
        row = {"name": name, "command": transport.io_command(opcode, cid, **kwargs),
               "status": status}
        if before is not None:
            row["before"] = before
        if after is not None:
            row["after"] = after
        if rejection:
            row["rejection"] = True
        steps.append(row)
        cid += 1

    if not restart:
        command("clear_write", 1, lba=0, units=1, before=transport.CLEAR, after=transport.CLEAR)
    command("clear_read", 2, lba=0, units=1,
            before=bytes([0x5A]) * 4096, after=transport.CLEAR)
    backing = ciphertext if accepted else bytes(8192)
    if accepted:
        if not restart:
            command("wrapped_two_unit_write", 1, flags=4, extension=blob,
                    before=transport.PLAINTEXT, after=transport.PLAINTEXT)
        command("wrapped_two_unit_read", 2, flags=4, extension=blob,
                before=bytes([0xC3]) * 8192, after=transport.PLAINTEXT)
        command("independent_ciphertext_read", 2,
                before=bytes([0x3C]) * 8192, after=ciphertext)
    if not restart:
        variants = []
        if accepted:
            # Cover framing, tag, and both CBC ciphertext blocks independently.
            for name, offset in (("flags_tamper", 0), ("reserved_tamper", 4),
                                 ("tag_tamper", 16), ("cipher_first_tamper", 32),
                                 ("cipher_last_tamper", 63)):
                changed = bytearray(blob)
                changed[offset] ^= 1
                variants.append((name, {"flags": 4, "extension": bytes(changed)}))
            variants.extend([
                ("empty_envelope", {"flags": 4, "extension": bytes(64)}),
                ("authenticated_unsupported_flags", {"flags": 4, "extension": envelope(0)}),
                ("contradictory_key_flags", {"flags": 12, "extension": blob}),
                ("metadata_pointer", {"flags": 4, "extension": blob, "mptr": transport.DATA_ADDRESS}),
                ("unsupported_control", {"flags": 4, "extension": blob, "control": 0x4000}),
                ("unsupported_sgl", {"flags": 0x44, "extension": blob}),
                ("unsupported_fused", {"flags": 0x05, "extension": blob, "expected_status": 2}),
                ("unit_overflow", {"flags": 4, "extension": blob, "unit": (1 << 64) - 1}),
            ])
        else:
            variants.append(("wrapped_rejected", {"flags": 4, "extension": blob}))
        for name, kwargs in variants:
            kwargs = dict(kwargs)
            expected_status = kwargs.pop("expected_status", 0x4002)
            for opcode in (1, 2):
                sentinel = bytes([0x80 + cid]) * 8192
                command(name + ("_write" if opcode == 1 else "_read"), opcode,
                        status=expected_status, before=sentinel, after=sentinel,
                        rejection=True, **kwargs)
                command(name + "_backing_unchanged", 2,
                        before=bytes([0x29]) * 8192, after=backing)
    require(sum(row.get("queue", 1) == 1 for row in steps) < 64,
            "fixture exceeds bounded queue size")
    if restart:
        require(all(row.get("queue", 1) == 0 or row["command"][0] == 2 for row in steps),
                "fresh-process fixture must issue storage READ only")
    return steps


def run_guest(engine, root, disk, steps, suffix, enabled, context, clang, objcopy,
              trace=False, expect_startup_failure=False):
    source, obj, image = (root / f"fixture-{suffix}{ext}" for ext in (".S", ".o", ".bin"))
    source.write_text(transport.fixture(steps).replace("HUNTMOB_ANS_UNWRAPPED_XTS_PASS", MARKER))
    for argv in ([clang, "--target=aarch64-none-elf", "-c", str(source), "-o", str(obj)],
                 [objcopy, "-O", "binary", str(obj), str(image)]):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=25)
        require(result.returncode == 0, "fixture compilation failed: " + result.stderr[-600:])
    controller = "nvme,serial=HuntMobFixture,addr=1,id=testnvme,is-apple-ans=on"
    extra = []
    if enabled:
        controller += f",{PROPERTY}=on"
    if context is not None:
        secret = root / f"public-context-{suffix}.bin"
        # Never accept user key inputs or place key bytes in argv/logs.
        secret.write_bytes(context)
        os.chmod(secret, 0o600)
        extra.extend(["-object", f"secret,id=public-context,file={secret},format=raw"])
        controller += f",{CONTEXT_PROPERTY}=public-context"
    if trace:
        extra.extend(["-trace", "enable=pci_nvme_apple_ans_complete"])
    command = [
        str(engine), "-M", "virt,highmem=off", "-cpu", "max", "-accel", "tcg", "-m", "64",
        "-display", "none", "-serial", "none", "-monitor", "none", "-nic", "none",
        "-kernel", str(image), "-semihosting-config", "enable=on,target=native",
        "-drive", f"file={disk},format=raw,if=none,id=testdisk", "-device", controller,
        "-device", "nvme-ns,drive=testdisk,bus=testnvme,nsid=1,logical_block_size=4096,physical_block_size=4096",
    ] + extra
    result = subprocess.run(command, capture_output=True, text=True, timeout=25)
    output = result.stdout + result.stderr
    if expect_startup_failure:
        require(result.returncode != 0 and "STEP_" not in output and MARKER not in output,
                "invalid context was not rejected before guest execution")
        return {"configuration_rejected_at_startup": True, "guest_executed": False}
    require(result.returncode == 0 and MARKER in output,
            "actual-controller validation failed: " + output[-1400:])
    for index, row in enumerate(steps):
        require(f"STEP_{index}_{row['name']}_OK" in output, "missing guest validation receipt")
    return {"configuration_rejected_at_startup": False, "guest_executed": True}


def exercise(engine, name, enabled, context, accepted, clang, objcopy, ciphertext, blob,
             trace=False, startup_failure=False):
    with tempfile.TemporaryDirectory(prefix="huntmob-ans-wrapped-public-") as td:
        root = Path(td)
        disk = root / "synthetic.raw"
        disk.write_bytes(bytes(DISK_BYTES))
        steps = records(accepted, blob, ciphertext)
        outcome = run_guest(engine, root, disk, steps, "initial", enabled, context, clang, objcopy,
                            trace, startup_failure)
        expected = bytearray(DISK_BYTES)
        if not startup_failure:
            expected[:4096] = transport.CLEAR
            if accepted:
                expected[transport.LBA * 4096:(transport.LBA + 2) * 4096] = ciphertext
        stored = disk.read_bytes()
        require(stored == expected, "complete temporary backing differs from independent oracle")
        restart_count = 0
        if accepted:
            require(transport.PLAINTEXT not in stored, "synthetic plaintext leaked into backing")
            restarted = records(True, blob, ciphertext, restart=True)
            run_guest(engine, root, disk, restarted, "restart", enabled, context, clang, objcopy, trace)
            restart_count = len(restarted)
            require(disk.read_bytes() == stored, "read-only fresh process changed temporary backing")
        return {
            "name": name, **outcome, "property_omitted_default_off": not enabled,
            "synthetic_context_bytes": None if context is None else len(context),
            "protected_io_accepted": accepted, "two_units": accepted,
            "ciphertext_matches_independent_oracle": accepted,
            "fresh_process_read_verified": accepted, "fresh_process_backing_unchanged": accepted,
            "synthetic_context_explicitly_resupplied_after_restart": accepted,
            "completed_requests": 0 if startup_failure else len(steps),
            "restart_requests": restart_count,
            "rejected_requests": [] if startup_failure else [r["name"] for r in steps if r.get("rejection")],
            "rejection_dma_unchanged_and_backing_verified_each_time": not startup_failure,
            "backing_sha256": hashlib.sha256(stored).hexdigest(),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--authorized-lab", action="store_true", required=True)
    parser.add_argument("--trace-diagnostics", action="store_true")
    parser.add_argument("--clang", default=shutil.which("clang") or "clang")
    parser.add_argument("--objcopy", default=shutil.which("llvm-objcopy") or "/opt/homebrew/opt/llvm/bin/llvm-objcopy")
    args = parser.parse_args()
    engine = args.engine.resolve(strict=True)
    engine_hash = hashlib.sha256(engine.read_bytes()).hexdigest()
    blob, ciphertext = envelope(), oracle()
    # A wrong wrapping key with the CORRECT auth key is not an expected MAC
    # failure: this envelope has no demonstrated binding of those two keys.
    scenarios = [
        ("default_off", False, None, False, False),
        ("enabled_correct_context", True, PUBLIC_CONTEXT, True, False),
        ("enabled_missing_context", True, None, False, False),
        ("enabled_wrong_auth_context", True, WRAP_KEY + bytes(reversed(AUTH_KEY)), False, False),
        ("enabled_wrong_context_pair", True, bytes(reversed(PUBLIC_CONTEXT)), False, False),
        ("invalid_context_length_63", True, PUBLIC_CONTEXT[:-1], False, False),
        ("invalid_context_length_65", True, PUBLIC_CONTEXT + b"\x00", False, False),
    ]
    reports = [exercise(engine, name, enabled, context, accepted, args.clang, args.objcopy,
                        ciphertext, blob, args.trace_diagnostics, startup_failure)
               for name, enabled, context, accepted, startup_failure in scenarios]
    require(hashlib.sha256(engine.read_bytes()).hexdigest() == engine_hash,
            "engine changed during validation; refuse to attribute results")
    print(json.dumps({
        "schema": "huntmob.ans-wrapped-public-fixture.v1", "ok": True, "ready": False,
        "scope": "script-created ARM64 virt; temporary 16 MiB disk; public synthetic context only",
        "engine_sha256": engine_hash, "reports": reports,
        "completed_requests": sum(r["completed_requests"] + r["restart_requests"] for r in reports),
        "envelope_bytes": len(blob), "envelope_sha256": hashlib.sha256(blob).hexdigest(),
        "oracle": "independent Python cryptography AES-256-CBC/CBC-MAC and AES-128-XTS",
        "xts_unit_bytes": 4096, "file_unit_differs_from_lba": transport.FILE_UNIT != transport.LBA,
        "variable_envelope_length_testable_in_fixed_descriptor": False,
        "guest_abi_validated": False, "hardware_context_source_validated": False,
        "sep_to_ans_key_transfer_validated": False, "data_protection_validated": False,
        "actual_sep_still_blocked": True,
        "wrapping_key_only_mismatch_authentication_detection": False,
    }, indent=2))


if __name__ == "__main__":
    main()
