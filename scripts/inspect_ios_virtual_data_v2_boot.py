#!/usr/bin/env python3
"""Inspect allowlisted public System boot files from an owned DATA-v2 cohort.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a no-op plan. --apply
attaches the owned backing and mounts ONLY System read-only. Data must stay
encrypted, locked and unmounted. No VM, Keychain, keybag or trustcache access.
"""
import argparse
import hashlib
import json
import os
import stat
import time
import uuid
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
import stage_ios_virtual_data_v2_cold_read as cold
from stage_ios_virtual_auxiliary import owned_container

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-system-boot-inspection.v2"
FILES = (
    "sbin/launchd", "System/Library/xpc/launchd.plist",
    "usr/libexec/keybagd", "usr/libexec/securityd",
    "sbin/mount_apfs", "System/Library/Filesystems/apfs.fs/mount_apfs",
    "System/Library/xpc/boot.plist", "System/Library/LaunchDaemons/boot.plist",
    "System/Library/LaunchDaemons/com.apple.keybagd.plist",
    "System/Library/LaunchDaemons/com.apple.mobile.keybagd.plist",
    "System/Library/LaunchDaemons/com.apple.apfsd.plist",
    "System/Library/LaunchDaemons/com.apple.seputil.plist",
    "System/Library/LaunchDaemons/com.apple.init_data_protection.plist",
    "System/Library/LaunchDaemons/com.apple.securityd.plist",
    "System/Library/LaunchDaemons/com.apple.UserEventAgent-System.plist",
    "System/Library/LaunchDaemons/com.apple.mobile.lockdown.plist",
    "System/Library/LaunchDaemons/com.apple.fseventsd.plist",
    "System/Library/LaunchDaemons/com.apple.logd.plist",
    "System/Library/LaunchDaemons/com.apple.bootpd.plist",
    "private/etc/rc", "private/etc/rc.boot", "private/etc/launchd.conf", "private/etc/fstab", "private/etc/boot.plist",
)
DIRECTORIES = (
    "System/Library/LaunchDaemons", "System/Library/xpc", "System/Library/Caches",
    "System/Library/Filesystems/apfs.fs", "private/etc",
)
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
OPTIONAL_LEAF_SYMLINKS = frozenset(("sbin/mount_apfs", "System/Library/Filesystems/apfs.fs/mount_apfs"))


class OptionalLeafSymlink(ValueError):
    """Metadata-only result for an optional utility alias; never followed."""


def resolve_public(mount, relative, allowed):
    require(relative in allowed, "Only a fixed public System allowlist entry may be inspected")
    parts = Path(relative).parts
    require(parts and not Path(relative).is_absolute() and ".." not in parts, "Unsafe public System path")
    current = mount
    for index, name in enumerate(parts):
        current /= name
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            if index == len(parts) - 1 and allowed is FILES and relative in OPTIONAL_LEAF_SYMLINKS:
                raise OptionalLeafSymlink("Optional public utility leaf alias is not followed")
            raise ValueError("Public System symlink refused")
        if index != len(parts) - 1:
            require(stat.S_ISDIR(info.st_mode), "Public System parent is not a directory")
    return current


def copy_public_file(mount, output, relative, remaining):
    try:
        source = resolve_public(mount, relative, FILES)
    except OptionalLeafSymlink:
        return {"present": True, "copied": False, "status": "optional-leaf-symlink-skipped", "symlink_followed": False}, 0
    if source is None:
        return {"present": False}, 0
    info = source.lstat()
    require(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= min(MAX_FILE_BYTES, remaining),
            "Public System file type/size exceeds the inspection contract")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) ==
                (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns),
                "Public file changed while opening")
        data = bytearray()
        while len(data) < info.st_size:
            block = os.read(fd, min(1024 * 1024, info.st_size - len(data)))
            require(block, "Short read from public System file")
            data.extend(block)
        after = os.fstat(fd)
        require((after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) and
                source.lstat().st_ino == info.st_ino, "Public file changed while reading")
    finally:
        os.close(fd)
    destination = output / "public-system" / relative
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    stage.write_new(destination, data)
    sha = hashlib.sha256(data).hexdigest()
    require(stage.digest(destination) == sha, "Extracted public System file readback differs")
    return {"present": True, "bytes": len(data), "sha256": sha,
            "source_device": info.st_dev, "source_inode": info.st_ino,
            "artifact": str(destination.relative_to(output))}, len(data)


def directory_names(mount, relative):
    path = resolve_public(mount, relative, DIRECTORIES)
    if path is None:
        return {"present": False}
    require(path.is_dir(), "Public config inventory must be a directory")
    names = []
    for entry in path.iterdir():
        require(len(names) < 4096, "Public config inventory exceeded its bounded entry count")
        mode = entry.lstat().st_mode
        kind = "symlink" if stat.S_ISLNK(mode) else "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "other"
        names.append({"name": entry.name, "type": kind})
    return {"present": True, "entries": sorted(names, key=lambda item: item["name"]), "contents_read": False}


def checked_readonly_system(mount, system, manifest):
    cold.validate_system_mount(mount, system, manifest)
    require(os.statvfs(mount).f_flag & os.ST_RDONLY, "System inspection requires an actual read-only VFS mount")


