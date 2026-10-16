#!/usr/bin/env python3
"""Stage/consume a bounded own Hardware directory seed, never Data or keys.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a no-op plan. A guest
initializer reproduces only five stock-proven missing Hardware directories.
"""
import argparse
import hashlib
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
import stage_ios_virtual_data_v2_cold_read as cold
import stage_ios_virtual_data_v2_post_keybag as post
import inspect_ios_virtual_data_v2_mount_contract as inspection
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_auxiliary import owned_container
from stage_ios_virtual_data_v2_auxiliary import checked_tc

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-factorydata-seed.v2"
INSPECTION = "data-v2-mount-contract-inspection-20261015-165806-d3701eaf"
INSPECTION_SHA = "acb106d4686283c5254b653d637f6fb088e85c86028dfe7cd9e5b89e27caf8e8"
STOCK_CONTRACT = contract.PROJECT / "artifacts/validation/ios-factorydata-directory-seed-contract-v1-2026-10-15.json"
STOCK_CONTRACT_SHA = "fb0ea69498288f6ebdc2aa09e586d3b2fea77b4afcd34a860c5fce47cb4e9232"
OLD_TC_SHA = "7125e16ef5b688b71ab1e482b4b8a94eb4f5fcdf937771209c06e875dd0a7d15"
OLD_COLD_SHA = "3967f6c4aedcfc71afe5ea5407c421d8986545b8686e38e37e1bdb571c513479"
PINS = {"prepare_factorydata_virtual_v2.c": "3ae790fcce381c4c8f393c09dfc0b50e0f60f89e378d8226624ca2c4738218e2",
        "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050"}
STOP_MARKER = "HuntMob: provisioning checkpoint ready; own DATA-v2 FactoryData metadata prepared"


def preparation_evidence(target, manifest):
    baseline = inspection.baseline(target, manifest)
    receipt_path = target / INSPECTION / "receipt.json"
    post.verify_hash(receipt_path, INSPECTION_SHA)
    value = contract.read_metadata(receipt_path)
    require(value.get("schema") == inspection.SCHEMA and value.get("vm_uuid") == post.VM_UUID and
            value.get("data_uuid") == post.DATA_UUID and value.get("hardware_uuid") == inspection.HARDWARE_UUID and
            value.get("engine_binding") == manifest["engine_binding"] and
            value.get("state") == "completed-readonly-inspection" and
            all(value.get(key) is True for key in ("system_unmounted", "hardware_unmounted", "owned_device_detached")) and
            value.get("data_mounted") is False and value.get("hardware_file_contents_read") is False,
            "Exact independent readonly Hardware/System mount inspection required")
    target_metadata = value["metadata"]["System"]["System/Library/Caches/com.apple.factorydata"]
    root_metadata = value["metadata"]["Hardware"][""]
    missing = value["metadata"]["Hardware"]["FactoryData"]
    require(target_metadata.get("exists") is True and target_metadata.get("type") == "directory" and
            target_metadata.get("mode") == "0o755" and target_metadata.get("directory_names") == [] and
            root_metadata.get("exists") is True and root_metadata.get("type") == "directory" and
            root_metadata.get("directory_names") == [] and missing.get("exists") is False and
            missing.get("first_missing_component") == "FactoryData", "Only the independently proven empty own Hardware may be seeded")
    post.verify_hash(STOCK_CONTRACT, STOCK_CONTRACT_SHA)
    source = contract.read_metadata(STOCK_CONTRACT)
    confirmed = source["confirmed"]
    require(confirmed["hardware_restore_mountpoint"] == "/mnt6" and
            confirmed["hardware_relative_path"] == "FactoryData/System/Library/Caches/com.apple.factorydata" and
            confirmed["creation_only_for_lstat_enoent"] is True and confirmed["new_directory_mode_octal"] == "0755" and
            confirmed["new_directory_uid"] == confirmed["new_directory_gid"] == 0 and
            confirmed["protection_class_argument"] == -1 and confirmed["copies_calibration_or_factorydata_content"] is False,
            "Stock directory seed semantics differ")
    return {"mount_failure": baseline, "readonly_inspection": INSPECTION, "readonly_inspection_sha256": INSPECTION_SHA,
            "stock_directory_contract_sha256": STOCK_CONTRACT_SHA, "hardware_uuid": inspection.HARDWARE_UUID}


