#!/usr/bin/env python3
"""Append one empty own Update volume through the pinned stock guest API.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a no-op plan. Never starts
a guest, opens Keychain, mounts host Data, reformats a volume or resets keys.
"""
import argparse
import copy
import hashlib
import json
import plistlib
import re
import shutil
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
import stage_ios_virtual_data_v2_cold_read as cold
import stage_ios_virtual_data_v2_post_keybag as post
import stage_ios_virtual_data_v2_factorydata as factory
import inspect_ios_virtual_data_v2_mount_contract as inspection
from stage_ios_virtual_auxiliary import owned_container
from stage_ios_virtual_data_v2_auxiliary import checked_tc
from install_auxiliary_bootstrap_vm import cdhash

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-update-volume.v2"
INSPECTION = "data-v2-mount-contract-inspection-20261015-171758-f9339a5b"
INSPECTION_SHA = "29ada5045c94e8da022500dfdec9e92a4a8c458dc236256230b01ce52333323d"
NEWFS = "System/Library/Filesystems/apfs.fs/newfs_apfs"
NEWFS_SHA = "8dbd1aa6abbfbae8d0797e35b518441172f2a1e3b8bb6cb3f8f9186aa7dfe997"
APPEND_PROOF = contract.PROJECT / "artifacts/validation/ios-stock-append-update-volume-contract-v1-2026-10-15.json"
APPEND_PROOF_SHA = "c659a48adf6a5cf00019057f95fb8312df91946585548212a74c085f7bcc426a"
FSTAB_PROOF = contract.PROJECT / "artifacts/validation/ios-fstab-prefix-truncation-contract-v1-2026-10-15.json"
FSTAB_PROOF_SHA = "807951c68fb23f77db6e91b051734962e449dab437077a80166ba85f6d7f83b5"
PINS = {"append_update_virtual_v2.c": "7d7f94fcbee3695a2c3258f1ef98262811c658ab0adf525d727ab85f455dda4b",
        "append_update_policy_v2.h": "610f0a5c9fa8c9df3f204e3ca85f9cbad0a3b9ac5cd9ea93a6afb30c6d937b42",
        "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050"}
STOP_MARKER = "HuntMob: provisioning checkpoint ready; own DATA-v2 Update volume appended"


def require_sources(directory):
    for name, sha in PINS.items():
        post.verify_hash(directory / name, sha)


def verify_frozen_evidence(target, evidence):
    """Recheck immutable inputs after the temporary helper changes staging.

    The original inspector deliberately requires restored helper bindings.
    Never fabricate those bindings to reuse its pre-staging validator.
    """
    previous = {"contract_mode": "post-factory", "observation": inspection.POST_FACTORY_BASELINE,
        "observation_sha256": inspection.POST_FACTORY_BASELINE_SHA, "boot_log_sha256": inspection.POST_FACTORY_BOOT_LOG_SHA,
        "trace_log_sha256": inspection.POST_FACTORY_TRACE_LOG_SHA, "seed_observation_sha256": inspection.SEED_OBSERVATION_SHA,
        "seed_result_sha256": inspection.SEED_RESULT_SHA, "original_baseline_preserved": inspection.BASELINE}
    require(evidence == {"post_factory_failure": previous, "hardware_persistence_inspection": INSPECTION,
        "hardware_persistence_receipt_sha256": INSPECTION_SHA, "stock_append_contract_sha256": APPEND_PROOF_SHA,
        "fstab_prefix_contract_sha256": FSTAB_PROOF_SHA, "actual_stock_newfs_path": "/" + NEWFS,
        "actual_stock_newfs_sha256": NEWFS_SHA}, "Frozen append preparation evidence differs")
    for path, sha in ((target / inspection.POST_FACTORY_BASELINE / "observation.json", inspection.POST_FACTORY_BASELINE_SHA),
            (target / inspection.POST_FACTORY_BASELINE / "boot.log", inspection.POST_FACTORY_BOOT_LOG_SHA),
            (target / inspection.POST_FACTORY_BASELINE / "trace.log", inspection.POST_FACTORY_TRACE_LOG_SHA),
            (target / inspection.SEED_OBSERVATION / "observation.json", inspection.SEED_OBSERVATION_SHA),
            (target / "data-v2-factorydata-result.json", inspection.SEED_RESULT_SHA),
            (target / INSPECTION / "receipt.json", INSPECTION_SHA), (APPEND_PROOF, APPEND_PROOF_SHA), (FSTAB_PROOF, FSTAB_PROOF_SHA)):
        post.verify_hash(path, sha)


