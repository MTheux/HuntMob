#!/usr/bin/env python3
"""Public isolated bridge tests. No firmware, real keys, device or network I/O.

Compiles exact reviewed bridge functions from an explicit SEP source file.
Core/memory/BQL are mocked: this does not validate QEMU MMIO or cryptography.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shlex
import subprocess

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
EXPECTED_FUNCTIONS_SHA256 = "43c270fc9c1516ae0aac064e6ea59fe31fcb4939fb1629956b9fc5a207efb50d"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorized-public-fixtures", action="store_true", required=True)
    parser.add_argument("--sep-source", type=Path, required=True)
    parser.add_argument("--engine-build", type=Path, default=Path.home()/".huntmob/research/ios-engine-diagnostics-20261014/build")
    parser.add_argument("--output", type=Path, default=REPO/"build/ios-virtual-mpe-bridge")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    source = args.sep_source.resolve()
    build = args.engine_build.resolve()
    text = source.read_text()
    first = text[text.index("static void sep_virtual_mpe_fault("):text.index("void apple_sep_set_virtual_mpe(")]
    second = text[text.index("static bool sep_virtual_mpe_write("):text.index("static void misc1_reg_write(")]
    functions = first + second + "\n"
    actual = hashlib.sha256(functions.encode()).hexdigest()
    if actual != EXPECTED_FUNCTIONS_SHA256:
        raise SystemExit("Reviewed bridge function hash mismatch; no test executed")
    args.output.mkdir(parents=True, exist_ok=True)
    harness = args.output/"bridge_selftest.c"
    binary = args.output/"bridge_selftest"
    harness.write_text((HERE/"selftest_prefix.c").read_text()+functions+(HERE/"selftest_cases.c").read_text())
    root = build.parent/"source"
    flags = subprocess.check_output(["pkg-config", "--cflags", "--libs", "glib-2.0"], text=True)
    command = ["cc", "-std=gnu11", "-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter"]
    command += ["-I"+str(p) for p in [build, root/"include", root/"host/include/aarch64", root/"host/include/generic"]]
    command += [str(harness), str(build/"libqemuutil.a")]+shlex.split(flags)+["-o", str(binary)]
    compiled = subprocess.run(command, text=True, capture_output=True, timeout=60)
    (args.output/"compile.log").write_text(compiled.stdout+compiled.stderr)
    if compiled.returncode:
        raise SystemExit("Harness compilation failed; see compile.log")
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    run = subprocess.run([str(binary)], text=True, capture_output=True, timeout=15, env=env)
    if run.returncode or run.stderr:
        raise SystemExit("Harness failed or emitted sanitizer diagnostics")
    result = json.loads(run.stdout)
    receipt = {"schema":"huntmob.virtual-mpe-bridge.public-function-checks.v1", "source_sha256":sha(source), "reviewed_functions_sha256":actual, "harness_sha256":sha(harness), "binary_sha256":sha(binary), "qemuutil_sha256":sha(build/"libqemuutil.a"), "results":result, "sanitizers":["address","undefined"], "leak_sanitizer_enabled":False, "scope":"Exact bridge functions; memory/core/BQL mocked, utility archive not instrumented", "real_keys_used":False, "firmware_executed":False, "engine_mmio_validated":False}
    (args.output/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
