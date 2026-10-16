#!/usr/bin/env python3
"""Compare pinned and patched Nettle lifecycles in exclusive synthetic processes.

Compile the real QCrypto backend with allocator hooks in that translation unit
only. Inspect each still-live allocation before free; never inspect freed memory.
No firmware, keybag, guest, backing or private key input is accepted.
"""
import argparse
import hashlib
import json
import platform
import shlex
import subprocess
import tempfile
from pathlib import Path

REVISION = 'cc4302a99167abec69b714cfd00c38caece7e7de'


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Regular local build inputs required.')
    before = path.stat()
    result = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        before.st_ctime_ns) != (after.st_dev, after.st_ino, after.st_size,
                               after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('Build input changed while hashing.')
    return result


def run(command, cwd=None):
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True,
                          text=True, timeout=60)


def verify(candidate, output):
    own = Path(__file__).resolve().parent
    project = own.parents[1]
    candidate = Path(candidate).resolve(strict=True)
    source, build = candidate / 'source', candidate / 'build'
    patch = project / 'components/ios-engine/crypto-nettle-context-erasure.patch'
    output = Path(output).absolute()
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    config = (build / 'config-host.h').read_text()
    if '#define CONFIG_NETTLE' not in config or '#define CONFIG_AF_ALG' in config:
        raise ValueError('This test requires the configured Nettle backend without AF_ALG.')
    host = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64'}.get(platform.machine())
    if not host:
        raise ValueError('Unsupported local build architecture.')
    relative = ('crypto/cipher.c', 'crypto/cipher-nettle.c.inc', 'crypto/cipherpriv.h')
    pinned = {name: run(['git', 'show', f'{REVISION}:{name}'], source).stdout
              for name in relative}
    for name in ('crypto/cipher.c', 'crypto/cipherpriv.h'):
        if (source / name).read_text() != pinned[name]:
            raise ValueError('Cipher interfaces differ from the reviewed pinned source.')
    inputs = [source / name for name in relative]
    inputs += [build / 'config-host.h', build / 'libqemuutil.a', patch,
               own / 'context_erasure_allocator.h', own / 'context_erasure_selftest.c',
               Path(__file__).resolve()]
    hashes = {str(path): digest(path) for path in inputs}
    package_flags = shlex.split(run(['pkg-config', '--cflags', '--libs', 'nettle', 'glib-2.0']).stdout)
    compile_flags = shlex.split(run(['pkg-config', '--cflags', 'nettle', 'glib-2.0']).stdout)
    includes = [f'-I{path}' for path in (build, source, source / 'include',
                source / 'host/include' / host, source / 'host/include/generic', own)]
    reports = {}
    for label in ('baseline', 'patched'):
        tree = output / label
        (tree / 'crypto').mkdir(parents=True, mode=0o700)
        for name, content in pinned.items():
            (tree / name).write_text(content)
        if label == 'patched':
            run(['git', 'apply', '--check', str(patch)], tree)
            run(['git', 'apply', str(patch)], tree)
            allowed_current = (pinned['crypto/cipher-nettle.c.inc'],
                               (tree / 'crypto/cipher-nettle.c.inc').read_text())
            if (source / 'crypto/cipher-nettle.c.inc').read_text() not in allowed_current:
                raise ValueError('Current backend contains an unreviewed cipher change.')
        backend = tree / 'cipher.o'
        run(['cc', '-std=gnu11', '-O2', '-Wall', '-Werror', *includes,
             '-include', str(own / 'context_erasure_allocator.h'),
             '-c', str(tree / 'crypto/cipher.c'), *compile_flags, '-o', str(backend)])
        binary = tree / 'context-erasure-selftest'
        run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', *includes,
             str(own / 'context_erasure_selftest.c'), str(backend),
             str(build / 'libqemuutil.a'), *package_flags, '-o', str(binary)])
        reports[label] = json.loads(run([str(binary), '--authorized-synthetic-selftest']).stdout)
        reports[label]['binary_sha256'] = digest(binary)
        reports[label]['backend_object_sha256'] = digest(backend)
    for path in inputs:
        if digest(path) != hashes[str(path)]:
            raise ValueError('Input changed during compilation or execution.')
    baseline, patched = reports['baseline'], reports['patched']
    expected_pairs = 46 if '#define CONFIG_CRYPTO_SM4' in config else 45
    valid = (baseline['algorithm_mode_pairs'] == patched['algorithm_mode_pairs'] == expected_pairs
             and baseline['ciphertext_matrix_sha256'] == patched['ciphertext_matrix_sha256']
             and baseline['zero_before_release'] == 0
             and patched['all_contexts_wiped']
             and patched['allocations'] == patched['releases'] == expected_pairs * 3
             and baseline['tracking_errors'] == patched['tracking_errors'] == 0)
    result = {'version': 1, 'scope': 'public-synthetic-context-lifecycle-only',
              'engine_revision': REVISION, 'patch_sha256': hashes[str(patch)],
              'source_hashes': hashes, 'runs': reports,
              'expanded_nettle_context_erasure_validated': bool(valid),
              'guest_abi_validated': False, 'wrapped_key_support': False, 'ready': False}
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n')
    if not valid:
        raise ValueError('Lifecycle or baseline parity validation failed.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-synthetic-selftest', action='store_true', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.candidate, args.output)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'state': 'failed', 'ready': False, 'failure_type': type(error).__name__}))
        raise SystemExit(1)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
