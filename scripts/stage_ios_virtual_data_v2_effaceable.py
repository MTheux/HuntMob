#!/usr/bin/env python3
"""Stage a new scoped DATA-v2 trusted RAMdisk; default is a read-only plan.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Uses public firmware and an all-zero
new namespace6 only. Never starts a guest or accesses root/key material.
"""
import argparse
import json
import os
import plistlib
import re
import shutil
import stat
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_data_v2_auxiliary import BASE_TC_SHA

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-effaceable.v2"
SOURCE = profile.RESEARCH / "ramdisk-inspection.raw"
SOURCE_SHA = "5eff57f37009c1d996d6de3d6a069029a855cdc978fd54af0977cac49b42689e"
SOURCE_BYTES = 104685568
PINS = {"initialize_effaceable_virtual_v1.c": "2bbde355c905e730fb81294b3a6e474ed84cf600880a32f557aaeb856cf5fc70",
        "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050"}
UTILITY_SHA = "48ee43ea674778fa6aeed41b7e564f829c2efaf87e5f7bb0d08b4f95b2183693"
ENTITLEMENTS = {"com.apple.security.iokit-user-client-class": ["AppleEffaceableStorageUserClient"]}
ORIGINAL_BUILD = "data-v2-effaceable-ramdisk"
RETRY_BUILD = "data-v2-effaceable-ramdisk-r2-mounted-metadata"


def fresh_ns6(target, manifest):
    path = target / "namespace-6.raw"
    require(profile.fingerprint(path) == manifest["backings"][path.name] and
            path.stat().st_size == 4096 and not any(path.read_bytes()),
            "Effaceable initialization requires the new exact all-zero namespace6")


def mount_device_matches(mount, device):
    mounted = mount.lstat()
    block = Path(device).lstat()
    return stat.S_ISDIR(mounted.st_mode) and stat.S_ISBLK(block.st_mode) and mounted.st_dev == block.st_rdev


def verify_ramdisk_attachment(image, identity, device, before, mount):
    """Bind the mounted raw HFS image to this invocation, never another disk."""
    require(re.fullmatch(r"/dev/disk[0-9]+", device) and device not in before and
            profile.fingerprint(image) == identity, "Independent RAMdisk device/image identity changed")
    matches = []
    for entry in profile.image_inventory():
        value = entry.get("image-path")
        if value:
            path = profile.image_path(value)
            if not path.is_symlink() and path.resolve(strict=True) == image.resolve(strict=True):
                matches.append(entry)
    require(len(matches) == 1 and device in profile.whole_devices(matches), "RAMdisk device no longer belongs to this copied image")
    entities = [entry for entry in matches[0].get("system-entities", []) if entry.get("dev-entry") == device]
    require(len(entities) == 1 and entities[0].get("mount-point") == str(mount) and
            entities[0].get("volume-kind", "hfs") == "hfs", "RAMdisk inventory mount/entity differs")
    info = profile.run_plist(["/usr/sbin/diskutil", "info", "-plist", device])
    wholes = [info[key] for key in ("Whole", "WholeDisk") if key in info]
    sizes = [info[key] for key in ("TotalSize", "Size") if key in info]
    require(info.get("DeviceNode") == device and info.get("DeviceIdentifier") == device[5:] and
            wholes and all(value is True for value in wholes) and
            sizes and all(value == SOURCE_BYTES for value in sizes) and
            info.get("VirtualOrPhysical") == "Virtual" and info.get("BusProtocol") == "Disk Image" and
            info.get("Internal") is False and ("Mounted" not in info or info["Mounted"] is True) and
            info.get("FilesystemType") == "hfs" and info.get("MountPoint") == str(mount) and
            mount_device_matches(mount, device), "Mounted device is not exactly the new raw public HFS RAMdisk")


