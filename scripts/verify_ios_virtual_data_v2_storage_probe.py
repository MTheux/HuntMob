#!/usr/bin/env python3
"""Read-only, whole-file public-probe scan for the owned DATA-v2 cohort.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default prints a plan and reads no
cohort. Heavy reads require --apply --authorized-lab. No VM, mount, Keychain,
root export or backing write is performed. Probe absence never closes a finding.
"""
import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import time
import uuid

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as preparation

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-storage-probe-scan.v1"
MAX_OFFSETS = 16
CHUNK_BYTES = 4 * 1024 * 1024


def file_identity(info):
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            "An independent regular file is required")
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
            "links": info.st_nlink, "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns, "uid": info.st_uid,
            "mode": stat.S_IMODE(info.st_mode)}


def path_identity(path):
    return file_identity(path.lstat())


@contextmanager
def open_stable(path, expected_size=None, expected_identity=None):
    before = path_identity(path)
    require(before["uid"] == os.getuid(), "File owner differs")
    if expected_size is not None:
        require(before["bytes"] == expected_size, "File size differs")
    if expected_identity is not None:
        require(before == expected_identity, "File identity changed")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(file_identity(os.fstat(fd)) == before, "File changed while opening")
        yield fd, before
        require(file_identity(os.fstat(fd)) == before and path_identity(path) == before,
                "File changed while reading")
    finally:
        os.close(fd)


def stable_blob(path, limit):
    """Bounded primary metadata/log read; returned bytes must never be printed."""
    with open_stable(path) as (fd, identity):
        require(identity["bytes"] <= limit, "Evidence file exceeds its bound")
        chunks = []
        remaining = identity["bytes"]
        while remaining:
            block = os.read(fd, min(CHUNK_BYTES, remaining))
            require(bool(block), "Evidence file became shorter")
            chunks.append(block)
            remaining -= len(block)
        require(os.read(fd, 1) == b"", "Evidence file became longer")
        blob = b"".join(chunks)
    return blob, hashlib.sha256(blob).hexdigest(), identity


def probe_patterns(canary, expected_sha256):
    require(isinstance(canary, str) and re.fullmatch(r"[0-9a-f]{64}", canary) is not None,
            "Bound public probe shape differs")
    ascii_probe = canary.encode("ascii")
    require(re.fullmatch(r"[0-9a-f]{64}", expected_sha256 or "") is not None and
            hashlib.sha256(ascii_probe).hexdigest() == expected_sha256,
            "Bound public probe digest differs")
    return {"ascii_hex64": ascii_probe, "decoded32": bytes.fromhex(canary)}


def scan_file(fd, path, identity, patterns, *, chunk_bytes=CHUNK_BYTES):
    """Full SHA256 plus overlapping pattern search, without exposing matches."""
    require(chunk_bytes > 0 and patterns and all(isinstance(v, bytes) and v for v in patterns.values()),
            "Nonempty bounded scan patterns required")
    require(file_identity(os.fstat(fd)) == identity and path_identity(path) == identity,
            "Scan source changed before reading")
    os.lseek(fd, 0, os.SEEK_SET)
    overlap = max(map(len, patterns.values())) - 1
    digest = hashlib.sha256()
    counts = {name: 0 for name in patterns}
    offsets = {name: [] for name in patterns}
    scanned = 0
    tail = b""
    while True:
        block = os.read(fd, chunk_bytes)
        if not block:
            break
        digest.update(block)
        window = tail + block
        base = scanned - len(tail)
        for name, pattern in patterns.items():
            start = 0
            while True:
                found = window.find(pattern, start)
                if found < 0:
                    break
                absolute = base + found
                # Matches wholly in the preceding tail were counted previously.
                if absolute + len(pattern) > scanned:
                    counts[name] += 1
                    if len(offsets[name]) < MAX_OFFSETS:
                        offsets[name].append(absolute)
                start = found + 1
        scanned += len(block)
        tail = window[-overlap:] if overlap else b""
    require(scanned == identity["bytes"], "Scan byte count differs")
    require(file_identity(os.fstat(fd)) == identity and path_identity(path) == identity,
            "Scan source changed while reading")
    return {"sha256": digest.hexdigest(), "bytes_scanned": scanned,
            "identity_before": identity, "identity_after": path_identity(path),
            "matches": {name: {"count": counts[name], "offsets": offsets[name],
                                "offsets_truncated": counts[name] > len(offsets[name])}
                        for name in patterns}}


