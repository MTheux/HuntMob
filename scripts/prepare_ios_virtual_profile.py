#!/usr/bin/env python3
"""Plan or prepare a new experimental virtual-SEP-v1 disk cohort.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Defaults to a read-only plan. The
reviewed restore action may erase ONLY a loop device attached by this process
from its newly created namespace-1.raw. Never accepts device/source paths.
No Keychain root is created/read and no iOS VM or companion is started here.
"""
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import time
import urllib.parse
import uuid
from pathlib import Path


RESEARCH = Path.home() / ".huntmob/research"
VM_ROOT = RESEARCH / "ios-vms"
IPSW = RESEARCH / "firmware/iPhone11,8,iPhone12,1_14.0_18A5351d_Restore.ipsw"
SOURCE = RESEARCH / "image-integrity-20261013-214435/source.dmg"
SOURCE_RAW = SOURCE.with_name("source.raw")
PINS = {
    IPSW: "706742ed60327a5247c29ccc5bf7e6ce9bbf11dd30a468f8f6fc9da76bdca96d",
    SOURCE: "cae20aff4f69e72b78f80fdaf92f26d1f3dac7890c66ca00d16bb6f3270368dd",
    SOURCE_RAW: "96bebe305f5e0ab41ba61e976e52687646bfa1f189918956069caeda107ee9d6",
}
# Sizes match boot_ios_research.command(), including all volatile identity stores.
SIZES = {**{f"namespace-{index}.raw": size for index, size in enumerate(
    (32 * 1024**3, 8 * 1024**2, 128 * 1024, 8 * 1024,
     8 * 1024, 4 * 1024, 1024**2), 1)},
    "sep-nvram.raw": 64 * 1024, "sep-ssc.raw": 128 * 1024}
MIN_START_FREE = 28 * 1024**3  # 20 GiB reserve + 8 GiB expected restore headroom.
MIN_RUNNING_FREE = 20 * 1024**3
ASR_SECONDS = 900


def require(condition, message):
    if not condition:
        raise ValueError(message)