def validate(vm_id, retry=False):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    auxiliary = manifest.get("auxiliary_layout", {})
    require(manifest.get("virtual_staging", {}).get("phase") == "data-checkpoint" and
            manifest.get("restore_checkpoint_observed") is True and
            manifest.get("auxiliary_volumes_staged") is True and
            auxiliary.get("vm_uuid") == vm_id and auxiliary.get("completed") is True and
            auxiliary.get("data_slot_2_absent") is True and
            auxiliary.get("historical_data_or_keys_copied") is False,
            "Fresh matching DATA-v2 restore/auxiliary checkpoints required, once only")
    if retry:
        cleanup = manifest.get("effaceable_ramdisk_v2_cleanup", {})
        require(cleanup.get("state") == "detached-unmodified-copy" and cleanup.get("vm_uuid") == vm_id and
                cleanup.get("profile") == contract.PROFILE and
                contract.canonical_hash(manifest.get("effaceable_ramdisk_v2", {})) == cleanup.get("preparing_record_sha256") and
                stage.digest(target / "data-v2-effaceable-intent.json") == cleanup.get("original_intent_sha256") and
                not (target / "data-v2-effaceable-retry-intent.json").exists() and
                not (target / RETRY_BUILD).exists(), "Only one reviewed pre-write public-copy retry is allowed")
        original = target / ORIGINAL_BUILD / "RestoreRamDisk.raw"
        require(profile.fingerprint(original) == cleanup["detached_image_fingerprint"] and
                stage.digest(original) == cleanup["detached_image_sha256"], "Failed original copy changed after safe detach")
        require(not any(entry.get("image-path") == str(original) for entry in profile.image_inventory()),
                "Failed original copy is still attached")
    else:
        require(manifest.get("effaceable_ramdisk_v2") is None and
                not (target / "data-v2-effaceable-intent.json").exists(), "Fresh RAMdisk staging is single-use")
    fresh_ns6(target, manifest)
    return target, manifest


def inputs(target, manifest):
    """Validate only this DATA-v2 RAMdisk contract before explicit launch."""
    record = manifest.get("effaceable_ramdisk_v2", {})
    require(record.get("schema") == SCHEMA and record.get("vm_uuid") == manifest["vm_uuid"] and
            record.get("profile") == contract.PROFILE and
            record.get("data_profile_sha256") == manifest["data_profile_sha256"] and
            record.get("state") == "prepared" and record.get("prepared") is True and
            record.get("fresh_ns6_zero_verified") is True and
            record.get("secure_root_policy_changed") is False and
            record.get("sep_restore_or_erase_requested") is False and
            record.get("public_original_sha256") == SOURCE_SHA,
            "Exact DATA-v2 effaceable staging contract required")
    fresh_ns6(target, manifest)
    revision = record.get("build_revision", ORIGINAL_BUILD)
    require(revision in (ORIGINAL_BUILD, RETRY_BUILD), "Unreviewed RAMdisk build revision")
    if revision == RETRY_BUILD:
        cleanup = manifest.get("effaceable_ramdisk_v2_cleanup", {})
        require(cleanup.get("state") == "detached-unmodified-copy" and
                record.get("predecessor_cleanup_sha256") == contract.canonical_hash(cleanup),
                "Retry RAMdisk must retain its exact failed-copy cleanup evidence")
    build = target / revision
    files = {}
    for label, name, key in (("RestoreRamDisk", "RestoreRamDisk.raw", "ramdisk"),
                              ("RestoreTrustCache", "RestoreTrustCache", "trustcache")):
        path = Path(record.get(key + "_path", ""))
        require(path == build / name and not path.is_symlink() and
                profile.fingerprint(path) == record[key + "_fingerprint"] and
                stage.digest(path) == record[key + "_sha256"], "Staged DATA-v2 RAMdisk component changed")
        files[label] = {"path": str(path), "sha256": stage.digest(path), "bytes": path.stat().st_size}
    for name, sha in PINS.items():
        require(not (build / name).is_symlink() and stage.digest(build / name) == sha,
                "Staged trusted initializer source changed")
    helper = build / "huntmob-initialize-effaceable"
    require(not helper.is_symlink() and stage.digest(helper) == record["helper_sha256"], "Scoped initializer differs")
    return files


