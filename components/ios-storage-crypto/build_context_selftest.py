#!/usr/bin/env python3
"""Build native synthetic lifecycle checks without executing a VM or firmware."""
import argparse
import hashlib
import json
import platform
import shlex
import subprocess
from pathlib import Path


def digest(path):
    before = path.stat()
    value = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ):
        raise ValueError('Build input changed during hashing')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-synthetic-selftest', action='store_true', required=True)
    parser.add_argument('--candidate-root', type=Path, default=(
        Path.home() / '.huntmob/research/ios-engine-diagnostics-20261014'))
    args = parser.parse_args()
    own = Path(__file__).resolve().parent
    candidate = args.candidate_root.resolve(strict=True)
    engine, build = candidate / 'source', candidate / 'build'
    sources = [own / name for name in ('ans_context_lifecycle.c', 'ans_context_lifecycle.h',
                                       'ans_context_selftest.c', 'build_context_selftest.py')]
    util = build / 'libqemuutil.a'
    files = sources + [util, build / 'config-host.h']
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise ValueError('Regular local build inputs required')
    hashes = {str(path): digest(path) for path in files}
    output = own.parent.parent / 'build/ios-ans-context-lifecycle'
    if output.is_symlink() or output.parent.is_symlink():
        raise ValueError('Regular output directory required')
    output.mkdir(parents=True, exist_ok=True)
    binary, receipt = output / 'selftest', output / 'receipt.json'
    normal_object = output / 'ans_context_lifecycle.normal.o'
    if any(path.is_symlink() for path in (binary, receipt, normal_object)):
        raise ValueError('Refusing symlink outputs')
    host = {'arm64': 'aarch64', 'aarch64': 'aarch64', 'x86_64': 'x86_64',
            'AMD64': 'x86_64'}.get(platform.machine())
    if not host:
        raise ValueError('Unsupported local architecture')
    pkg = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'glib-2.0'],
                                  text=True, timeout=10)
    # QEMU's existing inline qemu_spin_destroy intentionally ignores its argument.
    command = ['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-pthread',
               '-DHUNTMOB_ANS_CONTEXT_TESTING', '-I' + str(build), '-I' + str(engine),
               '-I' + str(engine / 'include'),
               '-I' + str(engine / 'host/include' / host),
               '-I' + str(engine / 'host/include/generic'), '-I' + str(own),
               str(sources[0]), str(sources[2]), str(util), *shlex.split(pkg),
               '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    normal_command = command[:command.index(str(sources[0]))]
    normal_command.remove('-DHUNTMOB_ANS_CONTEXT_TESTING')
    normal_command += shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', 'glib-2.0'], text=True, timeout=10))
    normal_command += ['-c', str(sources[0]), '-o', str(normal_object)]
    subprocess.run(normal_command, check=True, capture_output=True, timeout=60)
    symbols = subprocess.check_output(['nm', '-g', str(normal_object)],
                                      text=True, timeout=10)
    if 'huntmob_ans_context_test_seed_generation' in symbols:
        raise ValueError('Test-only generation hook leaked into normal build')
    result = subprocess.run([str(binary), '--authorized-synthetic-selftest'],
                            check=True, capture_output=True, text=True, timeout=15)
    if any(digest(path) != hashes[str(path)] for path in files):
        raise ValueError('Build input changed during compilation')
    report = json.loads(result.stdout)
    report.update(schema='huntmob.ans-context-lifecycle.native.v1', date='2026-10-15',
                  scope='standalone public-synthetic context lifecycle only',
                  source_hashes=hashes, binary_sha256=digest(binary),
                  synchronization='QemuMutex; callback executes under validated epoch lock',
                  test_generation_hook='compile-time test-only; absent from normal builds',
                  normal_object_sha256=digest(normal_object),
                  normal_object_test_generation_hook_absent=True,
                  key_bytes_in_receipt=False, firmware_executed=False,
                  revocation_does_not_undo_submitted_writes=True,
                  runtime_erasure_instrumented=False)
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'ready': False, 'state': 'context-lifecycle-test-failed',
                          'reason': type(error).__name__}))
        raise SystemExit(1)