def require_no_attached_backings(target, names, images=None):
    """Disk-image inventory only: never attach, mount, unlock or detach."""
    paths = {target / name for name in names}
    ids = {(path_identity(p)["device"], path_identity(p)["inode"]) for p in paths}
    images = preparation.image_inventory() if images is None else images
    require(isinstance(images, list), "Disk-image inventory is invalid")
    for image in images:
        require(isinstance(image, dict) and isinstance(image.get("image-path"), str),
                "Disk-image inventory lacks an exact backing path")
        candidate = preparation.image_path(image["image-path"])
        require(candidate not in paths and candidate.resolve() not in paths,
                "An owned backing is attached to the host")
        if candidate.exists():
            info = candidate.stat()
            require((info.st_dev, info.st_ino) not in ids, "An owned backing alias is attached to the host")


def checked_creation(target, manifest):
    """Revalidate the exact original public creation receipt/logs, not CLI data."""
    import stage_ios_virtual_data_v2_cold_read as cold
    record = manifest.get("cold_read_v2", {})
    evidence = record.get("creation_evidence", {})
    directory = Path(evidence.get("observation", ""))
    require(directory.parent == target and evidence.get("canary_is_public_fixture") is True,
            "Public fixture creation must belong to the exact cohort")
    inputs = {name: stable_blob(directory / name, 64 * 1024 * 1024)
              for name in ("observation.json", "boot.log", "trace.log")}
    observed = cold.creation_evidence(target, manifest, directory.name)
    require(observed == evidence, "Bound original creation evidence changed")
    for name, (_, digest, identity) in inputs.items():
        expected = evidence["receipt_sha256"] if name == "observation.json" else evidence[name.replace(".", "_") + "_sha256"]
        require(digest == expected and path_identity(directory / name) == identity,
                "Original creation input changed")
    patterns = probe_patterns(observed["expected_public_canary"], record.get("expected_probe_sha256"))
    # Return provenance without the public canary itself.
    return patterns, {"observation": str(directory), "receipt_sha256": evidence["receipt_sha256"],
                      "boot_log_sha256": evidence["boot_log_sha256"],
                      "trace_log_sha256": evidence["trace_log_sha256"],
                      "expected_probe_sha256": record["expected_probe_sha256"],
                      "canary_is_public_fixture": True}, inputs


