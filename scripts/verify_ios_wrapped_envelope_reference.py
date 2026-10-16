#!/usr/bin/env python3
"""Offline public-fixture reference for the traced virtual SEP envelope.

This proves the composition of the *current Inferno model* and the pinned
AESSEP firmware call sequence. It does not validate Apple key derivation,
physical hardware, key-slot transfer, APFS, or native iOS readiness.
No input files, key arguments, guest memory, devices, or networks are used.
"""

import argparse
import hashlib
import hmac
import json
import struct

from Crypto.Cipher import AES
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def reference_wrap(raw: bytes, wrap_key: bytes, auth_key: bytes, flags: int) -> bytes:
    """Model 206 -> 8 -> 88 using a single equivalent CBC-MAC message."""
    if any(len(value) != 32 for value in (raw, wrap_key, auth_key)):
        raise ValueError("Only 32-byte public fixture keys are supported")
    if not 0 <= flags <= 0xFFFFFFFF:
        raise ValueError("Flags must fit in uint32")
    cipher = Cipher(algorithms.AES(wrap_key), modes.CBC(bytes(16))).encryptor()
    encrypted = cipher.update(raw) + cipher.finalize()
    metadata = bytes(12) + struct.pack("<I", flags)
    cipher = Cipher(algorithms.AES(auth_key), modes.CBC(bytes(16))).encryptor()
    mac = cipher.update(encrypted + metadata) + cipher.finalize()
    return struct.pack("<I", flags) + bytes(12) + mac[-16:] + encrypted


def independent_wrap(raw: bytes, wrap_key: bytes, auth_key: bytes, flags: int) -> bytes:
    """PyCryptodome follows the three separately started MMIO operations."""
    encrypted = AES.new(wrap_key, AES.MODE_CBC, iv=bytes(16)).encrypt(raw)
    intermediate = AES.new(auth_key, AES.MODE_CBC, iv=bytes(16)).encrypt(encrypted)
    final = AES.new(auth_key, AES.MODE_CBC, iv=intermediate[-16:]).encrypt(
        bytes(12) + struct.pack("<I", flags)
    )
    return struct.pack("<I", flags) + bytes(12) + final + encrypted


def reference_unwrap(blob: bytes, wrap_key: bytes, auth_key: bytes) -> bytes:
    """Authenticate the exact framing before producing any plaintext."""
    if len(blob) != 64 or any(len(key) != 32 for key in (wrap_key, auth_key)):
        raise ValueError("Unsupported envelope or key length")
    if blob[4:16] != bytes(12):
        raise ValueError("Reserved metadata must be zero")
    cipher = Cipher(algorithms.AES(auth_key), modes.CBC(bytes(16))).encryptor()
    mac = cipher.update(blob[32:64] + bytes(12) + blob[:4]) + cipher.finalize()
    if not hmac.compare_digest(mac[-16:], blob[16:32]):
        raise ValueError("Envelope authentication failed")
    cipher = Cipher(algorithms.AES(wrap_key), modes.CBC(bytes(16))).decryptor()
    return cipher.update(blob[32:64]) + cipher.finalize()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized-lab", action="store_true", required=True,
                        help="Acknowledge the offline public-fixture-only scope")
    parser.parse_args()
    # Published deterministic synthetic inputs; these are not device secrets.
    raw = bytes(range(32))
    wrap_key = bytes(range(32, 64))
    auth_key = bytes(range(64, 96))
    flags = 0x1B140  # Traced SKG default request; no wider flag ABI is implied.
    blob = reference_wrap(raw, wrap_key, auth_key, flags)
    assert independent_wrap(raw, wrap_key, auth_key, flags) == blob
    assert reference_unwrap(blob, wrap_key, auth_key) == raw
    rejected = 0
    for index in range(64):
        changed = bytearray(blob)
        changed[index] ^= 1
        try:
            reference_unwrap(bytes(changed), wrap_key, auth_key)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError(f"Tampered envelope accepted at byte {index}")
    for changed_key in (bytes(32), bytes(reversed(auth_key))):
        try:
            reference_unwrap(blob, wrap_key, changed_key)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError("Wrong authentication key accepted")
    print(json.dumps({
        "schema": "huntmob.ios-envelope-reference.v1",
        "date": "2026-10-15",
        "scope": "public synthetic fixture only",
        "equivalent_independent_implementations": 2,
        "roundtrip_passed": True,
        "rejected_tamper_and_wrong_key_cases": rejected,
        "synthetic_envelope_sha256": hashlib.sha256(blob).hexdigest(),
        "hardware_key_derivation_validated": False,
        "sep_to_ans_key_transfer_validated": False,
        "real_firmware_roundtrip_validated": False,
        "native_ios_ready": False,
    }, indent=2))


if __name__ == "__main__":
    main()