def preparation_evidence(target, manifest):
    previous = inspection.baseline(target, manifest, "post-factory")
    path = target / INSPECTION / "receipt.json"
    post.verify_hash(path, INSPECTION_SHA)
    receipt = contract.read_metadata(path)
    require(receipt.get("schema") == inspection.POST_FACTORY_SCHEMA and receipt.get("inspection_baseline") == "post-factory" and
            receipt.get("vm_uuid") == post.VM_UUID and receipt.get("data_uuid") == post.DATA_UUID and
            receipt.get("hardware_uuid") == inspection.HARDWARE_UUID and receipt.get("engine_binding") == manifest["engine_binding"] and
            receipt.get("state") == "completed-readonly-inspection" and
            all(receipt.get(key) is True for key in ("system_unmounted", "hardware_unmounted", "owned_device_detached")) and
            receipt.get("data_mounted") is False and receipt.get("hardware_file_contents_read") is False,
            "Exact post-factory readonly persistence inspection required")
    for relative in inspection.HARDWARE_PATHS[1:]:
        entry = receipt["metadata"]["Hardware"].get(relative, {})
        require(entry.get("exists") is True and entry.get("type") == "directory" and entry.get("mode") == "0o755" and
                entry.get("file_contents_read") is False, "FactoryData directory persistence must remain proven")
    post.verify_hash(APPEND_PROOF, APPEND_PROOF_SHA)
    append = contract.read_metadata(APPEND_PROOF)
    rules = append["confirmed"]
    require(append["sources"]["newfs_apfs"]["sha256"] == NEWFS_SHA and
            append["proposed_original_program_argv"][1:] == ["-A", "-o", "role=p", "-v", "Update", "/dev/disk0s1"] and
            rules["A_requires_existing_AppleAPFSContainer"] is True and rules["A_container_reformat_path_taken"] is False and
            rules["role_p_value"] == 192 and rules["role_u_value"] == 2 and rules["role_p_is_Update192_not_User2"] is True and
            append["operation_scope"]["creates_one_new_empty_volume_in_existing_container"] is True and
            append["operation_scope"]["reformats_existing_volume"] is False, "Pinned -A append/role=p contract differs")
    post.verify_hash(FSTAB_PROOF, FSTAB_PROOF_SHA)
    fstab = contract.read_metadata(FSTAB_PROOF)
    require(fstab["confirmed"]["update"]["role"] == 192 and fstab["confirmed"]["hardware"]["role"] == 320,
            "Pinned missing-Update fstab prerequisite proof differs")
    return {"post_factory_failure": previous, "hardware_persistence_inspection": INSPECTION,
            "hardware_persistence_receipt_sha256": INSPECTION_SHA, "stock_append_contract_sha256": APPEND_PROOF_SHA,
            "fstab_prefix_contract_sha256": FSTAB_PROOF_SHA, "actual_stock_newfs_path": "/" + NEWFS,
            "actual_stock_newfs_sha256": NEWFS_SHA}


def checked_updated_layout(container, whole_device, manifest, update_uuid=None, system_mount=None):
    """Six-volume exception owned by this adapter; global five-role guard stays strict."""
    adjusted = copy.deepcopy(container)
    volumes = adjusted.get("Volumes", [])
    require(len(volumes) == 6 and len({v.get("APFSVolumeUUID") for v in volumes}) == 6,
            "Exactly the five existing volumes and one distinct Update volume required")
    reference = adjusted.get("ContainerReference", "")
    matches = [v for v in volumes if v.get("DeviceIdentifier") == reference + "s6"]
    require(len(matches) == 1, "Only new slot6 may hold Update")
    added = matches[0]
    observed = cold.canonical_data_uuid(added.get("APFSVolumeUUID", ""))
    require(added.get("Name") == "Update" and added.get("Roles") == ["Update"] and
            added.get("Encryption") is False and not added.get("MountPoint") and
            (update_uuid is None or observed == update_uuid), "Update slot/role/name/UUID/encryption/mount differs")
    adjusted["Volumes"] = [v for v in volumes if v is not added]
    system = cold.checked_layout(adjusted, whole_device, manifest, post.DATA_UUID, system_mount=system_mount)
    return system, {key: added[key] for key in ("Name", "Roles", "DeviceIdentifier", "APFSVolumeUUID", "Encryption")}


