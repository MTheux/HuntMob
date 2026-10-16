#!/usr/bin/env python3
"""Compile a pinned diagnostic engine in an exclusive tree; never boot a guest."""
import argparse
import hashlib
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
COMPONENT = PROJECT / 'components/ios-engine'
PATCHES = ('macos27-build.patch', 'ans-storage-diagnostics.patch',
           'ans-storage-diagnostics-stage2.patch', 'ans-storage-protected-io-guard.patch',
           'ans-lab-unwrapped-xts.patch', 'ans-lab-unwrapped-xts-cancel-status.patch',
           'sep-aes-keyline-diagnostics.patch', 'crypto-nettle-context-erasure.patch',
           'sep-key-control-categories.patch', 'ans-lab-wrapped-xts.patch',
           'sep-key-role-categories.patch', 'sep-derivation-readiness-diagnostics.patch',
           'ans-lab-reset-revocation-ram-dma.patch',
           'huntmob-virtual-sep-provider.patch', 'huntmob-virtual-sep-hmac-erase.patch',
           'huntmob-virtual-sep-nettle4-hmac.patch', 'sep-virtual-identity-integration.patch',
           'sep-virtual-identity-revoke.patch', 'sep-virtual-identity-bql.patch',
           'sep-virtual-identity-trace-readiness.patch',
           'huntmob-virtual-sep-machine-ans.patch', 'qcrypto-secret-root-erasure.patch',
           'sep-virtual-command-diagnostics.patch', 'huntmob-virtual-mpe-core-v1.patch',
           'huntmob-virtual-mpe-memory-v1.patch', 'huntmob-virtual-mpe-sep-bridge.patch',
           'huntmob-virtual-mpe-slpw-compat.patch',
           'huntmob-virtual-mpe-memory-n0.patch', 'arm-romd-ptw-write-guard.patch',
           'arm-romd-ptw-stage2-preservation.patch',
           'huntmob-virtual-mpe-progress-metadata.patch',
           'sep-uid-control-preserve-inline.patch',
           'ans-virtual-namespace-format-guard.patch',
           'ans-virtual-namespace-layout-validation.patch',
           'ans-protected-gate-diagnostics.patch',
           'ans-protected-frame-diagnostics.patch',
           'ans-wrapped-format-metadata.patch',
           'ans-authenticated-envelope-data-gate.patch',
           'ans-own-data-v2-profile.patch')
ALLOWED_FILES = {
    'configs/devices/aarch64-softmmu/default.mak',
    'hw/block/apple-silicon/ans.c', 'hw/block/trace-events',
    'hw/arm/apple-silicon/sep.c', 'hw/arm/apple-silicon/trace-events',
    'hw/nvme/ctrl.c', 'hw/nvme/nvme.h', 'hw/nvme/trace-events',
    'hw/misc/apple-silicon/aes.c', 'hw/misc/apple-silicon/trace-events',
    'crypto/cipher-nettle.c.inc', 'crypto/hmac-nettle.c', 'crypto/secret_common.c',
    'crypto/huntmob-virtual-sep.c', 'include/crypto/huntmob-virtual-sep.h',
    'include/hw/arm/apple-silicon/sep.h',
    'hw/arm/apple-silicon/t8030.c', 'include/hw/arm/apple-silicon/t8030.h',
    'include/hw/block/apple-silicon/ans.h',
    'crypto/apple-ans-wrapped.c', 'include/crypto/apple-ans-wrapped.h', 'crypto/meson.build',
    'crypto/huntmob-virtual-mpe.c', 'include/crypto/huntmob-virtual-mpe.h',
    'hw/arm/apple-silicon/huntmob-virtual-mpe-memory.c',
    'include/hw/arm/apple-silicon/huntmob-virtual-mpe-memory.h',
    'hw/arm/apple-silicon/meson.build',
    'target/arm/ptw.c',
}
TRACE_EVENTS = ('apple_ans_vendor_access', 'apple_sep_key_transfer_unimplemented',
                'pci_nvme_apple_ans_submit', 'pci_nvme_apple_ans_complete',
                'pci_nvme_apple_ans_admin_unimplemented',
                'apple_sep_aess_operation', 'apple_sep_aess_complete',
                'apple_sep_aess_uid_wrap_approximation', 'apple_sep_aess_reset',
                'apple_sep_ssc_command', 'apple_sep_ssc_complete',
                'apple_sep_ssc_backing_io', 'apple_sep_ssc_reset',
                'pci_nvme_apple_ans_protected_io_rejected',
                'pci_nvme_apple_ans_protected_gate',
                'pci_nvme_apple_ans_frame_format',
                'apple_aes_process_command', 'apple_aes_key_mode',
                'apple_aes_data_rejected', 'apple_aes_cipher_result',
                'apple_sep_keyline_request', 'apple_sep_key_control_category',
                'apple_sep_derivation_readiness', 'apple_sep_virtual_operation',
                'apple_sep_virtual_mpe_control', 'apple_sep_virtual_mpe_memory_event')