def scoped_cold_read(target, manifest):
    """Only an observed, hashed, stock post-keybag result can assert scoped read."""
    record = manifest.get("post_keybag_v2", {})
    if record.get("state") != "observed" or record.get("read_validated") is not True:
        return {"validated": False, "reason": "post-keybag-native-read-pending-or-unvalidated"}
    import stage_ios_virtual_data_v2_cold_read as cold
    import stage_ios_virtual_data_v2_post_keybag as post
    require(record.get("vm_uuid") == manifest["vm_uuid"] and record.get("profile") == contract.PROFILE and
            record.get("data_uuid") == manifest.get("cold_read_v2", {}).get("data_uuid") and
            record.get("expected_probe_sha256") == manifest["cold_read_v2"]["expected_probe_sha256"],
            "Post-keybag result identity differs")
    directory = Path(record.get("observation", ""))
    require(directory.parent == target, "Post-keybag observation belongs to another cohort")
    inputs = {name: stable_blob(directory / name, 64 * 1024 * 1024)
              for name in ("observation.json", "boot.log", "trace.log")}
    require(inputs["observation.json"][1] == record.get("observation_sha256") and
            inputs["boot.log"][1] == record.get("boot_log_sha256") and
            inputs["trace.log"][1] == record.get("trace_log_sha256"), "Post-keybag provenance changed")
    _, proof, log, _ = cold.observation(target, manifest, directory.name)
    require(proof.get("post_keybag_class_c_read_requested") is True and
            proof.get("stock_data_protection_verifier_invoked") is True and proof.get("read_validated") is True,
            "Native read receipt lacks the exact post-keybag phase")
    result = post.classify_result(log)
    require(result["read_validated"] is True and result["cold_read_validated"] is True,
            "Native result does not prove the scoped cold read")
    for name, (_, _, identity) in inputs.items():
        require(path_identity(directory / name) == identity, "Post-keybag evidence changed while reading")
    return {"validated": True, "result": result["result"], "observation": str(directory),
            "observation_sha256": inputs["observation.json"][1],
            "boot_log_sha256": inputs["boot.log"][1], "trace_log_sha256": inputs["trace.log"][1]}


def write_json_exclusive(path, value):
    require(path.is_absolute() and path.parent.is_dir(), "Receipt parent must exist")
    for ancestor in (path.parent, *path.parent.parents):
        require(not ancestor.is_symlink(), "Receipt parent must not be a symlink")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
        os.fsync(fd)
    finally:
        os.close(fd)


