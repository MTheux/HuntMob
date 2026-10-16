#!/usr/bin/env python3
"""Build the macOS-only virtual SEP Keychain helper without external packages."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New executable path; existing files are never replaced")
    parser.add_argument("--self-test", action="store_true",
                        help="Create and remove only internally generated fixture Keychain items")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / "components/ios-storage-crypto/virtual_sep_keychain.c"
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = args.output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise SystemExit("Output already exists; choose a new helper path")
    output.parent.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("cc")
    if not compiler:
        raise SystemExit("macOS C compiler unavailable")
    with tempfile.TemporaryDirectory(prefix="huntmob-keychain-build-", dir=output.parent) as td:
        temporary = Path(td) / "virtual-sep-keychain"
        result = subprocess.run([
            compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-Wno-deprecated-declarations", str(source), "-o", str(temporary),
            "-framework", "Security", "-framework", "CoreFoundation",
        ], capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise SystemExit("Helper compilation failed: " + result.stderr[-2000:])
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
            raise SystemExit("Helper source changed during compilation")
        os.chmod(temporary, 0o700)
        # Exclusive publication protects an existing helper's Keychain identity.
        os.link(temporary, output)
    receipt = {
        "schema": "huntmob.virtual-sep-keychain-build.v1", "helper": str(output),
        "helper_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "source_sha256": source_hash, "macos_only": True,
        "root_storage": "macOS default file-based Keychain, fixed service and VM UUID account",
        "plaintext_root_files_written": False, "apple_sep_equivalent": False,
        "ready": False,
    }
    if args.self_test:
        result = subprocess.run([str(output), "--self-test"], capture_output=True,
                                text=True, timeout=45)
        try:
            receipt["self_test"] = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise SystemExit("Helper self-test did not return valid metadata")
        receipt["self_test_exit_code"] = result.returncode
        print(json.dumps(receipt, indent=2))
        raise SystemExit(0 if result.returncode == 0 and receipt["self_test"].get("ok") else 1)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