def write_receipt(output, record):
    temporary = output / ".receipt-new.json"
    stage.write_new(temporary, json.dumps(record, indent=2).encode())
    fd = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, output / "receipt.json")


def inspect(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    record_cold = manifest.get("cold_read_v2", {})
    require(record_cold.get("schema") == cold.SCHEMA and record_cold.get("vm_uuid") == vm_id and
            record_cold.get("profile") == contract.PROFILE and
            record_cold.get("state") in ("installed", "launch-requested") and
            manifest.get("root_provisioned") is True and not (target / ".data-v2-launch.lock").exists(),
            "Inspection requires the stopped exact cold-read cohort")
    data_uuid = cold.canonical_data_uuid(record_cold.get("data_uuid", ""))
    require(record_cold.get("host_data_uuid") == data_uuid and record_cold.get("host_data_encrypted") is True and
            record_cold.get("host_data_locked") is True, "Bound encrypted Data UUID metadata required")
    output = target / ("data-v2-system-boot-inspection-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    output.mkdir(mode=0o700)
    manifest_sha = stage.digest(target / "virtual-profile.json")
    record = {"schema": SCHEMA, "vm_uuid": vm_id, "data_uuid": data_uuid,
              "data_profile_sha256": manifest["data_profile_sha256"], "engine_binding": manifest["engine_binding"],
              "manifest_sha256": manifest_sha, "state": "attaching-owned-backing", "system_mounted_readonly": False,
              "data_mounted": False, "data_unlocked": False, "root_accessed": False, "vm_started": False,
              "cohort_mutation_requested": False, "whole_backing_content_unchanged_validated": False,
              "trustcache_modified": False, "files": {}, "directory_names": {},
              "ready": False, "native_ready": False}
    write_receipt(output, record)
    device = None
    before = None
    mounted = False
    mount = output / "SystemReadOnly"
    system = None
    try:
        device, before = stage.attach_backing(target, manifest)
        container = owned_container(device)
        system = cold.checked_layout(container, device, manifest, data_uuid)
        record.update(whole_device=device, system_device=system, initial_layout_sha256=contract.canonical_hash(container),
                      initial_volume_metadata=container, state="mounting-system-readonly")
        write_receipt(output, record)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "rdonly,nobrowse,noowners", system, str(mount)])
        mounted = True
        checked_readonly_system(mount, system, manifest)
        cold.checked_layout(owned_container(device), device, manifest, data_uuid, system_mount=mount)
        record.update(system_mounted_readonly=True, mount_path=str(mount), state="inspecting-allowlisted-public-system")
        write_receipt(output, record)
        used = 0
        for relative in FILES:
            value, size = copy_public_file(mount, output, relative, MAX_TOTAL_BYTES - used)
            record["files"][relative] = value
            used += size
            record["bytes_copied"] = used
            # Preserve each completed extraction before the next allowlist
            # entry can fail. A partial inspection retains bound successes.
            write_receipt(output, record)
        for relative in DIRECTORIES:
            record["directory_names"][relative] = directory_names(mount, relative)
            write_receipt(output, record)
        checked_readonly_system(mount, system, manifest)
        cold.checked_layout(owned_container(device), device, manifest, data_uuid, system_mount=mount)
        require(stage.digest(target / "virtual-profile.json") == manifest_sha, "Cohort manifest changed during inspection")
        record.update(bytes_copied=used, state="public-system-copied")
    except BaseException as error:
        record.update(state="inspection-failed", failure_type=type(error).__name__)
        raise
    finally:
        try:
            if mounted:
                # A changed VFS identity prevents unmounting an unrelated path.
                checked_readonly_system(mount, system, manifest)
                cold.checked_layout(owned_container(device), device, manifest, data_uuid, system_mount=mount)
                stage.run(["/sbin/umount", str(mount)])
                record["system_unmounted"] = True
            if device is not None:
                profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
                cold.checked_layout(owned_container(device), device, manifest, data_uuid)
                stage.run(["/usr/bin/hdiutil", "detach", device])
                require(not any(entry.get("image-path") == str(target / "namespace-1.raw") for entry in profile.image_inventory()),
                        "Owned backing remains attached after inspection")
                record["owned_device_detached"] = True
        except BaseException as cleanup:
            record.update(cleanup_failed=True, cleanup_failure_type=type(cleanup).__name__)
            raise
        finally:
            if record["state"] == "public-system-copied" and record.get("owned_device_detached") is True:
                record["state"] = "completed-readonly-inspection"
            write_receipt(output, record)
    return output, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({**contract.plan(args.vm_uuid, "inspect-public-system-boot"), "allowlisted_files": FILES,
                          "names_only_directories": DIRECTORIES, "host_attachment_performed": False,
                          "host_mount_performed": False}, indent=2))
        return
    require(args.authorized_lab, "Host attachment requires --authorized-lab")
    output, record = inspect(args.vm_uuid)
    print(json.dumps({"output": str(output), "state": record["state"], "files_copied": sum("artifact" in v for v in record["files"].values()),
                      "owned_device_detached": record.get("owned_device_detached", False), "ready": False}, indent=2))


if __name__ == "__main__":
    main()