def install(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    evidence = preparation_evidence(target, manifest)
    require(not manifest.get("update_volume_v2") and not (target / "data-v2-update-volume-intent.json").exists() and
            not (target / ".data-v2-launch.lock").exists(), "Update append is single-use and requires a stopped VM")
    require_sources(stage.PROVISIONING)
    _, tc = checked_tc(target, manifest)
    post.verify_hash(tc, factory.OLD_TC_SHA)
    require(manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] == factory.OLD_COLD_SHA,
            "Exact unused cold helper must precede temporary append helper")
    record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id, "data_uuid": post.DATA_UUID,
              "state": "preparing", "source_sha256": dict(PINS), "engine_binding": manifest["engine_binding"], "evidence": evidence,
              "original_helper_sha256": factory.OLD_COLD_SHA, "original_trustcache_sha256": factory.OLD_TC_SHA,
              "new_role": "Update", "new_role_number": 192, "new_slot": 6, "host_data_mounted": False,
              "root_accessed": False, "existing_volumes_reformatted": False, "keys_reinitialized": False,
              "shared_apfs_metadata_writes_expected": True, "native_ready": False, "ready": False}
    post.durable_intent(target / "data-v2-update-volume-intent.json", record)
    manifest["update_volume_v2"] = record
    profile.write_manifest(target, manifest)
    build = target / "data-v2-update-volume"
    build.mkdir(mode=0o700)
    for name, sha in PINS.items():
        shutil.copyfile(stage.PROVISIONING / name, build / name)
        post.verify_hash(build / name, sha)
    sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
    binary = build / "huntmob-prepare-userdata"
    stage.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
               "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"',
               str(build / "append_update_virtual_v2.c"), "-o", str(binary)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.huntmob.virtual-sep.update-append", str(binary)])
    stage.run(["codesign", "--verify", "--strict", str(binary)])
    actual = stage.run(["codesign", "-d", "--entitlements", ":-", str(binary)])
    require(not actual.stdout.strip(), "Stock append helper must gain no extra entitlements")
    original_tc = tc.read_bytes()
    stage.write_new(build / "original-VirtualTrustCache", original_tc)
    custom = post.add_only_shim_tc(original_tc, cdhash(binary), vm_id)
    record.update(helper_sha256=stage.digest(binary), helper_cdhash=cdhash(binary), trustcache_sha256=hashlib.sha256(custom).hexdigest())
    profile.write_manifest(target, manifest)
    device, before = stage.attach_backing(target, manifest)
    mount = target / "DataV2UpdateVolumeSystem"
    mounted = False
    try:
        layout = owned_container(device)
        system = cold.checked_layout(layout, device, manifest, post.DATA_UUID)
        record["existing_five_uuid_by_slot"] = {str(index): next(v["APFSVolumeUUID"] for v in layout["Volumes"] if
            v["DeviceIdentifier"] == layout["ContainerReference"] + "s" + str(index)) for index in range(1, 6)}
        profile.write_manifest(target, manifest)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        cold.validate_system_mount(mount, system, manifest)
        factory.unchanged_system(mount, manifest)
        post.verify_hash(stage.safe_path(mount, NEWFS), NEWFS_SHA)
        guest = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        stage.write_new(build / "original-huntmob-prepare-userdata", guest.read_bytes(), 0o755)
        post.verify_hash(build / "original-huntmob-prepare-userdata", factory.OLD_COLD_SHA)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.replace_known(guest, binary.read_bytes(), factory.OLD_COLD_SHA)
        post.verify_hash(guest, record["helper_sha256"])
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        stage.replace_known(tc, custom, factory.OLD_TC_SHA)
        post.verify_hash(tc, record["trustcache_sha256"])
        stage.write_new(stage.safe_path(mount, "usr/libexec/huntmob-prepare-data"), post.MARKER)
        factory.unchanged_system(mount, manifest, seeded_helper=record["helper_sha256"], marker_present=True)
        post.verify_hash(stage.safe_path(mount, NEWFS), NEWFS_SHA)
        cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID, system_mount=mount)
        cold.validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            cold.validate_system_mount(mount, system, manifest)
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="installed", owned_device_detached=True, existing_five_preserved_before_guest=True)
    manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] = record["helper_sha256"]
    manifest["virtual_staging"]["trustcache_sha256"] = record["trustcache_sha256"]
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    profile.write_manifest(target, manifest)
    return record