PROTECTION_HEADER_SHA256 = 'bf40e579eaafcfc6bb8f56865dfa5111ec787a306d6fba6adb112b3e0e1e7aa4'
OPTIONS = [
    '--target-list=aarch64-softmmu', '--disable-guest-agent', '--disable-sdl',
    '--disable-gtk', '--disable-cocoa', '--disable-pvg', '--enable-lzfse',
    '--enable-nettle', '--enable-gnutls', '--enable-slirp', '--disable-werror',
    '--extra-cflags=-I/opt/homebrew/include', '--extra-ldflags=-L/opt/homebrew/lib',
]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_patches(patches):
    """Only the reviewed build and metadata diagnostics can enter this recipe."""
    for path in patches:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise ValueError('Invalid diagnostic patch.')
        files = re.findall(r'^diff --git a/(\S+) b/(\S+)$', path.read_text(), re.M)
        if not files or any(a != b or a not in ALLOWED_FILES for a, b in files):
            raise ValueError('Patch changes a path outside the diagnostic contract.')


def reviewed_sources(source, patch_names):
    """Bind added files too: git diff alone omits untracked patch-created files."""
    paths = set()
    for name in patch_names:
        paths.update(re.findall(r'^diff --git a/(\S+) b/\S+$',
                                (COMPONENT / name).read_text(), re.M))
    result = {}
    for name in sorted(paths):
        path = Path(source) / name
        if name not in ALLOWED_FILES or path.is_symlink() or not path.is_file():
            raise ValueError('Reviewed source must be a regular allowed file.')
        result[name] = sha256(path)
    return result


def require_data_protection(source):
    """Reject the earlier simplified SEP build, even if it compiles successfully."""
    header = Path(source) / 'include/hw/arm/apple-silicon/boot.h'
    content = header.read_text()
    # Remove comments before checking the actual preprocessor definition.
    content = re.sub(r'/\*.*?\*/|//[^\n]*', '', content, flags=re.S)
    if not re.search(r'^\s*#\s*define\s+ENABLE_DATA_ENCRYPTION\s*$', content, re.M):
        raise ValueError('Data Protection must remain enabled in the source.')
    if header.is_symlink() or sha256(header) != PROTECTION_HEADER_SHA256:
        raise ValueError('Data Protection header must match the pinned source blob.')


def reserve_output(output):
    output = Path(output).absolute()
    # No cleanup or replacement of an existing experiment, even on failure.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    return output


def run(command, cwd, log, timeout):
    with log.open('ab') as stream:
        stream.write(('\n$ ' + json.dumps([str(x) for x in command]) + '\n').encode())
        stream.flush()
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # Ninja/configure may have compiler children. Terminate only this
            # session's group, including children if the parent exits first.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)


def inventory(binary):
    result = {}
    for name, arguments in (
        ('version', ['--version']), ('machines', ['-machine', 'help']),
        ('accelerators', ['-accel', 'help']), ('trace_events', ['-trace', 'help']),
    ):
        proc = subprocess.run([str(binary), *arguments], capture_output=True,
                              text=True, timeout=20, check=True)
        result[name] = proc.stdout + proc.stderr
    if 't8030' not in result['machines']:
        raise ValueError('Candidate is missing the selected t8030 machine.')
    events = set(result['trace_events'].split())
    if not set(TRACE_EVENTS) <= events:
        raise ValueError('Candidate is missing the reviewed storage diagnostics.')
    result['trace_inventory_sha256'] = hashlib.sha256(result['trace_events'].encode()).hexdigest()
    result['trace_events'] = list(TRACE_EVENTS)
    return result


