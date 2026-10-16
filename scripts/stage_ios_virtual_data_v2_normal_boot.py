#!/usr/bin/env python3
"""Restore stock boot programs/trustcache after the scoped persistent-read proof.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a no-op plan. No VM starts,
Keychain access, host Data mount/unlock, volume deletion or reformat occurs.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import struct
from contextlib import contextmanager
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
import stage_ios_virtual_data_v2_cold_read as cold
import stage_ios_virtual_data_v2_post_keybag as post
import stage_ios_virtual_data_v2_factorydata as factory
import stage_ios_virtual_data_v2_update_volume as update
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_auxiliary import owned_container
from stage_ios_virtual_data_v2_auxiliary import BASE_TC_SHA, checked_tc

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-normal-boot.v2"
OBSERVATION = "data-v2-observation-20261015-173327"
OBSERVATION_SHA = "40d06115a9cc28ef529bce123d664a5126c4ff0ce129536c8d4adf5db01a6e5f"
BOOT_LOG_SHA = "b96cd577290948d195a77bb0b74db7da9af5385b6d6a8c06b1539120a1b42d16"
TRACE_LOG_SHA = "b9c71333f0c55eca9ea70d1c3c32c1095f69a2c56e99a4ef23423cbaec6601c5"
SCAN = "data-v2-storage-scan-20261015-173521-8530e6c8"
SCAN_SHA = "b119f4f743e9e880dba37905950ab4e655a6148e54c54cc9de687fcc5d0c43cd"
UPDATE_UUID = "158C647A-0D5A-495B-A77F-2DBF56236B6C"
LOADER_SHA = "2de0486db2cada9f33d13dccfb573f1c8ee3cc3c0774c281642672080088760a"
FIRST_NORMAL = "data-v2-observation-20261015-175232"
FIRST_NORMAL_SHA = "2692abcf540473a5092c7651cf183f421808af3321c339b57c58d098e9ea7a4d"
FIRST_NORMAL_BOOT_SHA = "7a9b3d4e91568cec776c165653961fb3d713a3bdd12bb5d3a64e8f341e05eb90"
FIRST_NORMAL_TRACE_SHA = "7e6a88735b53922b5f08bb7465be5781408a4c30fe16e5cc3abac762390b8043"
REFRESH_SCAN = "data-v2-storage-scan-20261015-175643-580aeec0"
REFRESH_SCAN_SHA = "608ee49647ea8e443e313a681139c203a92be8a51f62854f0e54d6d57144224f"
FORBIDDEN_MARKERS = ("usr/libexec/huntmob-prepare-data", "usr/libexec/huntmob-restore-sep.img4")


def verified_scan(target, manifest, current_identity, *, scan_mode="initial"):
    require(scan_mode in ("initial", "refresh-current", "historical-after-normal"), "Unknown normal-boot scan contract")
    if scan_mode == "historical-after-normal":
        # The exception is reachable only through the pinned completed normal
        # boot and a fresh all-nine identity scan. It is never an install bypass.
        headless_refresh_evidence(target, manifest, for_rearm=False)
    scan_name, expected_sha = (REFRESH_SCAN, REFRESH_SCAN_SHA) if scan_mode == "refresh-current" else (SCAN, SCAN_SHA)
    path = target / scan_name / "receipt.json"
    post.verify_hash(path, expected_sha)
    value = contract.read_metadata(path)
    require(value.get("schema") == "huntmob.virtual-sep-data-storage-probe-scan.v1" and value.get("vm_uuid") == post.VM_UUID and
            value.get("engine_binding") == manifest["engine_binding"] and value.get("data_profile") == contract.PROFILE and
            value.get("state") == "completed-readonly-scan" and value.get("total_matches") == 0 and value.get("public_probe_absent") is True and
            value.get("global_source_identity_unchanged") is True and value.get("host_backings_not_attached_before_after") is True and
            all(value.get(key) is False for key in ("Data_mounted_or_unlocked", "backings_written", "root_accessed", "keychain_accessed", "vm_started")),
            "Exact completed nine-backing readonly scan with zero marker matches required")
    scoped = value.get("scoped_native_cold_read", {})
    require(scoped == {"observation": str(target / OBSERVATION), "observation_sha256": OBSERVATION_SHA,
            "boot_log_sha256": BOOT_LOG_SHA, "trace_log_sha256": TRACE_LOG_SHA, "result": "afu-read-match", "validated": True},
            "The raw scan must bind this actual persistent Class C read")
    require(set(value.get("backings", {})) == set(profile.SIZES) and
            value.get("total_bytes_scanned") == sum(profile.SIZES.values()), "Full extent of all nine owned backings must be scanned")
    for name, size in profile.SIZES.items():
        entry = value["backings"][name]
        before, after = entry["identity_before"], entry["identity_after"]
        require(before == after and entry.get("bytes_scanned") == size and
                {key: after[key] for key in ("device", "inode", "bytes", "links")} == manifest["backings"][name],
                "Scan must preserve the exact cohort geometry/identity")
        require(set(entry.get("matches", {})) == {"ascii_hex64", "decoded32"} and
                all(pattern.get("count") == 0 and pattern.get("offsets") == [] and pattern.get("offsets_truncated") is False
                    for pattern in entry["matches"].values()), "Any backing marker hit or partial search forbids staging")
        if scan_mode != "historical-after-normal" and (scan_mode == "refresh-current" or current_identity or name != "namespace-1.raw"):
            observed = (target / name).lstat()
            require((observed.st_dev, observed.st_ino, observed.st_size, observed.st_nlink, observed.st_mtime_ns, observed.st_ctime_ns) ==
                    (after["device"], after["inode"], after["bytes"], after["links"], after["mtime_ns"], after["ctime_ns"]),
                    "Backing changed since the final readonly scan")
    return {"receipt": scan_name, "receipt_sha256": expected_sha, "total_matches": 0, "scoped_native_cold_read_validated": True}


def preparation_evidence(target, manifest, current_identity=True, *, owned_launch_lock=None, scan_mode="initial"):
    lock = target / ".data-v2-launch.lock"
    if owned_launch_lock is None:
        require(not lock.exists() and not lock.is_symlink(), "A launch is active or unresolved; refuse preparation")
    else:
        # Use the shared contract's descriptor/inode/mode/owner check, rather
        # than treating a caller-supplied boolean as ownership of the lock.
        contract.validate_manifest(target, manifest, owned_launch_lock=owned_launch_lock)
    record = manifest.get("post_keybag_v2", {})
    require(manifest.get("vm_uuid") == post.VM_UUID and manifest.get("root_provisioned") is True and
            record.get("schema") == post.SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == post.VM_UUID and record.get("data_uuid") == post.DATA_UUID and record.get("state") == "observed" and
            record.get("observation") == str(target / OBSERVATION) and record.get("result") == "afu-read-match" and
            record.get("read_validated") is True and record.get("cold_read_validated") is True and
            record.get("observation_sha256") == OBSERVATION_SHA,
            "Actual scoped persistent Class C read must precede stock normal boot")
    require(contract.read_metadata(target / "data-v2-post-keybag-result.json") == record, "Consumed native post-keybag result differs from manifest")
    for key in ("factorydata_seed_v2", "update_volume_v2"):
        previous = manifest.get(key, {})
        require(previous.get("state") == "observed-original-restored" and previous.get("vm_uuid") == post.VM_UUID and
                all(previous.get(flag) is True for flag in ("original_helper_restored", "original_trustcache_restored",
                    "own_prepare_marker_removed", "owned_device_detached")), "Prerequisite helper/trustcache restoration is incomplete")
    require(manifest["update_volume_v2"].get("created_update", {}).get("APFSVolumeUUID") == UPDATE_UUID,
            "Exact newly validated Update UUID required")
    directory, proof, log, trace = cold.observation(target, manifest, OBSERVATION)
    require(stage.digest(directory / "observation.json") == OBSERVATION_SHA and proof.get("post_keybag_class_c_read_requested") is True and
            proof["boot.log_sha256"] == BOOT_LOG_SHA and proof["trace.log_sha256"] == TRACE_LOG_SHA and
            post.classify_result(log)["read_validated"] is True, "Exact stock keybag exit0/AFU/digest/read checkpoint must remain verified")
    loader = contract.CANDIDATE / "source/hw/arm/apple-silicon/boot.c"
    post.verify_hash(loader, LOADER_SHA)
    scan = verified_scan(target, manifest, current_identity, scan_mode=scan_mode)
    return {"native_cold_read_observation": OBSERVATION, "native_cold_read_sha256": OBSERVATION_SHA,
            "boot_log_sha256": BOOT_LOG_SHA, "trace_log_sha256": TRACE_LOG_SHA,
            "raw_scan": scan, "bound_im4p_loader_sha256": LOADER_SHA,
            "stock_original_im4p_sha256": BASE_TC_SHA}


def require_absent_markers(mount):
    for relative in FORBIDDEN_MARKERS:
        path = stage.safe_path(mount, relative)
        require(not path.exists() and not path.is_symlink(), "An own restore/preparation marker forbids stock normal boot")


def require_stock_inode_preserved(before, after):
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and not (before.st_mode & 0o022) and
            (after.st_dev, after.st_ino, after.st_mode, after.st_nlink) ==
            (before.st_dev, before.st_ino, before.st_mode, 1), "Stock keybag inode/mode changed during restoration")


def headless_refresh_evidence(target, manifest, *, for_rearm):
    """One explicitly bounded host display retry, after a fresh complete scan."""
    record = manifest.get("normal_boot_v2", {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest.get("vm_uuid") == post.VM_UUID and record.get("data_uuid") == post.DATA_UUID and
            record.get("update_uuid") == UPDATE_UUID and record.get("engine_binding") == manifest["engine_binding"] and
            record.get("observation") == str(target / FIRST_NORMAL) and
            record.get("state") == ("launch-requested" if for_rearm else "planned"),
            "Exactly the first stopped stock normal observation is eligible for headless refresh")
    intent = target / "data-v2-normal-headless-refresh-intent.json"
    if for_rearm:
        require(not record.get("headless_refresh_rearmed") and not intent.exists() and not intent.is_symlink(),
                "Headless display refresh can be rearmed only once")
    else:
        require(record.get("headless_refresh_hz_required") == 10 and record.get("headless_refresh_rearmed"),
                "The rearmed plan requires exactly 10 Hz host refresh")
    directory = target / FIRST_NORMAL
    proof = contract.read_metadata(directory / "observation.json")
    post.verify_hash(directory / "observation.json", FIRST_NORMAL_SHA)
    post.verify_hash(directory / "boot.log", FIRST_NORMAL_BOOT_SHA)
    post.verify_hash(directory / "trace.log", FIRST_NORMAL_TRACE_SHA)
    require(proof.get("schema") == "huntmob.virtual-sep-data-observation.v2" and proof.get("vm_uuid") == post.VM_UUID and
            proof.get("engine_binding") == manifest["engine_binding"] and proof.get("data_profile") == contract.PROFILE and
            proof.get("normal_boot_requested") is True and proof.get("stop_reason") == "bounded-observation-ended" and
            proof.get("normal_boot_log_observed") is True and proof.get("stock_early_boot_marker_observed") is True and
            proof.get("panic_observed") is False and proof.get("qmp_quit_requested") is True and proof.get("qmp_quit_accepted") is True and
            proof.get("exit_code") == 0 and proof.get("checkpoint_observed") is False and proof.get("aess_command_count", 0) > 0 and
            proof.get("boot.log_sha256") == FIRST_NORMAL_BOOT_SHA and proof.get("trace.log_sha256") == FIRST_NORMAL_TRACE_SHA and
            proof.get("virtual_mpe_memory_fault_observed") is False and proof.get("mpe_rejected_revocation_observed") is False,
            "The first stock normal boot must be clean, bounded and stopped before this retry")
    require(all(proof.get(key) == 0 for key in ("aess_rejected_command_count", "nvme_error_completion_count",
            "protected_io_rejection_count", "protected_gate_rejection_count")), "Crypto/storage failures forbid a display-only retry")
    command = proof.get("command", [])
    require(isinstance(command, list) and command.count("-display") == 1 and
            command.index("-display") + 1 < len(command) and command[command.index("-display") + 1] == "none",
            "Only the pinned headless display configuration is eligible")
    log = (directory / "boot.log").read_text(errors="replace")
    require(classify_result(log)["stock_early_boot_marker_observed"] is True, "Actual stock early boot marker required")
    current_scan = verified_scan(target, manifest, True, scan_mode="refresh-current")
    evidence = {"previous_observation": str(directory), "previous_observation_sha256": FIRST_NORMAL_SHA,
                "previous_boot_log_sha256": FIRST_NORMAL_BOOT_SHA, "previous_trace_log_sha256": FIRST_NORMAL_TRACE_SHA,
                "current_scan": current_scan, "reason": "bounded-host-headless-display-refresh",
                "headless_refresh_hz_required": 10, "maximum_retries": 1, "guest_or_engine_modified": False,
                "backings_modified_by_rearm": False, "root_accessed": False, "native_ready": False, "ready": False}
    if not for_rearm:
        require(record.get("headless_refresh_rearmed") == evidence and contract.read_metadata(intent) == evidence,
                "One-time display refresh intent differs from the pinned completed-boot/scan chain")
    return evidence


def rearm_headless_refresh(vm_id):
    target = contract.target_for(vm_id)
    with exclusive_staging_lock(target) as descriptor:
        manifest = contract.validate_manifest(target, owned_launch_lock=descriptor)
        contract.verify_engine(manifest)
        evidence = headless_refresh_evidence(target, manifest, for_rearm=True)
        historical = preparation_evidence(target, manifest, False, owned_launch_lock=descriptor,
                                          scan_mode="refresh-current")
        # Keep original cold/scan evidence immutable; the newer scan establishes
        # the allowed post-native-write identities instead of rewriting history.
        original = manifest["normal_boot_v2"]["evidence"]
        require({key: value for key, value in historical.items() if key != "raw_scan"} ==
                {key: value for key, value in original.items() if key != "raw_scan"} and
                original["raw_scan"] == {"receipt": SCAN, "receipt_sha256": SCAN_SHA, "total_matches": 0,
                    "scoped_native_cold_read_validated": True}, "Original scoped cold/scan evidence must remain unchanged")
        record = manifest["normal_boot_v2"]
        require(all(record.get(key) is True for key in ("stock_keybag_same_inode_restored", "stock_data_protection_restored",
                    "all_owned_helpers_removed_from_trustcache", "own_restore_preparation_markers_absent", "owned_device_detached", "existing_six_volumes_preserved")) and
                record.get("identity_binding") == {key: manifest.get(key) for key in ("keychain_service", "keychain_account", "crypto_provider_source_sha256", "kdf_id")} and
                manifest["virtual_staging"]["helper_sha256"]["init_data_protection"] == stage.STOCK_SHA and
                manifest["virtual_staging"]["trustcache_sha256"] == BASE_TC_SHA,
                "Stock boot restoration and root/KDF identity must stay unchanged")
        verify_stock_restore_artifacts(target, manifest, record)
        # No mount, guest, engine mutation or backing write: only a durable plan.
        post.durable_intent(target / "data-v2-normal-headless-refresh-intent.json", evidence)
        record.update(state="planned", previous_normal_observation=str(target / FIRST_NORMAL),
                      headless_refresh_hz_required=10, headless_refresh_rearmed=evidence)
        profile.write_manifest(target, manifest)
        return evidence


def stock_tc_transition(current_raw, base_im4p, owned_hashes):
    require(hashlib.sha256(base_im4p).hexdigest() == BASE_TC_SHA and len(current_raw) >= 24 and
            struct.unpack_from("<I", current_raw)[0] == 1, "Exact stock IM4P and prior raw helper cache required")
    count, = struct.unpack_from("<I", current_raw, 20)
    require(count < 4096 and len(current_raw) == 24 + 22 * count, "Malformed prior raw helper trustcache")
    old = {current_raw[24 + i * 22:24 + (i + 1) * 22] for i in range(count)}
    base = stage.trustcache_entries(base_im4p)
    require(len(owned_hashes) == 3 and len(set(owned_hashes)) == 3 and
            all(re.fullmatch(r"[0-9a-f]{40}", value or "") for value in owned_hashes), "Exactly the three owned helper CDHashes required")
    removed = {bytes.fromhex(value) + b"\x02\x00" for value in owned_hashes}
    require(base.issubset(old) and old - base == removed and not any(entry[:20].hex() in owned_hashes for entry in base),
            "Only the three owned helper entries may be removed; all stock entries must remain")
    # Return the ORIGINAL IM4P, retaining its raw payload UUID/duplicate/order.
    return base_im4p


def checked_stock_system(mount, manifest, normal=False):
    require_absent_markers(mount)
    for relative, expected in (("sbin/launchd", post.PUBLIC_PINS["sbin/launchd"]),
            ("System/Library/xpc/launchd.plist", post.PUBLIC_PINS["System/Library/xpc/launchd.plist"]),
            ("usr/libexec/seputil", stage.STOCK_SHA), ("usr/libexec/huntmob-original/init_data_protection", stage.STOCK_SHA),
            ("usr/libexec/huntmob-prepare-userdata", factory.OLD_COLD_SHA),
            ("usr/libexec/init_data_protection", stage.STOCK_SHA if normal else manifest["post_keybag_v2"]["wrapper_sha256"]),
            ("usr/libexec/keybagd", post.PUBLIC_PINS["usr/libexec/keybagd"] if normal else manifest["post_keybag_v2"]["helper_sha256"])):
        post.verify_hash(stage.safe_path(mount, relative), expected)
    original = stage.safe_path(mount, "usr/libexec/huntmob-original/keybagd")
    if normal:
        require(not original.exists() and not original.is_symlink(), "Stock keybag inode must be back at its original boot path")
    else:
        post.verify_hash(original, post.PUBLIC_PINS["usr/libexec/keybagd"])


@contextmanager
def exclusive_staging_lock(target):
    """Share the launcher's atomic exclusion; never steal or reap stale locks.

    A crash/SIGKILL leaves the lock and any durable staging intent in place.
    Recovery requires an explicit ownership/state audit, never a PID guess.
    """
    require(target.is_dir() and not target.is_symlink(), "Independent owned staging directory required")
    path = target / ".data-v2-launch.lock"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        value = (str(os.getpid()) + "\n").encode()
        require(os.write(descriptor, value) == len(value), "Short exclusive staging lock write")
        os.fsync(descriptor)
        opened = os.fstat(descriptor)
        actual = path.lstat()
        require(stat.S_ISREG(actual.st_mode) and actual.st_nlink == 1 and actual.st_uid == os.getuid() and
                stat.S_IMODE(actual.st_mode) == 0o600 and
                (actual.st_dev, actual.st_ino) == (opened.st_dev, opened.st_ino), "Exclusive staging lock identity differs")
        yield descriptor
    finally:
        try:
            try:
                actual = path.lstat()
            except FileNotFoundError:
                actual = None
            opened = os.fstat(descriptor)
            # Do not unlink a replacement lock, symlink, or any other inode.
            if (actual is not None and stat.S_ISREG(actual.st_mode) and actual.st_nlink == 1 and
                    (actual.st_dev, actual.st_ino) == (opened.st_dev, opened.st_ino)):
                path.unlink()
        finally:
            os.close(descriptor)


def install(vm_id):
    target = contract.target_for(vm_id)
    with exclusive_staging_lock(target) as descriptor:
        manifest = contract.validate_manifest(target, owned_launch_lock=descriptor)
        return _install_owned(target, manifest, descriptor)


def _install_owned(target, manifest, owned_launch_lock):
    vm_id = manifest["vm_uuid"]
    contract.verify_engine(manifest)
    require(not manifest.get("normal_boot_v2") and not (target / "data-v2-normal-boot-intent.json").exists(),
            "Restoring stock normal boot is single-use")
    evidence = preparation_evidence(target, manifest, True, owned_launch_lock=owned_launch_lock)
    base, tc = checked_tc(target, manifest)
    post.verify_hash(base, BASE_TC_SHA)
    post.verify_hash(tc, factory.OLD_TC_SHA)
    require(manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] == factory.OLD_COLD_SHA,
            "Unused cold helper must already have been restored")
    identity_binding = {key: manifest.get(key) for key in ("keychain_service", "keychain_account", "crypto_provider_source_sha256", "kdf_id")}
    record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id, "data_uuid": post.DATA_UUID,
              "update_uuid": UPDATE_UUID, "state": "preparing", "engine_binding": manifest["engine_binding"],
              "identity_binding": identity_binding, "evidence": evidence, "original_trustcache_sha256": factory.OLD_TC_SHA,
              "normal_trustcache_sha256": BASE_TC_SHA, "stock_data_protection_sha256": stage.STOCK_SHA,
              "stock_keybagd_sha256": post.PUBLIC_PINS["usr/libexec/keybagd"], "host_data_mounted": False,
              "root_accessed": False, "vm_started": False, "Data_or_keys_reinitialized": False,
              "scoped_cold_read_validated": True, "full_boot_validated": False, "springboard_validated": False,
              "ipa_execution_validated": False, "native_ready": False, "ready": False}
    post.durable_intent(target / "data-v2-normal-boot-intent.json", record)
    manifest["normal_boot_v2"] = record
    profile.write_manifest(target, manifest)
    build = target / "data-v2-normal-boot"
    build.mkdir(mode=0o700)
    stage.write_new(build / "previous-VirtualTrustCache", tc.read_bytes())
    stage.write_new(build / "stock-original-RestoreTrustCache", base.read_bytes())
    device, before = stage.attach_backing(target, manifest)
    mount = target / "DataV2NormalBootSystem"
    mounted = False
    try:
        system, added = update.checked_updated_layout(owned_container(device), device, manifest, UPDATE_UUID)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        cold.validate_system_mount(mount, system, manifest)
        checked_stock_system(mount, manifest)
        init = stage.safe_path(mount, "usr/libexec/init_data_protection")
        keybag = stage.safe_path(mount, "usr/libexec/keybagd")
        original = stage.safe_path(mount, "usr/libexec/huntmob-original/keybagd")
        stock_init = stage.safe_path(mount, "usr/libexec/huntmob-original/init_data_protection")
        cold_helper = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        owned = [cdhash(init), cdhash(keybag), cdhash(cold_helper)]
        restored_tc = stock_tc_transition(tc.read_bytes(), base.read_bytes(), owned)
        saved = original.lstat()
        require(stat.S_ISREG(saved.st_mode) and saved.st_nlink == 1 and not (saved.st_mode & 0o022),
                "Stock keybag original inode/mode differs")
        stage.write_new(build / "previous-init_data_protection", init.read_bytes(), 0o755)
        stage.write_new(build / "previous-keybagd-shim", keybag.read_bytes(), 0o755)
        stage.write_new(build / "stock-init_data_protection", stock_init.read_bytes(), 0o755)
        record.update(removed_owned_cdhashes=owned, original_stock_keybag_inode=saved.st_ino,
                      original_stock_keybag_device=saved.st_dev, original_stock_keybag_mode=saved.st_mode & 0o7777,
                      previous_wrapper_sha256=stage.digest(init), previous_keybag_shim_sha256=stage.digest(keybag),
                      stock_original_trustcache_bytes=len(restored_tc))
        profile.write_manifest(target, manifest)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        # Replace only the exact pinned owned shim; stock original retains its
        # inode, UID, mode, bytes and signature across this same-filesystem move.
        post.verify_hash(keybag, record["previous_keybag_shim_sha256"])
        os.replace(original, keybag)
        after = keybag.lstat()
        require_stock_inode_preserved(saved, after)
        post.verify_hash(keybag, post.PUBLIC_PINS["usr/libexec/keybagd"])
        stage.replace_known(init, stock_init.read_bytes(), record["previous_wrapper_sha256"])
        post.verify_hash(init, stage.STOCK_SHA)
        stage.run(["codesign", "--verify", "--strict", str(init)])
        stage.run(["codesign", "--verify", "--strict", str(keybag)])
        stage.replace_known(tc, restored_tc, factory.OLD_TC_SHA)
        post.verify_hash(tc, BASE_TC_SHA)
        checked_stock_system(mount, manifest, normal=True)
        update.checked_updated_layout(owned_container(device), device, manifest, UPDATE_UUID, system_mount=mount)
        cold.validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            cold.validate_system_mount(mount, system, manifest)
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        update.checked_updated_layout(owned_container(device), device, manifest, UPDATE_UUID)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="staged", stock_keybag_same_inode_restored=True, stock_data_protection_restored=True,
                  all_owned_helpers_removed_from_trustcache=True, own_restore_preparation_markers_absent=True,
                  owned_device_detached=True, existing_six_volumes_preserved=True)
    manifest["virtual_staging"]["helper_sha256"]["init_data_protection"] = stage.STOCK_SHA
    manifest["virtual_staging"]["trustcache_sha256"] = BASE_TC_SHA
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=BASE_TC_SHA, bytes=tc.stat().st_size,
                                                               format="stock-original-IM4P-rtsc")
    profile.write_manifest(target, manifest)
    return record


def validate_for_boot(target, manifest):
    record = manifest.get("normal_boot_v2", {})
    refresh = record.get("state") == "planned"
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] == post.VM_UUID and record.get("data_uuid") == post.DATA_UUID and
            record.get("update_uuid") == UPDATE_UUID and record.get("state") in ("staged", "planned") and
            record.get("engine_binding") == manifest["engine_binding"] and
            record.get("identity_binding") == {key: manifest.get(key) for key in ("keychain_service", "keychain_account", "crypto_provider_source_sha256", "kdf_id")} and
            all(record.get(key) is True for key in ("stock_keybag_same_inode_restored", "stock_data_protection_restored",
                "all_owned_helpers_removed_from_trustcache", "own_restore_preparation_markers_absent", "owned_device_detached", "existing_six_volumes_preserved")) and
            record.get("host_data_mounted") is False and manifest["virtual_staging"]["helper_sha256"]["init_data_protection"] == stage.STOCK_SHA and
            manifest["virtual_staging"]["trustcache_sha256"] == BASE_TC_SHA and
            manifest["firmware"]["files"]["RestoreTrustCache"].get("format") == "stock-original-IM4P-rtsc",
            "Exactly the restored stock normal-boot stage is required")
    if refresh:
        headless_refresh_evidence(target, manifest, for_rearm=False)
    else:
        require(not record.get("headless_refresh_rearmed") and record.get("headless_refresh_hz_required", 0) == 0,
                "A staged first boot cannot inherit a rearmed display plan")
    require(record.get("evidence") == preparation_evidence(target, manifest, False,
            scan_mode="historical-after-normal" if refresh else "initial"), "Cold read/scan/loader evidence changed")
    verify_stock_restore_artifacts(target, manifest, record)
    return record


def verify_stock_restore_artifacts(target, manifest, record):
    """Recheck immutable stock/backup bytes without mounting a backing."""
    build = target / "data-v2-normal-boot"
    for name, sha in (("previous-VirtualTrustCache", factory.OLD_TC_SHA), ("stock-original-RestoreTrustCache", BASE_TC_SHA),
            ("previous-init_data_protection", record["previous_wrapper_sha256"]),
            ("previous-keybagd-shim", record["previous_keybag_shim_sha256"]), ("stock-init_data_protection", stage.STOCK_SHA)):
        post.verify_hash(build / name, sha)
    current = Path(manifest["firmware"]["files"]["RestoreTrustCache"]["path"])
    require(current == target / "firmware/VirtualTrustCache", "Only the original scoped firmware path may carry the stock cache")
    post.verify_hash(current, BASE_TC_SHA)
    stock_tc_transition((build / "previous-VirtualTrustCache").read_bytes(), current.read_bytes(), record["removed_owned_cdhashes"])


def classify_result(log):
    """Diagnostic only: launchd/SpringBoard text never establishes a usable UI."""
    require(not any(text in log for text in ("HuntMob: post-keybag", "HuntMob: cold Class C", "HuntMob: Update append",
                "HuntMob: FactoryData", "HuntMob: provisioning checkpoint ready;", "ClassD initialization", "fresh MKBCreateSystem", "synthetic canary=")),
            "An owned bootstrap/probe ran during the requested stock boot")
    return {"normal_boot_log_observed": bool(log.strip()),
            "stock_early_boot_marker_observed": "Early boot complete. Continuing system boot." in log,
            "full_boot_validated": False, "springboard_validated": False,
            "ipa_execution_validated": False, "native_ready": False, "ready": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("install", "rearm-headless-refresh"), default="install")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({**contract.plan(args.vm_uuid, "restore-stock-normal-boot" if args.action == "install" else args.action), "host_data_mounted": False,
                          "stock_base_trustcache_only": True, "full_boot_validated": False, "springboard_validated": False}, indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    print(json.dumps(install(args.vm_uuid) if args.action == "install" else rearm_headless_refresh(args.vm_uuid), indent=2))


if __name__ == "__main__":
    main()