def require_sources(directory):
    require(all(re.fullmatch(r"[0-9a-f]{64}", sha or "") for sha in PINS.values()), "Native seed source is not frozen/reviewed")
    for name, sha in PINS.items():
        post.verify_hash(directory / name, sha)


def unchanged_system(mount, manifest, *, seeded_helper=None, marker_present=False):
    record = manifest["post_keybag_v2"]
    for relative, expected in (("sbin/launchd", post.PUBLIC_PINS["sbin/launchd"]),
            ("System/Library/xpc/launchd.plist", post.PUBLIC_PINS["System/Library/xpc/launchd.plist"]),
            ("usr/libexec/keybagd", record["helper_sha256"]),
            ("usr/libexec/huntmob-original/keybagd", post.PUBLIC_PINS["usr/libexec/keybagd"]),
            ("usr/libexec/seputil", stage.STOCK_SHA), ("usr/libexec/huntmob-original/init_data_protection", stage.STOCK_SHA),
            ("usr/libexec/init_data_protection", record["wrapper_sha256"]),
            ("usr/libexec/huntmob-prepare-userdata", seeded_helper or OLD_COLD_SHA)):
        post.verify_hash(stage.safe_path(mount, relative), expected)
    marker = stage.safe_path(mount, "usr/libexec/huntmob-prepare-data")
    if marker_present:
        require(marker.is_file() and not marker.is_symlink() and marker.lstat().st_nlink == 1 and marker.read_bytes() == post.MARKER,
                "Only the exact owned temporary marker may exist")
    else:
        require(not marker.exists() and not marker.is_symlink(), "Owned preparation marker must be absent")


def install(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    evidence = preparation_evidence(target, manifest)
    require(not manifest.get("factorydata_seed_v2") and not (target / "data-v2-factorydata-intent.json").exists() and
            not (target / ".data-v2-launch.lock").exists(), "Hardware directory seed is single-use and requires a stopped VM")
    require_sources(stage.PROVISIONING)
    _, tc = checked_tc(target, manifest)
    post.verify_hash(tc, OLD_TC_SHA)
    require(manifest["post_keybag_v2"]["trustcache_sha256"] == OLD_TC_SHA and
            manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] == OLD_COLD_SHA,
            "Exact prior unused cold helper and post-keybag trustcache required")
    record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id, "data_uuid": post.DATA_UUID,
              "hardware_uuid": inspection.HARDWARE_UUID, "state": "preparing", "source_sha256": dict(PINS),
              "engine_binding": manifest["engine_binding"], "evidence": evidence,
              "original_helper_sha256": OLD_COLD_SHA, "original_trustcache_sha256": OLD_TC_SHA,
              "host_data_mounted": False, "root_accessed": False, "hardware_only_directory_seed": True,
              "calibration_or_factorydata_content_copied": False, "native_ready": False, "ready": False}
    post.durable_intent(target / "data-v2-factorydata-intent.json", record)
    manifest["factorydata_seed_v2"] = record
    profile.write_manifest(target, manifest)
    build = target / "data-v2-factorydata"
    build.mkdir(mode=0o700)
    for name, sha in PINS.items():
        shutil.copyfile(stage.PROVISIONING / name, build / name)
        post.verify_hash(build / name, sha)
    sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
    binary = build / "huntmob-prepare-userdata"
    stage.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
               "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"',
               str(build / "prepare_factorydata_virtual_v2.c"), "-o", str(binary)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.huntmob.virtual-sep.factorydata-seed", str(binary)])
    stage.run(["codesign", "--verify", "--strict", str(binary)])
    actual = stage.run(["codesign", "-d", "--entitlements", ":-", str(binary)])
    require(not actual.stdout.strip(), "Hardware mkdir initializer must gain no extra entitlements")
    original_tc = tc.read_bytes()
    stage.write_new(build / "original-VirtualTrustCache", original_tc)
    custom = post.add_only_shim_tc(original_tc, cdhash(binary), vm_id)
    record.update(helper_sha256=stage.digest(binary), helper_cdhash=cdhash(binary), trustcache_sha256=hashlib.sha256(custom).hexdigest())
    profile.write_manifest(target, manifest)
    device, before = stage.attach_backing(target, manifest)
    mount = target / "DataV2FactorySeedSystem"
    mounted = False
    try:
        system = cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        cold.validate_system_mount(mount, system, manifest)
        unchanged_system(mount, manifest)
        guest = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        stage.write_new(build / "original-huntmob-prepare-userdata", guest.read_bytes(), 0o755)
        post.verify_hash(build / "original-huntmob-prepare-userdata", OLD_COLD_SHA)
        preserved_marker = target / "data-v2-post-keybag/original-prepare-data-marker"
        require(preserved_marker.read_bytes() == post.MARKER and not preserved_marker.is_symlink(), "Preserved own marker bytes differ")
        mnt6 = stage.safe_path(mount, "mnt6")
        if not mnt6.exists() and not mnt6.is_symlink():
            mnt6.mkdir(mode=0o755)
            mnt6.chmod(0o755)
            record["system_mnt6_created"] = True
        require(mnt6.is_dir() and not mnt6.is_symlink() and stat.S_IMODE(mnt6.lstat().st_mode) == 0o755 and
                not any(mnt6.iterdir()), "System /mnt6 must be an empty ordinary mode0755 directory")
        record["system_mnt6_empty_verified"] = True
        profile.write_manifest(target, manifest)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.replace_known(guest, binary.read_bytes(), OLD_COLD_SHA)
        post.verify_hash(guest, record["helper_sha256"])
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        stage.replace_known(tc, custom, OLD_TC_SHA)
        post.verify_hash(tc, record["trustcache_sha256"])
        stage.write_new(stage.safe_path(mount, "usr/libexec/huntmob-prepare-data"), post.MARKER)
        unchanged_system(mount, manifest, seeded_helper=record["helper_sha256"], marker_present=True)
        cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID, system_mount=mount)
        cold.validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            cold.validate_system_mount(mount, system, manifest)
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="installed", owned_device_detached=True)
    manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] = record["helper_sha256"]
    manifest["virtual_staging"]["trustcache_sha256"] = record["trustcache_sha256"]
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    profile.write_manifest(target, manifest)
    return record