def validate_for_boot(target, manifest):
    record = manifest.get("update_volume_v2", {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] == post.VM_UUID and record.get("data_uuid") == post.DATA_UUID and
            record.get("state") == "installed" and record.get("source_sha256") == PINS and
            record.get("engine_binding") == manifest["engine_binding"] and record.get("existing_five_preserved_before_guest") is True and
            record.get("host_data_mounted") is False and
            record.get("helper_sha256") == manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] and
            record.get("trustcache_sha256") == manifest["virtual_staging"]["trustcache_sha256"], "Exactly the installed append-only helper is required")
    verify_frozen_evidence(target, record.get("evidence"))
    build = target / "data-v2-update-volume"
    require_sources(build)
    post.verify_hash(build / "huntmob-prepare-userdata", record["helper_sha256"])
    post.verify_hash(build / "original-huntmob-prepare-userdata", factory.OLD_COLD_SHA)
    post.verify_hash(build / "original-VirtualTrustCache", factory.OLD_TC_SHA)
    expected = post.add_only_shim_tc((build / "original-VirtualTrustCache").read_bytes(), record["helper_cdhash"], post.VM_UUID)
    require(hashlib.sha256(expected).hexdigest() == record["trustcache_sha256"], "Only this initializer may be added to the prior raw trustcache")
    return record


def classify_result(log):
    require(not any(text in log for text in ("HuntMob: Update append failure", "ClassD initialization", "fresh MKBCreateSystem",
                "synthetic canary=", "HuntMob: post-keybag", "HuntMob: cold Class C")), "Any append failure or Data/keybag/probe activity invalidates this isolated result")
    exits = re.findall(r"^HuntMob: Update append stock-newfs-exit=(-?\d+) signal=(\d+)$", log, re.MULTILINE)
    require(exits == [("0", "0")], "Exactly one unchanged stock append invocation must exit zero")
    ordered = ["HuntMob: invoking stock Data Protection verifier",
        "HuntMob: Update append preflight existing_slots=5 slot6_absent=1 slot7_absent=1",
        "HuntMob: Update append stock-newfs-start role=192 append_only=1",
        "HuntMob: Update append stock-newfs-exit=0 signal=0",
        "HuntMob: Update append slot6 ready existing_slots_preserved=5 slot7_absent=1", STOP_MARKER]
    require(all(log.count(value) == 1 for value in ordered) and
            [log.index(value) for value in ordered] == sorted(log.index(value) for value in ordered),
            "Existing five/new single slot/stock append/checkpoint order differs")
    return {"stock_append_completed": True, "existing_slots_preserved": 5, "new_slot": 6, "new_role_number": 192,
            "slot7_absent": True, "host_update_metadata_validation_required": True, "native_ready": False, "ready": False}