def prewrite_cleanup_evidence(target, manifest):
    """Prove the sole failed public copy is still before its first guest write."""
    record = manifest.get("effaceable_ramdisk_v2", {})
    require(record.get("schema") == SCHEMA and record.get("vm_uuid") == manifest["vm_uuid"] and
            record.get("profile") == contract.PROFILE and record.get("state") == "preparing" and
            record.get("prepared") is False and record.get("source_sha256") == PINS and
            record.get("public_original_sha256") == SOURCE_SHA and "observation" not in record and
            record.get("build_revision", ORIGINAL_BUILD) == ORIGINAL_BUILD and
            not manifest.get("effaceable_ramdisk_v2_cleanup") and
            not (target / "data-v2-effaceable-cleanup-intent.json").exists() and
            not (target / ".data-v2-launch.lock").exists() and not (target / "qmp.sock").exists(),
            "Only the original stopped pre-write RAMdisk preparation may be cleaned once")
    fresh_ns6(target, manifest)
    build = target / ORIGINAL_BUILD
    image, mount = build / "RestoreRamDisk.raw", build / "mount"
    identity = profile.fingerprint(image)
    require(identity["bytes"] == SOURCE_BYTES and image.stat().st_ino != SOURCE.stat().st_ino and
            not build.is_symlink() and not mount.is_symlink(), "Expected independent failed public copy")
    if "public_copy_fingerprint" in record:
        require(identity == record["public_copy_fingerprint"], "Failed public copy identity changed")
    for name, sha in PINS.items():
        require(not (build / name).is_symlink() and stage.digest(build / name) == sha, "Failed-build source pin differs")
    matches = [entry for entry in profile.image_inventory() if entry.get("image-path") == str(image)]
    require(len(matches) == 1 and len(profile.whole_devices(matches)) == 1,
            "Failed copy must own exactly one current whole virtual device")
    device = next(iter(profile.whole_devices(matches)))
    verify_ramdisk_attachment(image, identity, device, set(), mount)
    require(stage.digest(stage.safe_path(mount, "usr/bin/nvmefwupdater")) == UTILITY_SHA,
            "Mounted failed copy has a different public utility")
    for relative in ("usr/libexec/huntmob-initialize-effaceable", "usr/libexec/huntmob-virtual-sep-v1",
                     "System/Library/LaunchDaemons/com.huntmob.effaceable-init.plist"):
        path = stage.safe_path(mount, relative)
        require(not path.exists() and not path.is_symlink(), "Any installed guest helper/marker/daemon forbids a pre-write retry")
    for name in ("com.apple.restored_external.plist", "com.apple.KeyMaker.plist", "com.apple.PurpleReverseProxy.ramdisk.plist"):
        saved = build / (name + ".original")
        require(not saved.exists() and not saved.is_symlink(), "Any saved/mutated guest daemon forbids a pre-write retry")
    require(not SOURCE.is_symlink() and stage.digest(SOURCE) == SOURCE_SHA, "Original public source changed")
    return {"schema": "huntmob.virtual-sep-data-effaceable-cleanup.v2", "vm_uuid": manifest["vm_uuid"],
            "profile": contract.PROFILE, "reason": "mounted-key-omitted-before-first-guest-write",
            "device": device, "mount": str(mount), "image": str(image), "image_fingerprint": identity,
            "mounted_image_sha256": stage.digest(image), "original_intent_sha256": stage.digest(target / "data-v2-effaceable-intent.json"),
            "preparing_record_sha256": contract.canonical_hash(record),
            "source_sha256": dict(PINS), "guest_helper_absent": True, "guest_started": False,
            "fresh_ns6_zero_verified": True, "root_recreated": False, "ready": False}