def validate_for_boot(target, manifest):
    record = manifest.get("factorydata_seed_v2", {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] == post.VM_UUID and record.get("data_uuid") == post.DATA_UUID and
            record.get("hardware_uuid") == inspection.HARDWARE_UUID and record.get("state") == "installed" and
            record.get("source_sha256") == PINS and record.get("engine_binding") == manifest["engine_binding"] and
            record.get("system_mnt6_empty_verified") is True and record.get("host_data_mounted") is False and
            record.get("helper_sha256") == manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] and
            record.get("trustcache_sha256") == manifest["virtual_staging"]["trustcache_sha256"],
            "Exactly the installed own Hardware initializer is required")
    require(record.get("evidence") == preparation_evidence(target, manifest), "FactoryData source absence/stock proof changed")
    build = target / "data-v2-factorydata"
    require_sources(build)
    post.verify_hash(build / "huntmob-prepare-userdata", record["helper_sha256"])
    post.verify_hash(build / "original-huntmob-prepare-userdata", OLD_COLD_SHA)
    post.verify_hash(build / "original-VirtualTrustCache", OLD_TC_SHA)
    expected_tc = post.add_only_shim_tc((build / "original-VirtualTrustCache").read_bytes(), record["helper_cdhash"], post.VM_UUID)
    require(hashlib.sha256(expected_tc).hexdigest() == record["trustcache_sha256"], "Initializer trustcache must retain all prior entries plus only this initializer")
    return record