def scan_cohort(vm_id, public_summary=None):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    target = contract.target_for(vm_id)
    if public_summary is not None:
        require(public_summary.is_absolute() and public_summary.parent.is_dir() and
                not public_summary.exists() and not public_summary.is_symlink(),
                "A new absolute public summary path is required")
        for ancestor in (public_summary.parent, *public_summary.parent.parents):
            require(not ancestor.is_symlink(), "Public summary parent must not be a symlink")
    manifest_path = target / "virtual-profile.json"
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    _, manifest_sha, manifest_identity = stable_blob(manifest_path, 1024 * 1024)
    require(contract.read_metadata(manifest_path) == manifest, "Manifest changed before scanning")
    require_no_attached_backings(target, preparation.SIZES)
    lock_path = target / ".data-v2-launch.lock"
    lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    lock_identity = None
    started = time.monotonic()
    output = None
    try:
        os.fchmod(lock_fd, 0o600)
        os.write(lock_fd, ("storage-scan " + str(os.getpid()) + "\n").encode())
        os.fsync(lock_fd)
        lock_identity = file_identity(os.fstat(lock_fd))
        contract.validate_manifest(target, manifest, owned_launch_lock=lock_fd)
        require_no_attached_backings(target, preparation.SIZES)
        patterns, evidence, creation_inputs = checked_creation(target, manifest)
        cold_read = scoped_cold_read(target, manifest)
        directory = target / ("data-v2-storage-scan-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
        directory.mkdir(mode=0o700, exist_ok=False)
        output = directory / "receipt.json"
        results = {}
        # Keep all nine descriptors open and bind all identities before any scan.
        with ExitStack() as stack:
            handles = {name: stack.enter_context(open_stable(target / name, size))
                       for name, size in preparation.SIZES.items()}
            require(len({(identity["device"], identity["inode"]) for _, identity in handles.values()}) == 9,
                    "Backing identities alias")
            for name, (fd, identity) in handles.items():
                results[name] = scan_file(fd, target / name, identity, patterns)
            # Also catch an earlier backing changing while a later file was read.
            for name, (fd, identity) in handles.items():
                require(file_identity(os.fstat(fd)) == identity and path_identity(target / name) == identity,
                        "Backing changed during the global scan")
            for name, (_, _, identity) in creation_inputs.items():
                require(path_identity(Path(evidence["observation"]) / name) == identity,
                        "Creation evidence changed during the scan")
            require(path_identity(manifest_path) == manifest_identity, "Manifest changed during the scan")
            contract.validate_manifest(target, manifest, owned_launch_lock=lock_fd)
            contract.verify_engine(manifest)
            require(scoped_cold_read(target, manifest) == cold_read, "Native cold-read evidence changed during the scan")
            require_no_attached_backings(target, preparation.SIZES)
            require(file_identity(os.fstat(lock_fd)) == lock_identity and path_identity(lock_path) == lock_identity,
                    "Scan ownership lock changed")
        matches = sum(item["count"] for result in results.values() for item in result["matches"].values())
        receipt = {"schema": SCHEMA, "state": "completed-readonly-scan", "vm_uuid": vm_id,
                   "data_profile": contract.PROFILE, "engine_binding": manifest["engine_binding"],
                   "manifest_sha256": manifest_sha, "creation_evidence": evidence,
                   "backings": results, "total_bytes_scanned": sum(r["bytes_scanned"] for r in results.values()),
                   "duration_seconds": time.monotonic() - started, "chunk_bytes": CHUNK_BYTES,
                   "overlap_bytes": 63, "pattern_lengths": {k: len(v) for k, v in patterns.items()},
                   "total_matches": matches, "public_probe_absent": matches == 0,
                   "global_source_identity_unchanged": True, "host_backings_not_attached_before_after": True,
                   "scoped_native_cold_read": cold_read, "cryptography_validated_by_scan": False,
                   "historical_finding_status": "OPEN", "ready": False, "native_ready": False,
                   "root_accessed": False, "keychain_accessed": False, "vm_started": False,
                   "Data_mounted_or_unlocked": False, "backings_written": False,
                   "limitations": ["Probe absence does not prove encryption, key secrecy, full Data Protection or native readiness.",
                                   "Host administrators remain in the trusted computing base; metadata checks are not hostile-host attestation.",
                                   "Scoped native cold-read evidence, when present, applies only to the pinned probe and cohort."]}
        write_json_exclusive(output, receipt)
        summary = {key: receipt[key] for key in ("schema", "state", "vm_uuid", "total_bytes_scanned", "duration_seconds",
                  "total_matches", "public_probe_absent", "scoped_native_cold_read", "cryptography_validated_by_scan",
                  "historical_finding_status", "ready", "native_ready")}
        summary.update(receipt_path=str(output), receipt_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
        if public_summary is not None:
            write_json_exclusive(public_summary, summary)
        return summary
    except Exception as error:
        if output is not None and not output.exists() and not output.is_symlink():
            write_json_exclusive(output, {"schema": SCHEMA, "state": "failed-readonly-scan",
                                 "error_type": type(error).__name__, "vm_uuid": vm_id,
                                 "cryptography_validated_by_scan": False,
                                 "historical_finding_status": "OPEN", "ready": False, "native_ready": False})
        raise
    finally:
        os.close(lock_fd)
        if lock_identity is not None:
            require(path_identity(lock_path) == lock_identity, "Refuse removing a replaced scan lock")
            lock_path.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    parser.add_argument("--public-summary", type=Path)
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"schema": SCHEMA, "state": "plan-only", "target": str(contract.target_for(args.vm_uuid)),
                          "heavy_read_performed": False, "backing_count": 9,
                          "expected_total_bytes": sum(preparation.SIZES.values()), "root_accessed": False,
                          "cryptography_validated_by_scan": False, "historical_finding_status": "OPEN",
                          "ready": False, "native_ready": False}, indent=2))
        return
    require(args.authorized_lab, "Heavy reads require --authorized-lab")
    print(json.dumps(scan_cohort(args.vm_uuid, args.public_summary), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Do not echo source logs, probe bytes or arbitrary exception arguments.
        print(json.dumps({"schema": SCHEMA, "state": "failed", "error_type": type(error).__name__,
                          "historical_finding_status": "OPEN", "native_ready": False, "ready": False}))
        raise SystemExit(1)
