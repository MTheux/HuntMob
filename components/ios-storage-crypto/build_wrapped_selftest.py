#!/usr/bin/env python3
"""Build the C envelope codec against the isolated patched QCrypto backend.

Only generated public fixture constants are used. No firmware or backing is run.
"""
import argparse
import hashlib
import json
import platform
import re
import shlex
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def digest(path):
    before = path.stat()
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError('Build input changed during hashing')
    return value


def encrypt(key, data):
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return cipher.update(data) + cipher.finalize()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-synthetic-selftest', action='store_true', required=True)
    parser.add_argument('--candidate-root', type=Path, default=(
        Path.home() / '.huntmob/research/ios-engine-diagnostics-20261014'))
    args = parser.parse_args()
    own = Path(__file__).resolve().parent
    project = own.parent.parent
    candidate = args.candidate_root.resolve(strict=True)
    engine = candidate / 'source'
    build = candidate / 'build'
    cipher = build / 'libcrypto.a.p/crypto_cipher.c.o'
    util = build / 'libqemuutil.a'
    nettle_source = engine / 'crypto/cipher-nettle.c.inc'
    if 'qcrypto_nettle_ctx_wipe(ctx, sizeof(*ctx))' not in nettle_source.read_text():
        raise ValueError('Expanded Nettle context erasure patch is required')
    if not re.search(r'^#define CONFIG_NETTLE(?:\s+1)?\s*$',
                     (build / 'config-host.h').read_text(), re.MULTILINE):
        raise ValueError('This test is limited to the reviewed Nettle backend')
    sources = [own / name for name in ('wrapped_reference.c', 'wrapped_reference.h',
                                       'wrapped_selftest.c', 'build_wrapped_selftest.py')]
    files = sources + [cipher, util, nettle_source, build / 'config-host.h']
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Regular local build inputs required')
    hashes = {str(path): digest(path) for path in files}
    output = project / 'build/ios-wrapped-reference-v2'
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError('Regular output directory required')
    # A new version never overwrites the preceding fixture/binary/receipt.
    output.mkdir(parents=True, exist_ok=False)
    binary, receipt, fixture = [output / name for name in
                                ('selftest', 'receipt.json', 'wrapped_fixture.h')]
    if any(path.is_symlink() for path in (binary, receipt, fixture)):
        raise ValueError('Refusing symlink outputs')
    raw, wrap_key, auth_key = [bytes(range(start, start + 32)) for start in (0, 32, 64)]
    ciphertext = encrypt(wrap_key, raw)
    def envelope(word):
        flags = word.to_bytes(4, 'little')
        tag = encrypt(auth_key, ciphertext + bytes(12) + flags)[-16:]
        return flags + bytes(12) + tag + ciphertext

    blob, native_blob = envelope(0x1B140), envelope(0x1B040)
    unknown_flags = (0, 0x1B141, 0x1B041, 0x1B240, 0x1B940, 0xFFFFFFFF)
    unknown_blobs = [envelope(word) for word in unknown_flags]
    fixture.write_text('/* Generated PUBLIC synthetic constants only. */\n' + '\n'.join(
        'static const uint8_t fixture_' + name + '[] = {' +
        ','.join(f'0x{byte:02x}' for byte in value) + '};'
        for name, value in (('raw', raw), ('wrap_key', wrap_key),
                            ('auth_key', auth_key), ('expected_blob', blob),
                            ('expected_native_blob', native_blob))) + '\n' +
        'static const uint32_t fixture_unknown_flags[] = {' +
        ','.join(hex(word) for word in unknown_flags) + '};\n' +
        'static const uint8_t fixture_unknown_blobs[][64] = {' +
        ','.join('{' + ','.join(f'0x{byte:02x}' for byte in value) + '}'
                 for value in unknown_blobs) + '};\n')
    host = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64',
            'AMD64': 'x86_64'}.get(platform.machine())
    if not host:
        raise ValueError('Unsupported local architecture')
    pkg = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'nettle', 'glib-2.0'],
                                  text=True, timeout=10)
    command = ['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-I' + str(build), '-I' + str(engine), '-I' + str(engine / 'include'),
               '-I' + str(engine / 'host/include' / host),
               '-I' + str(engine / 'host/include/generic'), '-I' + str(own),
               '-I' + str(output), str(sources[0]), str(sources[2]), str(cipher),
               str(util), *shlex.split(pkg), '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    result = subprocess.run([str(binary), '--authorized-synthetic-selftest'],
                            check=True, capture_output=True, text=True, timeout=10)
    if any(digest(path) != hashes[str(path)] for path in files):
        raise ValueError('Build input changed during compilation')
    report = json.loads(result.stdout)
    report.update(schema='huntmob.ios-wrapped-reference.c.v2', date='2026-10-15',
                  scope='public synthetic fixture, current virtual model framing only',
                  source_hashes=hashes, binary_sha256=digest(binary),
                  synthetic_envelope_sha256=hashlib.sha256(blob).hexdigest(),
                  synthetic_native_envelope_sha256=hashlib.sha256(native_blob).hexdigest(),
                  exact_flags_allowlist=[0x1B040, 0x1B140],
                  valid_MAC_unsupported_flags=list(unknown_flags),
                  compiler_command=command,
                  independent_oracle='Python cryptography AES256-CBC',
                  nettle_context_erasure_source_required=True,
                  context_erasure_runtime_instrumented=False,
                  controller_connected=False, firmware_executed=False)
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'state': 'wrapped-reference-test-failed',
                          'reason': type(error).__name__}))
        raise SystemExit(1)