def fingerprint(path, source=False):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            "Only an independent regular owned file is accepted")
    result = {"device": info.st_dev, "inode": info.st_ino,
              "bytes": info.st_size, "links": info.st_nlink}
    if source:
        result.update(mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
    return result


def digest(path):
    before = fingerprint(path, source=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(descriptor)
        require((opened.st_dev, opened.st_ino) == (before["device"], before["inode"]),
                "Source changed while opening")
        result = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                result.update(block)
        after = os.fstat(descriptor)
        require(after.st_size == opened.st_size and after.st_mtime_ns == opened.st_mtime_ns
                and after.st_ctime_ns == opened.st_ctime_ns and fingerprint(path, source=True) == before,
                "Source changed while hashing")
        return result.hexdigest(), before
    finally:
        os.close(descriptor)


def validate_sources():
    identities = {}
    for path, expected in PINS.items():
        observed, identity = digest(path)
        require(observed == expected, "Pinned pristine firmware source differs")
        identities[str(path)] = {"sha256": observed, **identity}
    return identities


def validate_source_identities(records):
    for path, record in records.items():
        require(fingerprint(Path(path), source=True) == {key: record[key] for key in (
            "device", "inode", "bytes", "links", "mtime_ns", "ctime_ns")},
            "Pinned source identity/content metadata changed during preparation")


def run_plist(arguments):
    result = subprocess.run(arguments, capture_output=True, timeout=30, check=True)
    require(len(result.stdout) <= 8 * 1024 * 1024, "Unexpectedly large device metadata")
    return plistlib.loads(result.stdout)


def image_inventory():
    result = run_plist(["/usr/bin/hdiutil", "info", "-plist"])
    require(isinstance(result, dict) and isinstance(result.get("images"), list),
            "Invalid disk-image inventory")
    return result["images"]


def whole_devices(images):
    return {entity.get("dev-entry") for image in images
            for entity in image.get("system-entities", [])
            if re.fullmatch(r"/dev/disk[0-9]+", str(entity.get("dev-entry", "")))}


def image_path(value):
    require(isinstance(value, str), "Disk-image path missing")
    if value.startswith("file:"):
        parsed = urllib.parse.urlparse(value)
        require(parsed.scheme == "file" and not parsed.netloc and
                not parsed.query and not parsed.fragment, "Unexpected backing URI")
        value = urllib.parse.unquote(parsed.path)
    result = Path(value)
    require(result.is_absolute(), "Disk-image backing must be absolute")
    return result


def validate_virtual_info(info, device):
    """Pure metadata contract; no path supplied to this function is erased."""
    require(info.get("DeviceNode") == device and
            info.get("DeviceIdentifier") == device.removeprefix("/dev/"),
            "Loop-device identity mismatch")
    whole_values = [info[key] for key in ("Whole", "WholeDisk") if key in info]
    size_values = [info[key] for key in ("TotalSize", "Size") if key in info]
    require(whole_values and all(value is True for value in whole_values),
            "Target is not consistently a whole disk")
    require(info.get("VirtualOrPhysical") == "Virtual"
            and info.get("BusProtocol") == "Disk Image",
            "Target is not a whole virtual Disk Image")
    require(info.get("Internal") is False and not info.get("Mounted", False)
            and not info.get("MountPoint"), "Target is internal or mounted")
    require(size_values and all(value == SIZES["namespace-1.raw"] for value in size_values),
            "Loop-device size differs from the new namespace")
    require(info.get("DeviceBlockSize") == 4096, "Loop-device block size differs from the pinned layout")


def verify_attachment(image, identity, device, prior_devices):
    require(identity.get("bytes") == SIZES["namespace-1.raw"],
            "Owned namespace size differs from the fixed profile")
    require(re.fullmatch(r"/dev/disk[0-9]+", device) and device not in prior_devices,
            "Target was not newly attached by this invocation")
    require(fingerprint(image) == identity, "Owned namespace identity changed")
    matches = []
    for entry in image_inventory():
        candidate = entry.get("image-path")
        if not candidate:
            continue
        try:
            path = image_path(candidate)
            same = not path.is_symlink() and path.resolve(strict=True) == image.resolve(strict=True)
        except (ValueError, OSError):
            same = False
        if same:
            matches.append(entry)
    require(len(matches) == 1 and device in whole_devices(matches),
            "Loop device no longer belongs exclusively to the created backing")
    validate_virtual_info(run_plist(["/usr/sbin/diskutil", "info", "-plist", device]), device)


def discover_owned_attachment(image, identity, prior_devices):
    """Recover cleanup ownership if attach returned an error after attaching."""
    candidates = set()
    for entry in image_inventory():
        try:
            path = image_path(entry.get("image-path"))
            if not path.is_symlink() and path.resolve(strict=True) == image.resolve(strict=True):
                candidates.update(whole_devices([entry]) - prior_devices)
        except (OSError, ValueError):
            continue
    require(len(candidates) == 1, "No single newly owned attachment can be recovered")
    device = candidates.pop()
    verify_attachment(image, identity, device, prior_devices)
    return device


def asr_command(device):
    require(re.fullmatch(r"/dev/disk[0-9]+", device), "Invalid owned loop device")
    return ["/usr/sbin/asr", "restore", "--source", str(SOURCE), "--target", device,
            "--erase", "--noprompt", "--SHA256", "--puppetstrings"]


def write_manifest(target, value):
    temporary = target / f".manifest-{os.getpid()}.json"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, target / "virtual-profile.json")


def check_parent():
    for path in (Path.home(), Path.home() / ".huntmob", RESEARCH, VM_ROOT):
        require(not path.is_symlink() and path.is_dir(), "Research directory must already exist without symlinks")


def create_cohort(target, vm_uuid, sources):
    check_parent()
    require(not target.exists() and not target.is_symlink(), "Virtual profile destination already exists")
    require(shutil.disk_usage(VM_ROOT).free >= MIN_START_FREE,
            "At least 28 GiB free is required before preparation")
    target.mkdir(mode=0o700, exist_ok=False)
    created = {}
    for name, size in SIZES.items():
        descriptor = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.ftruncate(descriptor, size)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        created[name] = fingerprint(target / name)
    manifest = {
        "schema": "huntmob.virtual-sep-profile.v1", "model_version": 1,
        "vm_uuid": vm_uuid, "profile": "huntmob-virtual-sep-v1-experimental",
        "keychain_service": "HuntMob.VirtualSEP.v1", "keychain_account": vm_uuid,
        "root_provisioned": False, "root_lookup_performed": False,
        "sources": sources, "backings": created, "initial_zero_sparse_backings": True,
        "old_cohort_cloned": False, "restore_completed": False,
        "firmware_components_staged": False, "private_artifact_absence_checked": False,
        "state": "new-sparse-cohort", "ready": False, "apple_sep_equivalent": False,
        "guest_abi_validated": False, "data_protection_validated": False,
        "springboard_validated": False, "ipa_execution_validated": False,
    }
    write_manifest(target, manifest)
    return manifest


def stop_owned_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def restore_new_cohort(target, manifest):
    image = target / "namespace-1.raw"
    identity = manifest["backings"][image.name]
    before = image_inventory()
    prior_devices = whole_devices(before)
    require(all(image_path(entry["image-path"]).resolve() != image.resolve()
                for entry in before if entry.get("image-path")), "New backing is already attached")
    device = None
    attachment_attempted = False
    failure = None
    try:
        attachment_attempted = True
        attached = run_plist([
            "/usr/bin/hdiutil", "attach", "-nomount", "-noautofsck", "-noautoopen", "-nobrowse",
            "-imagekey", "diskimage-class=CRawDiskImage", "-blocksize", "4096", "-plist", str(image)])
        candidates = whole_devices([attached])
        require(len(candidates) == 1, "Attach did not return exactly one whole device")
        device = candidates.pop()
        verify_attachment(image, identity, device, prior_devices)
        # A modified source cannot inherit the earlier hash validation receipt.
        validate_source_identities(manifest["sources"])
        manifest.update(state="restoring-new-owned-loop-device", attached_device=device,
                        asr_command=asr_command(device))
        write_manifest(target, manifest)
        log_path = target / "asr-public-filesystem.log"
        with log_path.open("xb") as log:
            process = subprocess.Popen(asr_command(device), stdout=log, stderr=subprocess.STDOUT,
                                       stdin=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + ASR_SECONDS
                while process.poll() is None:
                    require(time.monotonic() < deadline, "ASR observation time limit reached")
                    require(shutil.disk_usage(VM_ROOT).free >= MIN_RUNNING_FREE,
                            "ASR stopped to retain 20 GiB free")
                    require(log_path.stat().st_size <= 8 * 1024 * 1024, "ASR metadata log exceeded bound")
                    time.sleep(0.25)
                require(process.returncode == 0, "ASR did not complete successfully")
            finally:
                stop_owned_process(process)
        content = log_path.read_bytes()
        require(b"Restore completed successfully" in content, "ASR completion marker missing")
        validate_source_identities(manifest["sources"])
        require(fingerprint(image) == identity, "Restore replaced/resized the owned backing")
        for name in SIZES:
            if name != image.name:
                require(fingerprint(target / name) == manifest["backings"][name],
                        "A non-System backing identity changed during restore")
                with (target / name).open("rb") as source:
                    require(not any(source.read()), "A fresh auxiliary backing is no longer zero")
        manifest.update(state="pristine-filesystem-restored", restore_completed=True,
                        asr_log_sha256=hashlib.sha256(content).hexdigest())
    except BaseException as error:
        failure = error
        manifest.update(state="preparation-failed", failure_type=type(error).__name__,
                        failure_reason=str(error)[:300], restore_completed=False)
    finally:
        if attachment_attempted and device is None:
            try:
                device = discover_owned_attachment(image, identity, prior_devices)
                manifest["cleanup_ownership_recovered_after_attach_error"] = True
            except BaseException:
                manifest["attachment_not_safely_recoverable"] = True
        if device is not None:
            try:
                # Never detach a reused/foreign device, and never force detach.
                verify_attachment(image, identity, device, prior_devices)
                subprocess.run(["/usr/bin/hdiutil", "detach", device],
                               capture_output=True, timeout=30, check=True)
                manifest["owned_device_detached"] = True
            except BaseException as error:
                manifest["owned_device_detached"] = False
                manifest["detach_failure_type"] = type(error).__name__
                if failure is None:
                    failure = error
                    manifest.update(state="detach-failed", restore_completed=False)
        write_manifest(target, manifest)
    if failure is not None:
        raise failure
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--authorized-lab", action="store_true")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--plan", action="store_true", help="Read-only plan; default")
    action.add_argument("--create-files", action="store_true", help="Create only nine new sparse files and public manifest")
    action.add_argument("--restore-reviewed", action="store_true", help="Create a NEW cohort and erase ONLY its newly attached loop device; review source first")
    args = parser.parse_args()
    require(str(uuid.UUID(args.vm_uuid)) == args.vm_uuid, "VM UUID must be canonical lowercase")
    target = VM_ROOT / ("virtual-sep-v1-" + args.vm_uuid)
    check_parent()
    if not (args.create_files or args.restore_reviewed):
        print(json.dumps({
            "schema": "huntmob.virtual-sep-preparation-plan.v1", "read_only": True,
            "target": str(target), "target_exists": target.exists(), "backing_sizes": SIZES,
            "source_paths_and_expected_sha256": {str(path): value for path, value in PINS.items()},
            "source_hash_validation_performed": False,
            "start_free_required": MIN_START_FREE, "running_free_reserved": MIN_RUNNING_FREE,
            "free_now": shutil.disk_usage(VM_ROOT).free,
            "asr_command_template": ["<new-owned-loop-device>" if part == "/dev/disk999999" else part
                                     for part in asr_command("/dev/disk999999")],
            "root_will_be_created": False, "root_will_be_read": False,
            "old_cohort_will_be_cloned": False, "ready": False,
        }, indent=2))
        return
    require(args.authorized_lab, "Mutating preparation requires --authorized-lab")
    sources = validate_sources()
    manifest = create_cohort(target, args.vm_uuid, sources)
    if args.restore_reviewed:
        manifest = restore_new_cohort(target, manifest)
    print(json.dumps({"manifest": str(target / "virtual-profile.json"),
                      "state": manifest["state"], "ready": False}, indent=2))


if __name__ == "__main__":
    main()