def classify_result(log):
    require(not any(value in log for value in ("HuntMob: FactoryData failure", "ClassD initialization", "fresh MKBCreateSystem",
                "synthetic canary=", "HuntMob: post-keybag", "HuntMob: cold Class C")),
            "Any initializer failure, Data provision/probe or keybag-handler activity forbids this isolated seed result")
    commands = re.findall(r"^HuntMob: FactoryData command stage=([a-z-]+) exit=(-?\d+) signal=(\d+)$", log, re.MULTILINE)
    require(commands == [("mount-hardware", "0", "0"), ("unmount-hardware", "0", "0")],
            "Exactly one successful Hardware mount/unmount pair required")
    directories = re.findall(r"^HuntMob: FactoryData directory index=(\d+) created=([01]) metadata_valid=([01])$", log, re.MULTILINE)
    require(directories == [(str(index), "1", "1") for index in range(1, 6)],
            "The independently observed empty Hardware requires five newly created ordered directories")
    ordered = ["HuntMob: invoking stock Data Protection verifier",
               "HuntMob: FactoryData command stage=mount-hardware exit=0 signal=0",
               "HuntMob: FactoryData Hardware UUID exact matched"]
    ordered += ["HuntMob: FactoryData directory index=" + str(index) + " created=1 metadata_valid=1" for index in range(1, 6)]
    ordered += ["HuntMob: FactoryData metadata verified directories=5 mode=0755 uid=0 gid=0",
                "HuntMob: FactoryData command stage=unmount-hardware exit=0 signal=0",
                "HuntMob: FactoryData Hardware unmounted", STOP_MARKER]
    require(all(log.count(value) == 1 for value in ordered) and
            [log.index(value) for value in ordered] == sorted(log.index(value) for value in ordered),
            "Stock verifier/Hardware identity/root metadata/unmount/checkpoint sequence differs")
    return {"factorydata_directories_prepared": True, "directory_count": 5, "mode": "0755", "uid": 0, "gid": 0,
            "hardware_unmounted": True, "hardware_only_directory_seed": True, "native_ready": False, "ready": False}


def consume(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    record = manifest.get("factorydata_seed_v2", {})
    require(record.get("schema") == SCHEMA and record.get("vm_uuid") == vm_id and record.get("profile") == contract.PROFILE and
            record.get("state") == "launch-requested" and not (target / "data-v2-factorydata-result.json").exists() and
            not (target / "data-v2-factorydata-restore-intent.json").exists(), "One clean native initializer result may restore prior helper once")
    directory = Path(record.get("observation", ""))
    require(directory.parent == target, "Initializer observation belongs to another cohort")
    directory, proof, log, trace = cold.observation(target, manifest, directory.name)
    require(proof.get("factorydata_seed_requested") is True and proof.get("post_keybag_class_c_read_requested") is False and
            proof.get("stock_data_protection_verifier_invoked") is True, "Explicit isolated Hardware initializer observation required")
    result = classify_result(log)
    build = target / "data-v2-factorydata"
    original = build / "original-huntmob-prepare-userdata"
    previous_tc = build / "original-VirtualTrustCache"
    post.verify_hash(original, OLD_COLD_SHA)
    post.verify_hash(previous_tc, OLD_TC_SHA)
    require_sources(build)
    _, tc = checked_tc(target, manifest)
    post.verify_hash(tc, record["trustcache_sha256"])
    evidence = {"observation": directory.name, "observation_sha256": stage.digest(directory / "observation.json"),
                "boot_log_sha256": proof["boot.log_sha256"], "trace_log_sha256": proof["trace.log_sha256"], **result}
    post.durable_intent(target / "data-v2-factorydata-restore-intent.json", evidence)
    device, before = stage.attach_backing(target, manifest)
    mount = target / "DataV2FactorySeedRestore"
    mounted = False
    try:
        system = cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        cold.validate_system_mount(mount, system, manifest)
        unchanged_system(mount, manifest, seeded_helper=record["helper_sha256"], marker_present=True)
        guest = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.replace_known(guest, original.read_bytes(), record["helper_sha256"])
        post.verify_hash(guest, OLD_COLD_SHA)
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        stage.replace_known(tc, previous_tc.read_bytes(), record["trustcache_sha256"])
        post.verify_hash(tc, OLD_TC_SHA)
        marker = stage.safe_path(mount, "usr/libexec/huntmob-prepare-data")
        require(marker.read_bytes() == post.MARKER and not marker.is_symlink() and marker.lstat().st_nlink == 1, "Only our exact temporary marker may be removed")
        marker.unlink()
        unchanged_system(mount, manifest)
        cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID, system_mount=mount)
        cold.validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            cold.validate_system_mount(mount, system, manifest)
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="observed-original-restored", observation_evidence=evidence, original_helper_restored=True,
                  original_trustcache_restored=True, own_prepare_marker_removed=True, owned_device_detached=True)
    manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] = OLD_COLD_SHA
    manifest["virtual_staging"]["trustcache_sha256"] = OLD_TC_SHA
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    post.durable_intent(target / "data-v2-factorydata-result.json", record)
    profile.write_manifest(target, manifest)
    return record


