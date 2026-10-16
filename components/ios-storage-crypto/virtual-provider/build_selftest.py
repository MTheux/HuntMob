#!/usr/bin/env python3
"""Test VirtualSEP v1 native HMAC/AES with public independently derived fixtures.

Only QCryptoSecret lookup is a public fixture mock. No engine, host keychain,
real root, guest, firmware, network or backing image is accessed by the test.
"""
import argparse
import hashlib
import hmac
import json
import platform
import re
import shlex
import subprocess
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes as crypto_hashes, hmac as crypto_hmac

HMAC_SOURCE_STATES = {
    'e1d0ca55e1a87938f26147d14987a513978153279c01880fd343088311a78f5d': 'baseline',
    '36157cdb40beaf8500f1f3fac1a4c1228790e8654548dae7411f0193c4899ac8': 'erasure-only',
    '4d457a1d752d439ae81be670bdb3ba73901ee4cacf6b7a7a708399489ecb9201': 'erasure-and-nettle4',
}
FINAL_HMAC_SHA256 = '4d457a1d752d439ae81be670bdb3ba73901ee4cacf6b7a7a708399489ecb9201'


def digest(path):
    before = path.stat()
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError('Build input changed during hashing')
    return value


def kdf(root, label, context):
    message = (1).to_bytes(4, 'big') + label.encode('ascii') + b'\0'
    message += context + (256).to_bytes(4, 'big')
    return hmac.new(root, message, hashlib.sha256).digest()


def encrypt(key, data):
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    return cipher.update(data) + cipher.finalize()


def blob(root, vm_id, context, raw):
    wrapping = kdf(root, 'HuntMob.VirtualSEP.v1/inline-wrap', vm_id + b'\0' + context)
    authentication = kdf(root, 'HuntMob.VirtualSEP.v1/inline-auth', vm_id + b'\0' + context)
    encrypted = encrypt(wrapping, raw)
    flags = (0x1B140).to_bytes(4, 'little')
    tag = encrypt(authentication, encrypted + bytes(12) + flags)[-16:]
    return flags + bytes(12) + tag + encrypted