def consume(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    record = manifest.get("update_volume_v2", {})
    require(record.get("schema") == SCHEMA and record.get("vm_uuid") == vm_id and record.get("profile") == contract.PROFILE and
            record.get("state") == "launch-requested" and not (target / "data-v2-update-volume-result.json").exists() and
            not (target / "data-v2-update-volume-restore-intent.json").exists(), "One exact native append result may restore the temporary helper once")
    directory = Path(record.get("observation", ""))
    require(directory.parent == target, "Append observation belongs to another cohort")
    directory, proof, log, trace = cold.observation(target, manifest, directory.name)
    require(proof.get("update_volume_bootstrap_requested") is True and proof.get("post_keybag_class_c_read_requested") is False and
            proof.get("factorydata_seed_requested") is False and proof.get("stock_data_protection_verifier_invoked") is True,
            "Explicit isolated Update append observation required")
    result = classify_result(log)
    build = target / "data-v2-update-volume"
    require_sources(build)
    original, prior_tc = build / "original-huntmob-prepare-userdata", build / "original-VirtualTrustCache"
    post.verify_hash(original, factory.OLD_COLD_SHA)
    post.verify_hash(prior_tc, factory.OLD_TC_SHA)
    _, tc = checked_tc(target, manifest)
    post.verify_hash(tc, record["trustcache_sha256"])
    evidence = {"observation": directory.name, "observation_sha256": stage.digest(directory / "observation.json"),
        "boot_log_sha256": proof["boot.log_sha256"], "trace_log_sha256": proof["trace.log_sha256"], **result}
    post.durable_intent(target / "data-v2-update-volume-restore-intent.json", evidence)
    device, before = stage.attach_backing(target, manifest)
    mount = target / "DataV2UpdateVolumeRestore"
    mounted = False
    update = None
    try:
        container = owned_container(device)
        system, update = checked_updated_layout(container, device, manifest)
        observed_old = {str(i): next(v["APFSVolumeUUID"] for v in container["Volumes"] if v["DeviceIdentifier"] ==
            container["ContainerReference"] + "s" + str(i)) for i in range(1, 6)}
        require(observed_old == record["existing_five_uuid_by_slot"], "An existing volume UUID changed during append")
        record["created_update"] = update
        profile.write_manifest(target, manifest)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        cold.validate_system_mount(mount, system, manifest)
        factory.unchanged_system(mount, manifest, seeded_helper=record["helper_sha256"], marker_present=True)
        post.verify_hash(stage.safe_path(mount, NEWFS), NEWFS_SHA)
        guest = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.replace_known(guest, original.read_bytes(), record["helper_sha256"])
        post.verify_hash(guest, factory.OLD_COLD_SHA)
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        stage.replace_known(tc, prior_tc.read_bytes(), record["trustcache_sha256"])
        post.verify_hash(tc, factory.OLD_TC_SHA)
        marker = stage.safe_path(mount, "usr/libexec/huntmob-prepare-data")
        require(marker.read_bytes() == post.MARKER and not marker.is_symlink() and marker.lstat().st_nlink == 1, "Only our exact append marker may be removed")
        marker.unlink()
        factory.unchanged_system(mount, manifest)
        checked_updated_layout(owned_container(device), device, manifest, update["APFSVolumeUUID"], system_mount=mount)
        cold.validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            cold.validate_system_mount(mount, system, manifest)
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        checked_updated_layout(owned_container(device), device, manifest, update["APFSVolumeUUID"] if update else None)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="observed-original-restored", observation_evidence=evidence, original_helper_restored=True,
                  original_trustcache_restored=True, own_prepare_marker_removed=True, owned_device_detached=True,
                  existing_five_uuid_unchanged=True, created_update=update)
    manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] = factory.OLD_COLD_SHA
    manifest["virtual_staging"]["trustcache_sha256"] = factory.OLD_TC_SHA
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    post.durable_intent(target / "data-v2-update-volume-result.json", record)
    profile.write_manifest(target, manifest)
    return record