def checked_rearm_state(target, manifest):
    record = manifest["post_keybag_v2"]
    seeded = manifest.get("factorydata_seed_v2", {})
    require(record.get("schema") == post.SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest.get("vm_uuid") == post.VM_UUID and record.get("data_uuid") == post.DATA_UUID and
            record.get("state") == "launch-requested" and record.get("observation") == str(target / inspection.BASELINE) and
            seeded.get("schema") == SCHEMA and seeded.get("state") == "observed-original-restored" and
            seeded.get("vm_uuid") == manifest["vm_uuid"] and seeded.get("profile") == contract.PROFILE and seeded.get("source_sha256") == PINS and
            all(seeded.get(key) is True for key in ("original_helper_restored", "original_trustcache_restored", "own_prepare_marker_removed", "owned_device_detached")) and
            not record.get("factorydata_seed_rearmed") and not (target / "data-v2-post-keybag-factory-rearm-intent.json").exists() and
            manifest["virtual_staging"]["trustcache_sha256"] == OLD_TC_SHA and
            manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] == OLD_COLD_SHA,
            "A single restored Hardware seed checkpoint must precede rearming post-keybag")
    return record, seeded


def rearm_after_factory_seed(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    preparation_evidence(target, manifest)
    record, seeded = checked_rearm_state(target, manifest)
    require_sources(target / "data-v2-factorydata")
    result_file = target / "data-v2-factorydata-result.json"
    require(contract.read_metadata(result_file) == seeded, "Restored initializer result differs from manifest")
    directory = Path(seeded.get("observation", ""))
    require(directory.parent == target, "Seed checkpoint belongs to another cohort")
    directory, proof, log, trace = cold.observation(target, manifest, directory.name)
    classification = classify_result(log)
    require(proof.get("factorydata_seed_requested") is True and proof.get("post_keybag_class_c_read_requested") is False and
            classification == {key: seeded["observation_evidence"][key] for key in classification} and
            stage.digest(directory / "observation.json") == seeded["observation_evidence"]["observation_sha256"],
            "Only the exact clean seeded/restored checkpoint may rearm post-keybag")
    previous_log = (target / inspection.BASELINE / "boot.log").read_text(errors="replace")
    require("HuntMob: post-keybag" not in previous_log, "Previous post-keybag handler activity forbids this pre-handler retry")
    for directory in target.glob("data-v2-observation-*"):
        receipt = directory / "observation.json"
        if receipt.exists():
            proof = contract.read_metadata(receipt)
            if proof.get("post_keybag_class_c_read_requested") is True:
                require(directory.name == inspection.BASELINE and stage.digest(receipt) == inspection.BASELINE_SHA,
                        "Any other post-keybag attempt forbids automatic rearming")
    evidence = {"previous_observation": record["observation"], "previous_receipt_sha256": inspection.BASELINE_SHA,
                "factorydata_result_sha256": stage.digest(result_file), "maximum_retries": 1,
                "root_recreated": False, "Data_or_keys_reinitialized": False, "native_ready": False, "ready": False}
    post.durable_intent(target / "data-v2-post-keybag-factory-rearm-intent.json", evidence)
    record.update(state="installed", previous_observation=record["observation"], factorydata_seed_rearmed=evidence)
    profile.write_manifest(target, manifest)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("install", "consume", "rearm-after-factory-seed"), default="install")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({**contract.plan(args.vm_uuid, "factorydata-" + args.action), "host_data_mounted": False,
                          "hardware_only_directory_seed": True}, indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    result = install(args.vm_uuid) if args.action == "install" else consume(args.vm_uuid) if args.action == "consume" else rearm_after_factory_seed(args.vm_uuid)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
