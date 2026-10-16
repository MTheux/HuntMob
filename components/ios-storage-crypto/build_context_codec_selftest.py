#!/usr/bin/env python3
"""Deterministic native composition of lifecycle and real QCrypto frame codec.

Uses public synthetic constants only. "Backing" and "DMA" are memory sentinels.
No device, backing image, firmware, VM or controller is opened or executed.
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
    candidate = args.candidate_root.resolve(strict=True)
    engine, build = candidate / 'source', candidate / 'build'
    names = ('ans_context_lifecycle.c', 'ans_context_lifecycle.h', 'wrapped_reference.c',
             'wrapped_reference.h', 'context_codec_selftest.c', 'build_context_codec_selftest.py')
    sources = [own / name for name in names]
    cipher, util = build / 'libcrypto.a.p/crypto_cipher.c.o', build / 'libqemuutil.a'
    nettle = engine / 'crypto/cipher-nettle.c.inc'
    config = build / 'config-host.h'
    if 'qcrypto_nettle_ctx_wipe(ctx, sizeof(*ctx))' not in nettle.read_text():
        raise ValueError('Expanded Nettle context erasure patch is required')
    if not re.search(r'^#define CONFIG_NETTLE(?:\s+1)?\s*$', config.read_text(), re.MULTILINE):
        raise ValueError('Only the reviewed Nettle backend is supported')
    files = sources + [cipher, util, nettle, config]
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Regular local build inputs required')
    hashes = {str(path): digest(path) for path in files}
    output = own.parent.parent / 'build/ios-ans-context-codec'
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError('Regular output directory required')
    output.mkdir(parents=True, exist_ok=True)
    binary, receipt, fixture = [output / name for name in
                                ('selftest', 'receipt.json', 'context_codec_fixture.h')]
    if any(path.is_symlink() for path in (binary, receipt, fixture)):
        raise ValueError('Refusing symlink outputs')
    values = {}
    flags = (0x1B140).to_bytes(4, 'little')
    for suffix, raw_start, wrap_start, auth_start in (('a', 0, 32, 64), ('b', 160, 96, 128)):
        raw, wrap, auth = [bytes(range(start, start + 32)) for start in
                           (raw_start, wrap_start, auth_start)]
        encrypted = encrypt(wrap, raw)
        tag = encrypt(auth, encrypted + bytes(12) + flags)[-16:]
        values.update({f'raw_{suffix}': raw, f'wrap_{suffix}': wrap,
                       f'auth_{suffix}': auth, f'blob_{suffix}': flags + bytes(12) + tag + encrypted})
    fixture.write_text('/* Generated PUBLIC synthetic constants only. */\n' + '\n'.join(
        'static const uint8_t fixture_' + name + '[] = {' +
        ','.join(f'0x{byte:02x}' for byte in value) + '};'
        for name, value in values.items()) + '\n')
    host = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64',
            'AMD64': 'x86_64'}.get(platform.machine())
    if not host:
        raise ValueError('Unsupported local architecture')
    pkg = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'nettle', 'glib-2.0'],
                                  text=True, timeout=10)
    command = ['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-pthread', '-I' + str(build), '-I' + str(engine),
               '-I' + str(engine / 'include'), '-I' + str(engine / 'host/include' / host),
               '-I' + str(engine / 'host/include/generic'), '-I' + str(own),
               '-I' + str(output), str(sources[0]), str(sources[2]), str(sources[4]),
               str(cipher), str(util), *shlex.split(pkg), '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    result = subprocess.run([str(binary), '--authorized-synthetic-selftest'],
                            check=True, capture_output=True, text=True, timeout=10)
    if any(digest(path) != hashes[str(path)] for path in files):
        raise ValueError('Build input changed during compilation')
    report = json.loads(result.stdout)
    report.update(schema='huntmob.ans-context-codec.native.v1', date='2026-10-15',
                  scope='standalone deterministic public-fixture composition',
                  source_hashes=hashes, binary_sha256=digest(binary),
                  fixture_sha256=digest(fixture),
                  independent_oracle='Python cryptography AES256-CBC; two distinct pairs',
                  expanded_context_erasure_source_required=True,
                  expanded_context_erasure_runtime_instrumented=False,
                  firmware_executed=False, device_io=False, disk_backing_opened=False,
                  sentinel_scope='local byte arrays, not a physical disk or DMA engine',
                  callbacks='bounded copies only; allocation, wait, drain and reentry prohibited',
                  codec_execution='outside lifecycle mutex; temporary context copied under lock',
                  actual_aio_drain_validated=False,
                  revocation_does_not_undo_submitted_writes=True)
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'state': 'context-codec-test-failed',
                          'reason': type(error).__name__}))
        raise SystemExit(1)