def rebuild_inputs(output, revision, patch_hashes):
    """Reuse only our matching compiled tree; preserve the preceding binary."""
    output = Path(output).resolve(strict=True)
    receipt_path = output / 'build-receipt.json'
    if receipt_path.is_symlink() or receipt_path.stat().st_size > 65536:
        raise ValueError('Invalid preceding build receipt.')
    previous = json.loads(receipt_path.read_text())
    if not isinstance(previous, dict):
        raise ValueError('Invalid preceding build receipt.')
    source, binary = output / 'source', output / 'build/qemu-system-aarch64'
    old_patches = previous.get('patch_sha256')
    if (previous.get('state') != 'compiled' or previous.get('ready') is not False
            or previous.get('purpose') not in {'metadata-only-storage-diagnostics', 'storage-protocol-research'}
            or previous.get('revision') != revision or previous.get('configure_options') != OPTIONS
            or not isinstance(old_patches, dict) or not old_patches
            or any(patch_hashes.get(name) != value for name, value in old_patches.items())
            or binary.is_symlink() or sha256(binary) != previous.get('binary_sha256')):
        raise ValueError('The preceding diagnostic build no longer matches its receipt.')
    require_data_protection(source)
    diff = subprocess.check_output(['git', 'diff', '--binary', revision], cwd=source, timeout=10)
    if hashlib.sha256(diff).hexdigest() != previous.get('source_diff_sha256'):
        raise ValueError('Source changed outside the reviewed rebuild patches.')
    old_sources = reviewed_sources(source, old_patches)
    if 'reviewed_source_sha256' in previous:
        if old_sources != previous['reviewed_source_sha256']:
            raise ValueError('Reviewed source changed after compilation.')
    else:
        # Migrate only the old tracked-only receipt. A missing added-file hash
        # must never turn a new receipt into a less strict legacy one.
        subprocess.run(['git', 'ls-files', '--error-unmatch', *old_sources],
                       cwd=source, check=True, capture_output=True, timeout=10)
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source,
                               text=True, timeout=10).strip() != revision:
        raise ValueError('Candidate revision changed.')
    if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source / 'util/mlib',
                               text=True, timeout=10).strip() != previous.get('mlib_revision'):
        raise ValueError('Candidate submodule changed.')
    # Keep this binary beside its original RPATH dependencies for comparisons.
    backup = binary.with_name('qemu-system-aarch64-' + previous['binary_sha256'][:16])
    with binary.open('rb') as src, backup.open('xb') as dst:
        shutil.copyfileobj(src, dst)
    backup.chmod(0o700)
    receipt_path.rename(output / ('build-receipt-' + previous['binary_sha256'][:16] + '.json'))
    return output, previous


