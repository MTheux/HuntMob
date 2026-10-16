#!/usr/bin/env python3
"""Prepare/stage a NEW own DATA-v2 cohort; default is a read-only plan.

AUTHORIZED TESTING ONLY — ISOLATED LAB. --apply and --authorized-lab are
required for mutations. Never opens Keychain or starts a VM. No old cohort
or root is copied. Only the pinned public System filesystem may be copied.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as preparation
import restore_ios_virtual_pristine as pristine
import stage_ios_virtual_profile as staging

require = contract.require


def create(vm_id, expected_engine):
    preparation.check_parent()
    target = contract.require_new_identity(vm_id)
    binding = contract.engine_binding(expected_engine)
    sources = preparation.validate_sources()
    manifest = preparation.create_cohort(target, vm_id, sources)
    manifest.update(schema=contract.SCHEMA, identity_schema=contract.IDENTITY_SCHEMA,
                    profile="huntmob-virtual-sep-own-data-v2-experimental",
                    data_profile=dict(contract.PROFILE), data_profile_sha256=contract.canonical_hash(contract.PROFILE),
                    kdf_id=contract.KDF_ID, native_ready=False, engine_binding=binding,
                    new_identity_required=True, v1_root_or_backings_reused=False)
    preparation.write_manifest(target, manifest)
    return contract.validate_manifest(target)


def restore(target, manifest):
    """Validated public APFS copy into fresh files; no host disk attachment."""
    require(manifest.get("root_provisioned") is False and manifest.get("root_lookup_performed") is False and
            manifest.get("restore_completed") is False and manifest.get("state") == "new-sparse-cohort" and
            not manifest.get("firmware_components_staged"), "Only a never-booted fresh cohort can be restored")
    require(all(preparation.image_path(entry["image-path"]).resolve() != (target / "namespace-1.raw").resolve()
                for entry in preparation.image_inventory() if entry.get("image-path")), "Backing is attached")
    sources = preparation.validate_sources()
    require(sources == manifest["sources"], "Pinned pristine source provenance changed")
    require(shutil.disk_usage(preparation.VM_ROOT).free >= preparation.MIN_START_FREE, "Insufficient restore headroom")
    for name in preparation.SIZES:
        if name != "namespace-1.raw":
            require(not any((target / name).read_bytes()), "Fresh auxiliary store is not zero")
    source_fd = os.open(preparation.SOURCE_RAW, os.O_RDONLY | os.O_NOFOLLOW)
    destination_fd = os.open(target / "namespace-1.raw", os.O_RDWR | os.O_NOFOLLOW)
    try:
        source_info = os.fstat(source_fd)
        source_record = sources[str(preparation.SOURCE_RAW)]
        require((source_info.st_dev, source_info.st_ino, source_info.st_size, source_info.st_nlink,
                 source_info.st_mtime_ns, source_info.st_ctime_ns) == tuple(source_record[key] for key in
                ("device", "inode", "bytes", "links", "mtime_ns", "ctime_ns")), "Opened public source identity differs")
        opened = os.fstat(destination_fd)
        identity = manifest["backings"]["namespace-1.raw"]
        require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_nlink) ==
                (identity["device"], identity["inode"], identity["bytes"], 1), "Opened destination identity differs")
        header = os.pread(source_fd, 92, 512)
        require(header[:8] == b"EFI PART", "Pristine source GPT absent")
        entries = struct.unpack_from("<Q", header, 72)[0]
        entry = os.pread(source_fd, 128, entries * 512)
        typ, _, start, end = struct.unpack_from("<16s16sQQ", entry)
        require(typ == pristine.APFS_TYPE.bytes_le and start * 512 == pristine.PARTITION_OFFSET and
                (end - start + 1) * 512 == pristine.PARTITION_BYTES, "Public APFS geometry changed")
        superblock = os.pread(source_fd, pristine.BLOCK, pristine.PARTITION_OFFSET)
        require(superblock[32:36] == b"NXSB" and struct.unpack_from("<I", superblock, 36)[0] == pristine.BLOCK,
                "Expected pinned public 4K APFS container")
        manifest.update(state="copying-pristine-public-apfs", restore_method="pristine-apfs-partition-copy-v1")
        preparation.write_manifest(target, manifest)
        # Newly created sparse inode only. No historical destination/retry reset.
        for offset, value in pristine.gpt(identity["bytes"], manifest["vm_uuid"]).items():
            require(os.pwrite(destination_fd, value, offset) == len(value), "Short GPT write")
        copied = hashlib.sha256()
        for offset in range(0, pristine.PARTITION_BYTES, 1024 * 1024):
            require(shutil.disk_usage(preparation.VM_ROOT).free >= preparation.MIN_RUNNING_FREE, "20 GiB reserve reached")
            length = min(1024 * 1024, pristine.PARTITION_BYTES - offset)
            data = os.pread(source_fd, length, pristine.PARTITION_OFFSET + offset)
            require(len(data) == length, "Short public APFS read")
            copied.update(data)
            require(os.pwrite(destination_fd, data, 6 * pristine.BLOCK + offset) == length, "Short public APFS write")
        os.fsync(destination_fd)
        pristine.verify_gpt(destination_fd, identity["bytes"])
        readback = hashlib.sha256()
        for offset in range(0, pristine.PARTITION_BYTES, 1024 * 1024):
            length = min(1024 * 1024, pristine.PARTITION_BYTES - offset)
            data = os.pread(destination_fd, length, 6 * pristine.BLOCK + offset)
            require(len(data) == length, "Short public APFS readback")
            readback.update(data)
        require(copied.digest() == readback.digest(), "Public APFS readback differs")
        preparation.validate_source_identities(sources)
        contract.validate_manifest(target, manifest)
        manifest.update(state="pristine-filesystem-restored", restore_completed=True, owned_device_detached=True,
                        gpt_sector_bytes=4096, gpt_crc_verified=True, public_apfs_readback_matches=True,
                        public_apfs_partition_sha256=copied.hexdigest(), public_apfs_bytes=pristine.PARTITION_BYTES,
                        filesystem_capacity_expansion_validated=False, private_artifact_absence_checked=False)
    except BaseException as error:
        manifest.update(state="preparation-failed", restore_completed=False, failure_type=type(error).__name__)
        raise
    finally:
        os.close(destination_fd)
        os.close(source_fd)
        preparation.write_manifest(target, manifest)
    return manifest


def create_empty_mnt2(target, manifest):
    """Create the missing stock mountpoint in this owned System only."""
    mount = target / "SystemStage-data-v2-mnt2"
    require(not mount.exists() and not mount.is_symlink(), "Mountpoint staging was already attempted")
    mount.mkdir(mode=0o700)
    device, before = staging.attach_backing(target, manifest)
    mounted = False
    try:
        system = staging.owned_system(device)
        staging.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        point = staging.safe_path(mount, "mnt2")
        require(not point.is_symlink(), "Guest Data mountpoint is a symlink")
        if not point.exists():
            point.mkdir(mode=0o755)
        require(point.is_dir() and not any(point.iterdir()), "Guest Data mountpoint must be an empty directory")
    finally:
        if mounted:
            staging.run(["/sbin/umount", str(mount)])
        preparation.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        staging.run(["/usr/bin/hdiutil", "detach", device])
    manifest["mnt2_empty_directory_verified"] = True


def stage(target, manifest, phase):
    require(manifest.get("restore_completed") is True and manifest.get("owned_device_detached") is True,
            "Public System restore/detach must precede staging")
    if phase == "data-checkpoint":
        require(manifest.get("restore_checkpoint_observed") is True,
                "Actual matching SEP restore checkpoint must precede Data staging")
    # The unchanged helper logic/marker is VirtualSEP identity v1. DATA-v2 is
    # a host/controller contract; the new UUID scopes the guest helper exactly.
    result = staging.stage(target, manifest, phase, graphics=False)
    if not manifest.get("mnt2_empty_directory_verified"):
        create_empty_mnt2(target, manifest)
    require(manifest["schema"] == contract.SCHEMA and manifest["data_profile"] == contract.PROFILE,
            "Shared staging changed the outer DATA contract")
    manifest["staging_identity_model"] = contract.IDENTITY_SCHEMA
    manifest["v2_staging_complete"] = True
    preparation.write_manifest(target, manifest)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("create", "restore-public", "stage"), default="create")
    parser.add_argument("--phase", choices=("restore-checkpoint", "data-checkpoint"), default="restore-checkpoint")
    parser.add_argument("--engine-sha256", help="Mandatory exact reviewed DATA-v2 engine hash on create")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        result = contract.plan(args.vm_uuid, args.action)
        result.update(backing_sizes=preparation.SIZES, phase=args.phase,
                      source_hash_validation_performed=False, engine_validation_performed=False)
        print(json.dumps(result, indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    if args.action == "create":
        result = create(args.vm_uuid, args.engine_sha256)
    else:
        target = contract.target_for(args.vm_uuid)
        result = contract.validate_manifest(target)
        contract.verify_engine(result)
        if args.action == "restore-public":
            result = restore(target, result)
        else:
            stage(target, result, args.phase)
    print(json.dumps({"manifest": str(contract.target_for(args.vm_uuid) / "virtual-profile.json"),
                      "state": result["state"], "ready": False, "native_ready": False}, indent=2))


if __name__ == "__main__":
    main()
