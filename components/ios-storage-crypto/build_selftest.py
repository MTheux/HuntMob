#!/usr/bin/env python3
"""Compile public synthetic tests against the already-built QEMU cipher object.

Never executes firmware, opens a backing, or changes the emulator build.
"""
import argparse
import hashlib
import json
import platform
import shlex
import subprocess
from pathlib import Path


def digest(path):
    original = path.stat()
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    final = path.stat()
    if (original.st_size, original.st_mtime_ns, original.st_ctime_ns) != (
        final.st_size, final.st_mtime_ns, final.st_ctime_ns
    ):
        raise ValueError('Build input changed during hashing')
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-synthetic-selftest', action='store_true', required=True)
    parser.add_argument('--qemu-root', type=Path, default=Path.home() / '.huntmob/research/Inferno')
    args = parser.parse_args()
    own = Path(__file__).resolve().parent
    project = own.parent.parent
    engine = args.qemu_root.resolve(strict=True)
    build = engine / 'build-huntmob'
    cipher = build / 'libcrypto.a.p/crypto_cipher.c.o'
    util = build / 'libqemuutil.a'
    sources = [own / 'xts_reference.c', own / 'xts_reference.h', own / 'selftest.c']
    sources += [own / 'build_selftest.py']
    files = sources + [cipher, util, build / 'config-host.h']
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Regular local build inputs required')
    hashes = {str(path.relative_to(own) if path in sources else path.relative_to(engine)): digest(path)
              for path in files}
    output = project / 'build/ios-storage-crypto'
    if output.is_symlink() or (output.parent.exists() and output.parent.is_symlink()):
        raise ValueError('Exclusive regular output directory required')
    output.mkdir(parents=True, exist_ok=True)
    binary = output / 'selftest'
    receipt = output / 'receipt.json'
    if binary.is_symlink() or receipt.is_symlink():
        raise ValueError('Refusing symlink output')
    host = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64',
            'AMD64': 'x86_64'}.get(platform.machine())
    if not host:
        raise ValueError('Unsupported local reference-build architecture')
    pkg = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'nettle', 'glib-2.0'],
                                  text=True, timeout=10)
    command = ['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-I' + str(build), '-I' + str(engine), '-I' + str(engine / 'include'),
               '-I' + str(engine / 'host/include' / host),
               '-I' + str(engine / 'host/include/generic'), '-I' + str(own),
               str(sources[0]), str(sources[2]), str(cipher), str(util),
               *shlex.split(pkg), '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    result = subprocess.run([str(binary), '--authorized-synthetic-selftest'],
                            check=True, capture_output=True, text=True, timeout=10)
    for path in files:
        name = str(path.relative_to(own) if path in sources else path.relative_to(engine))
        if digest(path) != hashes[name]:
            raise ValueError('Build input changed during compilation')
    report = json.loads(result.stdout)
    report['source_hashes'] = hashes
    report['binary_sha256'] = digest(binary)
    report['standard_kat_source'] = (
        'https://github.com/openssl/openssl/blob/master/test/recipes/'
        '30-test_evp_data/evpciph_aes_common.txt'
    )
    report['synthetic_independent_reference'] = 'cryptography 44.0.3 AES-XTS, two separate 4096-byte units'
    report['scope'] = 'public-standard-and-synthetic-only'
    report['controller_connected'] = False
    report['expanded_qcrypto_context_erasure_validated'] = False
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'state': 'reference-test-failed',
                          'reason': type(error).__name__}))
        raise SystemExit(1)