def build(repository, output, jobs=4, rebuild=False):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('This recipe is validated only on the Mac ARM research worker.')
    if not 1 <= jobs <= 6:
        raise ValueError('Use between one and six compiler jobs.')
    pin = json.loads((COMPONENT / 'upstream.json').read_text())
    revision = pin['revision']
    if not re.fullmatch('[a-f0-9]{40}', revision):
        raise ValueError('Invalid engine revision pin.')
    repository = Path(repository).resolve(strict=True)
    # Read the pinned commit rather than copy dirty sources or the old binary.
    found = subprocess.check_output(
        ['git', '-C', str(repository), 'rev-parse', revision + '^{commit}'],
        text=True, timeout=10).strip()
    if found != revision:
        raise ValueError('Pinned revision unavailable.')
    patches = [COMPONENT / name for name in PATCHES]
    check_patches(patches)
    patch_hashes = {p.name: sha256(p) for p in patches}
    previous = None
    if rebuild:
        output, previous = rebuild_inputs(output, revision, patch_hashes)
    else:
        output = reserve_output(output)
    log = output / 'build.log'
    if not rebuild:
        log.touch(mode=0o600, exist_ok=False)
    receipt_path = output / 'build-receipt.json'
    receipt = {
        'version': 1, 'purpose': 'storage-protocol-research',
        'revision': revision, 'patch_sha256': patch_hashes,
        'configure_options': OPTIONS, 'jobs': jobs, 'state': 'building',
        'ready': False, 'storage_crypto_implemented': False,
        'data_protection_validated': False, 'springboard_validated': False,
        'ipa_execution_validated': False,
        'protected_io_policy': 'reject-unsupported-apple-ans-read-write',
        'synthetic_unwrapped_xts_available': True,
        'synthetic_unwrapped_xts_default_enabled': False,
        'synthetic_wrapped_xts_available': True,
        'synthetic_wrapped_xts_default_enabled': False,
        'sep_wrapping_context_source_validated': False,
        'synthetic_wrapped_context_reset_policy': 'revoke-before-drain-no-auto-rearm',
        'synthetic_protected_data_dma_policy': 'ram-only-preflight-plus-memtx-check',
        'wrapped_key_support': False, 'hardware_crypto_abi_validated': False,
        'virtual_sep_model': 'HuntMob.VirtualSEP.v1',
        'virtual_sep_model_available': True, 'virtual_sep_default_enabled': False,
        'virtual_sep_boot_validated': False, 'virtual_sep_at_rest_validated': False,
        'virtual_mpe_model': 'HuntMob.OwnMPE.v1',
        'virtual_mpe_default_enabled': False,
        'virtual_mpe_apple_equivalence': False,
        'virtual_mpe_cpu_memory_validated': False,
    }
    if previous:
        receipt['previous_binary_sha256'] = previous['binary_sha256']
    receipt_path.touch(mode=0o600, exist_ok=False)

    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')

    save()
    started = time.monotonic()
    source, build_dir = output / 'source', output / 'build'
    try:
        if not rebuild:
            run(['git', '-C', str(repository), 'worktree', 'add', '--detach', str(source), revision],
                repository, log, 60)
        for patch in patches:
            if previous and patch.name in previous['patch_sha256']:
                continue
            if sha256(patch) != patch_hashes[patch.name]:
                raise ValueError('Patch changed during build preparation.')
            run(['git', 'apply', '--check', str(patch)], source, log, 20)
            run(['git', 'apply', str(patch)], source, log, 20)
        require_data_protection(source)
        receipt['data_protection_source_enabled'] = True
        source_before = reviewed_sources(source, PATCHES)
        if not rebuild:
            run(['git', 'submodule', 'update', '--init', '--depth', '1', 'util/mlib'],
                source, log, 180)
        receipt['mlib_revision'] = subprocess.check_output(
            ['git', '-C', str(source / 'util/mlib'), 'rev-parse', 'HEAD'],
            text=True, timeout=10).strip()
        if not rebuild:
            build_dir.mkdir(mode=0o700)
            run([str(source / 'configure'), *OPTIONS], build_dir, log, 300)
        run(['/opt/homebrew/bin/ninja', '-j', str(jobs), 'qemu-system-aarch64'],
            build_dir, log, 1200)
        require_data_protection(source)
        if reviewed_sources(source, PATCHES) != source_before:
            raise ValueError('Reviewed source changed during compilation.')
        receipt['reviewed_source_sha256'] = source_before
        binary = build_dir / 'qemu-system-aarch64'
        receipt.update(inventory(binary))
        receipt.update(state='compiled', binary=str(binary), binary_sha256=sha256(binary),
                       source_diff_sha256=hashlib.sha256(subprocess.check_output(
                           ['git', 'diff', '--binary', revision], cwd=source, timeout=10)).hexdigest())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt.update(state='failed', failure_type=type(error).__name__)
        raise
    finally:
        receipt['elapsed_seconds'] = round(time.monotonic() - started, 2)
        save()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path,
                        default=Path.home() / '.huntmob/research/Inferno')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--rebuild', action='store_true',
                        help='Recompile only a matching owned candidate, preserving its preceding binary.')
    args = parser.parse_args()
    try:
        result = build(args.repository, args.output, args.jobs, args.rebuild)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'state': 'failed', 'ready': False, 'failure_type': type(error).__name__}))
        raise SystemExit(1)
    print(json.dumps({key: result[key] for key in ('state', 'ready', 'binary_sha256',
                                                  'data_protection_validated')}))


if __name__ == '__main__':
    main()