def cleanup_unmodified_copy(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    evidence = prewrite_cleanup_evidence(target, manifest)
    intent = target / "data-v2-effaceable-cleanup-intent.json"
    stage.write_new(intent, json.dumps(evidence, indent=2).encode())
    descriptor = os.open(intent, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    manifest["effaceable_ramdisk_v2_cleanup"] = {**evidence, "state": "detach-requested"}
    profile.write_manifest(target, manifest)
    image = Path(evidence["image"])
    verify_ramdisk_attachment(image, evidence["image_fingerprint"], evidence["device"], set(), Path(evidence["mount"]))
    stage.run(["/usr/bin/hdiutil", "detach", evidence["device"]])
    require(not any(entry.get("image-path") == str(image) for entry in profile.image_inventory()), "Failed image remains attached")
    require(profile.fingerprint(image) == evidence["image_fingerprint"], "Detached failed image identity changed")
    record = manifest["effaceable_ramdisk_v2_cleanup"]
    record.update(state="detached-unmodified-copy", detached_image_fingerprint=profile.fingerprint(image),
                  detached_image_sha256=stage.digest(image), root_identity_unchanged=True,
                  original_build_preserved=True)
    fresh_ns6(target, manifest)
    profile.write_manifest(target, manifest)
    return record


def prepare(vm_id, retry=False):
    target, manifest = validate(vm_id, retry)
    require(not SOURCE.is_symlink() and SOURCE.stat().st_size == SOURCE_BYTES and
            stage.digest(SOURCE) == SOURCE_SHA, "Pinned public restore RAMdisk differs")
    for name, pin in PINS.items():
        require(not (stage.PROVISIONING / name).is_symlink() and stage.digest(stage.PROVISIONING / name) == pin,
                "Reviewed effaceable initializer source differs")
    record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id,
              "data_profile_sha256": manifest["data_profile_sha256"], "state": "preparing", "prepared": False,
              "secure_root_policy_changed": False, "sep_restore_or_erase_requested": False,
              "fresh_ns6_zero_verified": True, "preloaded_controller_online_requested": True,
              "public_original_sha256": SOURCE_SHA, "source_sha256": dict(PINS), "ready": False,
              "build_revision": RETRY_BUILD if retry else ORIGINAL_BUILD}
    if retry:
        record["predecessor_cleanup_sha256"] = contract.canonical_hash(manifest["effaceable_ramdisk_v2_cleanup"])
        manifest["effaceable_ramdisk_v2_prewrite_failure"] = manifest["effaceable_ramdisk_v2"]
    stage.write_new(target / ("data-v2-effaceable-retry-intent.json" if retry else "data-v2-effaceable-intent.json"),
                    json.dumps(record, indent=2).encode())
    manifest["effaceable_ramdisk_v2"] = record
    profile.write_manifest(target, manifest)
    build = target / record["build_revision"]
    build.mkdir(mode=0o700)
    for name, pin in PINS.items():
        shutil.copyfile(stage.PROVISIONING / name, build / name)
        require(stage.digest(build / name) == pin, "Initializer source copy differs")
    ent = build / "effaceable-entitlements.plist"
    stage.write_new(ent, plistlib.dumps(ENTITLEMENTS))
    sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
    binary = build / "huntmob-initialize-effaceable"
    stage.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
               "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"',
               str(build / "initialize_effaceable_virtual_v1.c"), "-o", str(binary)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.huntmob.virtual-sep.effaceable-init",
               "--entitlements", str(ent), str(binary)])
    stage.run(["codesign", "--verify", "--strict", str(binary)])
    actual = stage.run(["codesign", "-d", "--entitlements", ":-", str(binary)])
    require(plistlib.loads(actual.stdout) == ENTITLEMENTS, "Unexpected RAMdisk initializer entitlements")
    base = target / "firmware/RestoreTrustCache"
    require(not base.is_symlink() and stage.digest(base) == BASE_TC_SHA, "Pinned public trustcache differs")
    tc = build / "RestoreTrustCache"
    stage.write_new(tc, stage.merged_trustcache(base.read_bytes(), [cdhash(binary)], vm_id))
    image = build / "RestoreRamDisk.raw"
    shutil.copyfile(SOURCE, image)
    require(stage.digest(image) == SOURCE_SHA and image.stat().st_ino != SOURCE.stat().st_ino and
            image.stat().st_nlink == 1, "RAMdisk must be an independent public-source copy")
    image_identity = profile.fingerprint(image)
    record.update(public_copy_fingerprint=image_identity, public_copy_sha256=SOURCE_SHA)
    profile.write_manifest(target, manifest)
    mount = build / "mount"
    mount.mkdir(mode=0o700)
    before = profile.whole_devices(profile.image_inventory())
    attached = profile.run_plist(["/usr/bin/hdiutil", "attach", "-nobrowse", "-noautoopen", "-noautofsck",
        "-owners", "off", "-imagekey", "diskimage-class=CRawDiskImage", "-plist", "-mountpoint", str(mount), str(image)])
    devices = profile.whole_devices([attached]) - before
    require(len(devices) == 1, "Ambiguous independent RAMdisk attachment")
    device = devices.pop()
    try:
        entries = [entry for entry in attached["system-entities"] if entry.get("mount-point") == str(mount)]
        require(len(entries) == 1 and entries[0].get("dev-entry") == device and
                entries[0].get("volume-kind") == "hfs", "Only this independent HFS RAMdisk may be modified")
        verify_ramdisk_attachment(image, image_identity, device, before, mount)
        require(stage.digest(stage.safe_path(mount, "usr/bin/nvmefwupdater")) == UTILITY_SHA,
                "Pinned original preloaded-controller utility differs")
        guest = stage.safe_path(mount, "usr/libexec/huntmob-initialize-effaceable")
        stage.write_new(guest, binary.read_bytes(), 0o755)
        stage.write_new(stage.safe_path(mount, "usr/libexec/huntmob-virtual-sep-v1"),
                        ("HUNTMOB VIRTUAL SEP MODEL V1\n" + vm_id + "\n").encode())
        daemon = {"Label": "com.huntmob.virtual-sep.effaceable-init",
                  "ProgramArguments": ["/usr/libexec/huntmob-initialize-effaceable"], "RunAtLoad": True,
                  "KeepAlive": False, "StandardOutPath": "/dev/console", "StandardErrorPath": "/dev/console"}
        stage.write_new(stage.safe_path(mount, "System/Library/LaunchDaemons/com.huntmob.effaceable-init.plist"),
                        plistlib.dumps(daemon), 0o644)
        for name in ("com.apple.restored_external.plist", "com.apple.KeyMaker.plist", "com.apple.PurpleReverseProxy.ramdisk.plist"):
            path = stage.safe_path(mount, "System/Library/LaunchDaemons/" + name)
            saved = path.read_bytes()
            stage.write_new(build / (name + ".original"), saved)
            value = plistlib.loads(saved)
            value["Disabled"] = True
            stage.replace_known(path, plistlib.dumps(value), stage.digest(path))
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        require(stage.digest(guest) == stage.digest(binary), "RAMdisk helper readback differs")
    finally:
        verify_ramdisk_attachment(image, image_identity, device, before, mount)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    require(stage.digest(SOURCE) == SOURCE_SHA, "Original public RAMdisk changed")
    fresh_ns6(target, manifest)
    record.update(state="prepared", prepared=True, ramdisk_path=str(image), ramdisk_sha256=stage.digest(image),
                  ramdisk_fingerprint=profile.fingerprint(image), trustcache_path=str(tc), trustcache_sha256=stage.digest(tc),
                  trustcache_fingerprint=profile.fingerprint(tc), helper_sha256=stage.digest(binary))
    profile.write_manifest(target, manifest)
    inputs(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("prepare", "cleanup-unmodified-copy", "retry-public-copy"), default="prepare")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(contract.plan(args.vm_uuid, args.action), indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    if args.action == "cleanup-unmodified-copy":
        result = cleanup_unmodified_copy(args.vm_uuid)
    else:
        result = prepare(args.vm_uuid, retry=args.action == "retry-public-copy")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