def checked_rearm_state(target, manifest):
    record, update = manifest.get("post_keybag_v2", {}), manifest.get("update_volume_v2", {})
    require(record.get("schema") == post.SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest.get("vm_uuid") == post.VM_UUID and record.get("data_uuid") == post.DATA_UUID and
            record.get("state") == "launch-requested" and record.get("observation") == str(target / inspection.POST_FACTORY_BASELINE) and
            record.get("factorydata_seed_rearmed") and not record.get("update_volume_rearmed") and
            not (target / "data-v2-post-keybag-update-rearm-intent.json").exists() and
            update.get("schema") == SCHEMA and update.get("profile") == contract.PROFILE and update.get("vm_uuid") == post.VM_UUID and
            update.get("data_uuid") == post.DATA_UUID and update.get("engine_binding") == manifest.get("engine_binding") and
            update.get("source_sha256") == PINS and update.get("state") == "observed-original-restored" and
            all(update.get(key) is True for key in ("original_helper_restored", "original_trustcache_restored",
                "own_prepare_marker_removed", "owned_device_detached", "existing_five_uuid_unchanged")) and
            manifest["virtual_staging"]["trustcache_sha256"] == factory.OLD_TC_SHA and
            manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] == factory.OLD_COLD_SHA,
            "One restored, metadata-validated Update append must precede this separate post-keybag retry")
    added = update.get("created_update", {})
    cold.canonical_data_uuid(added.get("APFSVolumeUUID", ""))
    require(added.get("Name") == "Update" and added.get("Roles") == ["Update"] and added.get("Encryption") is False,
            "Bound new Update identity required")
    existing = update.get("existing_five_uuid_by_slot", {})
    require(set(existing) == {str(index) for index in range(1, 6)} and
            added["APFSVolumeUUID"] not in existing.values() and re.fullmatch(r"disk[0-9]+s6", added.get("DeviceIdentifier", "")),
            "The bound Update must be a distinct sixth identity, preserving the original five")
    return record, update


def rearm_after_update_volume(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    preparation_evidence(target, manifest)
    record, update = checked_rearm_state(target, manifest)
    result = target / "data-v2-update-volume-result.json"
    require(contract.read_metadata(result) == update, "Restored Update result differs from manifest")
    require_sources(target / "data-v2-update-volume")
    directory = Path(update.get("observation", ""))
    require(directory.parent == target, "Update observation belongs to another cohort")
    directory, proof, log, trace = cold.observation(target, manifest, directory.name)
    classification = classify_result(log)
    require(proof.get("update_volume_bootstrap_requested") is True and proof.get("post_keybag_class_c_read_requested") is False and
            classification == {key: update["observation_evidence"][key] for key in classification} and
            stage.digest(directory / "observation.json") == update["observation_evidence"]["observation_sha256"],
            "Exact native append checkpoint must precede rearming")
    require("HuntMob: post-keybag" not in (target / inspection.POST_FACTORY_BASELINE / "boot.log").read_text(errors="replace"),
            "Previous post-keybag handler activity forbids this pre-handler retry")
    allowed = {inspection.BASELINE: inspection.BASELINE_SHA, inspection.POST_FACTORY_BASELINE: inspection.POST_FACTORY_BASELINE_SHA}
    for path in target.glob("data-v2-observation-*/observation.json"):
        value = contract.read_metadata(path)
        if value.get("post_keybag_class_c_read_requested") is True:
            require(path.parent.name in allowed and stage.digest(path) == allowed[path.parent.name], "Any additional post-keybag attempt forbids this one-time retry")
    evidence = {"previous_observation": record["observation"], "previous_receipt_sha256": inspection.POST_FACTORY_BASELINE_SHA,
                "update_volume_result_sha256": stage.digest(result), "maximum_retries": 1,
                "preserved_factory_rearm_sha256": contract.canonical_hash(record["factorydata_seed_rearmed"]),
                "root_recreated": False, "Data_or_keys_reinitialized": False, "native_ready": False, "ready": False}
    post.durable_intent(target / "data-v2-post-keybag-update-rearm-intent.json", evidence)
    # Preserve previous_observation and factorydata_seed_rearmed exactly.
    record.update(state="installed", previous_update_observation=record["observation"], update_volume_rearmed=evidence)
    profile.write_manifest(target, manifest)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("install", "consume", "rearm-after-update-volume"), default="install")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({**contract.plan(args.vm_uuid, "update-volume-" + args.action), "host_data_mounted": False,
                          "stock_append_only": True, "new_role_number": 192, "new_slot": 6}, indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    result = install(args.vm_uuid) if args.action == "install" else consume(args.vm_uuid) if args.action == "consume" else rearm_after_update_volume(args.vm_uuid)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