def uid(root, vm_id, raw, index, count):
    key = kdf(root, f'HuntMob.VirtualSEP.v1/UID{index}',
              vm_id + (0x11223344).to_bytes(4, 'big'))
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).encryptor()
    result = raw
    for _ in range(max(count, 1)):
        result = cipher.update(result)
    cipher.finalize()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-synthetic-selftest', action='store_true', required=True)
    parser.add_argument('--candidate-root', type=Path, default=(
        Path.home() / '.huntmob/research/ios-engine-diagnostics-20261014'))
    args = parser.parse_args()
    own = Path(__file__).resolve().parent
    candidate = args.candidate_root.resolve(strict=True)
    engine, build = candidate / 'source', candidate / 'build'
    cipher = build / 'libcrypto.a.p/crypto_cipher.c.o'
    hmac_core = build / 'libcrypto.a.p/crypto_hmac.c.o'
    util = build / 'libqemuutil.a'
    nettle_hmac = engine / 'crypto/hmac-nettle.c'
    nettle_cipher = engine / 'crypto/cipher-nettle.c.inc'
    config = build / 'config-host.h'
    if 'qcrypto_nettle_ctx_wipe(ctx, sizeof(*ctx))' not in nettle_cipher.read_text():
        raise ValueError('Expanded Nettle cipher erasure patch required')
    if not re.search(r'^#define CONFIG_NETTLE(?:\s+1)?\s*$', config.read_text(), re.MULTILINE):
        raise ValueError('Only the reviewed Nettle backend is supported')
    sources = [own / name for name in ('crypto/huntmob-virtual-sep.c',
               'include/crypto/huntmob-virtual-sep.h', 'selftest.c', 'build_selftest.py',
               'kdf-contract-v1.json')]
    codec = own.parent / 'wrapped_reference.c'
    codec_header = own.parent / 'wrapped_reference.h'
    compat_patch = own.parent.parent / 'ios-engine/huntmob-virtual-sep-nettle4-hmac.patch'
    files = sources + [cipher, hmac_core, util, nettle_hmac, nettle_cipher, config,
                       codec, codec_header, compat_patch]
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Regular local build inputs required')
    hashes = {str(path): digest(path) for path in files}
    hmac_source_state = HMAC_SOURCE_STATES.get(hashes[str(nettle_hmac)])
    if hmac_source_state is None:
        raise ValueError('Nettle HMAC source is not one of the reviewed immutable inputs')
    output = own.parent.parent.parent / 'build/ios-virtual-sep-provider'
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError('Regular output directory required')
    output.mkdir(parents=True, exist_ok=True)
    binary, receipt, fixture, patched_hmac = [output / name for name in
        ('selftest', 'receipt.json', 'provider_fixture.h', 'hmac-nettle-erased.c')]
    if any(path.is_symlink() for path in (binary, receipt, fixture, patched_hmac)):
        raise ValueError('Refusing symlink outputs')
    # Build exactly the independently reviewed HMAC erasure delta into the
    # private test, without mutating the shared candidate or its objects.
    hmac_source = nettle_hmac.read_text()
    old = '    ctx = hmac->opaque;\n    g_free(ctx);'
    new = '''    ctx = hmac->opaque;
    /* Erase complete keyed inner/outer hash states before allocator release. */
    if (ctx) {
        volatile uint8_t *bytes = (volatile uint8_t *)ctx;
        size_t length = sizeof(*ctx);
        while (length--) {
            *bytes++ = 0;
        }
    }
    g_free(ctx);'''
    if old in hmac_source:
        if hmac_source.count(old) != 1:
            raise ValueError('Unexpected Nettle HMAC destructor contract')
        hmac_source = hmac_source.replace(old, new)
    elif new not in hmac_source:
        raise ValueError('Unreviewed Nettle HMAC erasure implementation')
    patched_hmac.write_text(hmac_source)
    if 'qcrypto_compat_hmac_sha256_digest' not in hmac_source:
        isolated = output / 'hmac-source'
        if isolated.is_symlink():
            raise ValueError('Regular private HMAC build directory required')
        (isolated / 'crypto').mkdir(parents=True, exist_ok=True)
        isolated_source = isolated / 'crypto/hmac-nettle.c'
        if isolated_source.is_symlink():
            raise ValueError('Refusing symlink HMAC source')
        isolated_source.write_text(hmac_source)
        subprocess.run(['git', 'apply', '--unsafe-paths', '--directory=' + str(isolated),
                        str(compat_patch)], check=True, capture_output=True, timeout=10)
        patched_hmac.write_text(isolated_source.read_text())
    if digest(patched_hmac) != FINAL_HMAC_SHA256:
        raise ValueError('Private HMAC build source does not match the reviewed final patch')
    root_a, root_b = bytes(range(32)), bytes(range(32, 64))
    vm_id, other_vm_id, context = bytes(range(16, 32)), bytes(range(32, 48)), bytes(range(48, 76))
    raw = bytes(range(80, 112))
    values = {'root_a': root_a, 'root_b': root_b, 'vm_id': vm_id, 'other_vm_id': other_vm_id,
              'context': context, 'raw': raw, 'blob_a': blob(root_a, vm_id, context, raw),
              'blob_b': blob(root_b, vm_id, context, raw),
              'other_vm_blob': blob(root_a, other_vm_id, context, raw),
              'uid0_count1': uid(root_a, vm_id, raw, 0, 1),
              'uid0_count2': uid(root_a, vm_id, raw, 0, 2),
              'uid1_count1': uid(root_a, vm_id, raw, 1, 1)}
    for algorithm in ('md5', 'sha1', 'sha224', 'sha256', 'sha384', 'sha512',
                      'ripemd160', 'sm3'):
        if algorithm == 'sm3':
            mac = crypto_hmac.HMAC(root_a, crypto_hashes.SM3())
            mac.update(context)
            values['hmac_' + algorithm] = mac.finalize()
        else:
            values['hmac_' + algorithm] = hmac.new(root_a, context, algorithm).digest()
    fixture.write_text('/* PUBLIC deterministic fixture only. */\n' + '\n'.join(
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
               '-Wno-unused-parameter', '-pthread', '-I' + str(build),
               '-I' + str(own / 'include'), '-I' + str(engine), '-I' + str(engine / 'include'),
               '-I' + str(engine / 'crypto'), '-I' + str(engine / 'host/include' / host),
               '-I' + str(engine / 'host/include/generic'), '-I' + str(own.parent),
               '-I' + str(output), str(sources[0]), str(sources[2]), str(codec),
               str(patched_hmac), str(cipher), str(hmac_core), str(util),
               *shlex.split(pkg), '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    result = subprocess.run([str(binary), '--authorized-synthetic-selftest'],
                            check=True, capture_output=True, text=True, timeout=15)
    if any(digest(path) != hashes[str(path)] for path in files):
        raise ValueError('Build input changed during compilation')
    report = json.loads(result.stdout)
    report.update(schema='huntmob.virtual-sep-provider.native.v1', date='2026-10-15',
                  scope='own virtual identity provider, public roots only',
                  source_hashes=hashes, binary_sha256=digest(binary),
                  fixture_sha256=digest(fixture), patched_hmac_sha256=digest(patched_hmac),
                  hmac_candidate_source_state=hmac_source_state,
                  kdf_contract_sha256=digest(own / 'kdf-contract-v1.json'),
                  independent_oracle='Python hmac/hashlib SP800-108 + cryptography AES256-CBC',
                  secret_lookup='public-fixture mock; actual QOM/keychain root loading unvalidated',
                  key_bytes_in_receipt=False, firmware_executed=False, device_io=False,
                  at_rest_validated=False, cold_boot_persistence_validated=False,
                  root_keychain_provisioned=False, erasure_runtime_instrumented=False)
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'state': 'virtual-provider-test-failed',
                          'reason': type(error).__name__}))
        raise SystemExit(1)
