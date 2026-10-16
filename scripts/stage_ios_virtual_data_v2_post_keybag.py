#!/usr/bin/env python3
"""Stage/consume the own DATA-v2 post-stock-keybag read experiment.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a no-op plan. No guest
launch, Keychain, Data mount/unlock, keybag read or creation occurs here.
"""
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import struct
import uuid
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
import stage_ios_virtual_data_v2_cold_read as cold
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_auxiliary import owned_container
from stage_ios_virtual_data_v2_auxiliary import checked_tc

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-post-keybag.v2"
VM_UUID = "9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"
DATA_UUID = "2F4BDE84-276C-414B-839A-2B2E996C1BF6"
BASELINE = "data-v2-observation-20261015-163037"
BASELINE_SHA = "5a2d47ac68406816bb8cb2353fbec25f8e2a7caafbfeec131c8059c6187d97b8"
BASELINE_LOG_SHA = "af4f998fc4d051df06de8dd4ce50412ab5f0a3b78455548e21f7b62eea6a6ee4"
BASELINE_TRACE_SHA = "0e6d134c8d05a81f1e7d0a4093f021ad5e721600ed782d95899259bcb0511ba6"
INSPECTION = "data-v2-system-boot-inspection-20261015-163945-86376060"
INSPECTION_SHA = "1931edf37128720e6b1b946577edd3f21e5eedb5f72c1934495897ea8f018e6e"
PUBLIC_PINS = {
    "sbin/launchd": "50307ff547f84a8c5e03b51fcc6b9be31cea876b39bb829d0dd6e42aa5dd4598",
    "System/Library/xpc/launchd.plist": "e5847afbcf6c025ee7f15620918eb6bc79bc916a29301bba8b034cf4775f3c24",
    "usr/libexec/keybagd": "4cd2506d4f47a150da3748887127eca0420051d3095bf6dd1470f35805920cf6",
}
PINS = {
    "keybagd_path_shim_v2.c": "6433b3b8c9db18d6eb095acb22bd79655ec88dd53839ba0623661ead05efead1",
    "verify_post_keybag_data_v2.c": "b09d0999241c3b98b46d5230de008682c33ccc7e878d49d01fddc88828d705b6",
    "post_keybag_sequence_v2.h": "496c8e139b9ad3260dad1dee90fc98eef4277f32e16a6f8c92deacad4836d361",
    "cold_read_policy_v2.h": "798c469f419b143427c6859a8d091b5c76a5048e73ed8586e62732df3c9b4499",
    "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050",
}
MARKER = b"HUNTMOB VIRTUAL SEP V1 FRESH DATA\n"
STOP_MARKER = "HuntMob: provisioning checkpoint ready; own DATA-v2 post-keybag cold-read observation"
BOOT_PROOF = profile.RESEARCH / "cold-system-bag-contract-20261015"
BOOT_PROOF_SHA = "e205dbf800b1b685343949132b7dd8fda6936b4e7d3ac6970ee79779d387edce"
BOOT_DEFINITIONS_SHA = "6714202a047e4849f96b30852fd807c421027c731821248c1ac0d65b0e3ec188"
BOOT_ORDER_SHA = "99211b6709ec736c383b019f7ce0cd8dde28154f5ca2b84b98ee78ef5797ef2a"


def boot_order_evidence():
    verify_hash(BOOT_PROOF / "receipt.json", BOOT_PROOF_SHA)
    proof = contract.read_metadata(BOOT_PROOF / "receipt.json")
    verify_hash(BOOT_PROOF / "launchd-boot-task-definitions.json", BOOT_DEFINITIONS_SHA)
    verify_hash(BOOT_PROOF / "launchd-boot-order-recovery-copy.asm", BOOT_ORDER_SHA)
    tasks = contract.read_metadata(BOOT_PROOF / "launchd-boot-task-definitions.json")
    require(proof.get("schema") == "huntmob.stock-system-keybag-bootstrap.static.v1" and
            proof["sources"]["recovery_ramdisk_launchd"]["sha256"] == PUBLIC_PINS["sbin/launchd"] and
            proof["confirmed"]["recovery_launchd_call_order"] == ["mount-phase-1", "data-protection", "mount-phase-2",
                "init-with-data-volume", "MSUEarlyBootTask", "fips", "keybag"] and
            tasks["data-protection"]["Program"] == "/usr/libexec/init_data_protection" and
            tasks["keybag"]["Program"] == "/usr/libexec/keybagd" and tasks["keybag"]["ProgramArguments"] == ["keybagd", "--init"],
            "Exact static launchd Boot definition and call-order proof required")
    return {"static_receipt_sha256": BOOT_PROOF_SHA, "boot_definitions_sha256": BOOT_DEFINITIONS_SHA,
            "boot_order_assembly_sha256": BOOT_ORDER_SHA, "normal_system_binary_equality_verified_by_inspection": True,
            "stock_order_preserved": True}


def baseline_evidence(target, manifest):
    require(manifest.get("vm_uuid") == VM_UUID and manifest.get("cold_read_v2", {}).get("data_uuid") == DATA_UUID,
            "Only the exact proven own DATA-v2 experiment may change its invocation point")
    previous = manifest["cold_read_v2"]
    require(previous.get("state") == "launch-requested" and previous.get("observation") == str(target / BASELINE),
            "The known failed early read must remain preserved")
    directory = target / BASELINE
    proof = contract.read_metadata(directory / "observation.json")
    require(stage.digest(directory / "observation.json") == BASELINE_SHA and proof.get("engine_binding") == manifest["engine_binding"] and
            proof.get("vm_uuid") == VM_UUID and proof.get("cold_class_c_read_requested") is True and
            proof.get("panic_observed") is True and proof.get("checkpoint_observed") is False and
            proof.get("qmp_quit_accepted") is True and proof.get("exit_code") == 0,
            "Exact failed early-read receipt required")
    require(stage.digest(directory / "boot.log") == BASELINE_LOG_SHA == proof.get("boot.log_sha256") and
            stage.digest(directory / "trace.log") == BASELINE_TRACE_SHA == proof.get("trace.log_sha256"), "Baseline logs changed")
    for key in ("aess_rejected_command_count", "nvme_error_completion_count", "protected_io_rejection_count", "protected_gate_rejection_count"):
        require(proof.get(key) == 0, "Baseline crypto/storage rejection differs")
    inspected = target / INSPECTION
    receipt = contract.read_metadata(inspected / "receipt.json")
    require(stage.digest(inspected / "receipt.json") == INSPECTION_SHA and receipt.get("engine_binding") == manifest["engine_binding"] and
            receipt.get("vm_uuid") == VM_UUID and receipt.get("data_uuid") == DATA_UUID and
            receipt.get("state") == "completed-readonly-inspection" and receipt.get("system_unmounted") is True and
            receipt.get("owned_device_detached") is True, "Normal System inspection must match this stopped cohort")
    for name, sha in PUBLIC_PINS.items():
        entry = receipt["files"].get(name, {})
        require(entry.get("artifact") == "public-system/" + name and entry.get("sha256") == sha and
                stage.digest(inspected / ("public-system/" + name)) == sha, "Inspected normal System public binary/cache changed")
    cache = plistlib.loads((inspected / "public-system/System/Library/xpc/launchd.plist").read_bytes())
    checked_cache(cache)
    return {"early_observation": BASELINE, "early_receipt_sha256": BASELINE_SHA, "early_log_sha256": BASELINE_LOG_SHA,
            "early_trace_sha256": BASELINE_TRACE_SHA, "inspection": INSPECTION, "inspection_sha256": INSPECTION_SHA,
            "normal_system_public_sha256": dict(PUBLIC_PINS), "boot_order": boot_order_evidence()}


def checked_cache(cache):
    daemons = cache.get("LaunchDaemons", {})
    daemon = daemons.get("/System/Library/LaunchDaemons/com.apple.mobile.keybagd.plist", {})
    require(daemon.get("Label") == "com.apple.mobile.keybagd" and
            daemon.get("ProgramArguments") == ["/usr/libexec/keybagd", "-t", "15"] and
            "Program" not in daemon and "Boot" not in cache,
            "Normal cache must retain the exact stock keybag daemon argv and no guessed Boot override")


def add_only_shim_tc(current, shim_hash, vm_id):
    require(re.fullmatch(r"[0-9a-f]{40}", shim_hash or "") and len(current) >= 24, "Owned CDHash/raw trustcache required")
    version, = struct.unpack_from("<I", current)
    count, = struct.unpack_from("<I", current, 20)
    identity = uuid.uuid5(uuid.UUID(vm_id), "HuntMob.VirtualSEP.v1.TrustCache").bytes
    require(version == 1 and current[4:20] == identity and count < 4096 and len(current) == 24 + 22 * count,
            "Current raw trustcache identity/layout differs")
    entries = [current[24 + n * 22:24 + (n + 1) * 22] for n in range(count)]
    require(entries == sorted(set(entries)), "Current trustcache entries must remain unique and canonical")
    addition = bytes.fromhex(shim_hash) + b"\x02\x00"
    require(addition not in entries, "Shim must be a new single trustcache addition")
    updated = sorted(entries + [addition])
    result = current[:20] + struct.pack("<I", len(updated)) + b"".join(updated)
    require(set(updated) - set(entries) == {addition} and set(entries).issubset(updated), "Existing trustcache entry loss refused")
    return result


def verify_hash(path, sha):
    require(path.is_file() and not path.is_symlink() and stage.digest(path) == sha, "Exact owned artifact/readback hash differs")


def durable_intent(path, record):
    stage.write_new(path, json.dumps(record, indent=2).encode())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def install(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    require(not manifest.get("post_keybag_v2") and not (target / "data-v2-post-keybag-intent.json").exists() and
            not (target / ".data-v2-launch.lock").exists(), "Post-keybag installation is single-use and requires a stopped VM")
    evidence = baseline_evidence(target, manifest)
    staging = manifest["virtual_staging"]
    prior = manifest["cold_read_v2"]
    require(staging["phase"] == "data-checkpoint" and prior["helper_sha256"] == staging["helper_sha256"]["huntmob-prepare-userdata"] and
            prior["trustcache_sha256"] == staging["trustcache_sha256"], "Existing early helper/trustcache binding differs")
    _, tc = checked_tc(target, manifest)
    for name, sha in PINS.items():
        verify_hash(stage.PROVISIONING / name, sha)
    record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id, "data_uuid": DATA_UUID,
              "state": "preparing", "source_sha256": dict(PINS), "baseline": evidence,
              "data_profile_sha256": manifest["data_profile_sha256"], "engine_binding": manifest["engine_binding"],
              "expected_probe_sha256": prior["expected_probe_sha256"], "original_keybagd_sha256": PUBLIC_PINS["usr/libexec/keybagd"],
              "original_trustcache_sha256": stage.digest(tc), "wrapper_sha256": staging["helper_sha256"]["init_data_protection"],
              "cold_helper_sha256": prior["helper_sha256"], "host_data_mounted": False, "root_accessed": False,
              "launchd_or_cache_modified": False, "stock_verifier_modified": False, "stock_keybagd_bytes_modified": False,
              "read_validated": False, "native_ready": False, "ready": False}
    durable_intent(target / "data-v2-post-keybag-intent.json", record)
    manifest["post_keybag_v2"] = record
    profile.write_manifest(target, manifest)
    build = target / "data-v2-post-keybag"
    build.mkdir(mode=0o700)
    for name, sha in PINS.items():
        shutil.copyfile(stage.PROVISIONING / name, build / name)
        verify_hash(build / name, sha)
    ent = build / "entitlements.plist"
    stage.write_new(ent, plistlib.dumps(cold.ENTITLEMENTS))
    sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
    binary = build / "keybagd"
    stage.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
               "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"',
               '-DHUNTMOB_EXPECTED_DATA_UUID="' + DATA_UUID + '"',
               '-DHUNTMOB_EXPECTED_CANARY_SHA256="' + record["expected_probe_sha256"] + '"',
               str(build / "keybagd_path_shim_v2.c"), "-o", str(binary)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.apple.keybagd", "--entitlements", str(ent), str(binary)])
    stage.run(["codesign", "--verify", "--strict", str(binary)])
    actual = stage.run(["codesign", "-d", "--entitlements", ":-", str(binary)])
    require(plistlib.loads(actual.stdout) == cold.ENTITLEMENTS == {"com.apple.keystore.device": True},
            "Shim must retain only the minimal explicit owned helper entitlement")
    cold.require_probe_absent(binary.read_bytes(), prior["creation_evidence"]["expected_public_canary"])
    original_tc = tc.read_bytes()
    verify_hash(tc, record["original_trustcache_sha256"])
    custom = add_only_shim_tc(original_tc, cdhash(binary), vm_id)
    cold.require_probe_absent(custom, prior["creation_evidence"]["expected_public_canary"])
    stage.write_new(build / "original-VirtualTrustCache", original_tc)
    record.update(helper_sha256=stage.digest(binary), helper_cdhash=cdhash(binary), trustcache_sha256=hashlib.sha256(custom).hexdigest())
    profile.write_manifest(target, manifest)
    device, before = stage.attach_backing(target, manifest)
    mount = target / "DataV2PostKeybagSystem"
    mounted = False
    try:
        system = cold.checked_layout(owned_container(device), device, manifest, DATA_UUID)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        cold.validate_system_mount(mount, system, manifest)
        for name, sha in PUBLIC_PINS.items():
            verify_hash(stage.safe_path(mount, name), sha)
        checked_cache(plistlib.loads(stage.safe_path(mount, "System/Library/xpc/launchd.plist").read_bytes()))
        for relative in ("usr/libexec/seputil", "usr/libexec/huntmob-original/init_data_protection"):
            verify_hash(stage.safe_path(mount, relative), stage.STOCK_SHA)
        verify_hash(stage.safe_path(mount, "usr/libexec/init_data_protection"), record["wrapper_sha256"])
        verify_hash(stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata"), record["cold_helper_sha256"])
        marker = stage.safe_path(mount, "usr/libexec/huntmob-prepare-data")
        require(marker.is_file() and not marker.is_symlink() and marker.lstat().st_nlink == 1 and
                marker.read_bytes() == MARKER, "Only the exact own preparation marker may be removed")
        original = stage.safe_path(mount, "usr/libexec/huntmob-original/keybagd")
        require(not original.exists() and not original.is_symlink(), "Original stock keybag destination must be absent")
        stock = stage.safe_path(mount, "usr/libexec/keybagd")
        identity = stock.lstat()
        require(stat.S_ISREG(identity.st_mode) and identity.st_nlink == 1 and not (identity.st_mode & 0o022),
                "Stock original must be a single non-writable-by-others regular file")
        stage.write_new(build / "original-keybagd.public", stock.read_bytes())
        verify_hash(build / "original-keybagd.public", PUBLIC_PINS["usr/libexec/keybagd"])
        stage.write_new(build / "original-prepare-data-marker", marker.read_bytes())
        record.update(stock_source_inode=identity.st_ino, stock_source_device=identity.st_dev,
                      stock_source_mode=identity.st_mode & 0o7777, marker_sha256=stage.digest(marker))
        profile.write_manifest(target, manifest)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        # Same-filesystem rename preserves the stock inode, UID, mode and code
        # signature. Never chown/copy-replace the original or alter its bytes.
        os.rename(stock, original)
        saved = original.lstat()
        require((saved.st_dev, saved.st_ino, saved.st_mode, saved.st_nlink) ==
                (identity.st_dev, identity.st_ino, identity.st_mode, 1), "Original stock inode/mode changed during rename")
        verify_hash(original, PUBLIC_PINS["usr/libexec/keybagd"])
        stage.write_new(stock, binary.read_bytes(), 0o755)
        verify_hash(stock, record["helper_sha256"])
        stage.run(["codesign", "--verify", "--strict", str(stock)])
        stage.replace_known(tc, custom, record["original_trustcache_sha256"])
        verify_hash(tc, record["trustcache_sha256"])
        require(marker.read_bytes() == MARKER and stage.digest(marker) == record["marker_sha256"], "Own preparation marker changed before removal")
        marker.unlink()
        require(not marker.exists() and not marker.is_symlink(), "Own preparation marker still exists")
        for name in ("sbin/launchd", "System/Library/xpc/launchd.plist"):
            verify_hash(stage.safe_path(mount, name), PUBLIC_PINS[name])
        verify_hash(stage.safe_path(mount, "usr/libexec/init_data_protection"), record["wrapper_sha256"])
        verify_hash(stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata"), record["cold_helper_sha256"])
        cold.checked_layout(owned_container(device), device, manifest, DATA_UUID, system_mount=mount)
        cold.validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            cold.validate_system_mount(mount, system, manifest)
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        cold.checked_layout(owned_container(device), device, manifest, DATA_UUID)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="installed", original_renamed_same_inode=True, own_prepare_marker_removed=True,
                  host_data_encrypted=True, host_data_locked=True, owned_device_detached=True)
    staging["trustcache_sha256"] = record["trustcache_sha256"]
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    profile.write_manifest(target, manifest)
    return record


def validate_for_boot(target, manifest):
    record = manifest.get("post_keybag_v2", {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] == VM_UUID and record.get("data_uuid") == DATA_UUID and
            record.get("state") == "installed" and record.get("source_sha256") == PINS and
            record.get("engine_binding") == manifest["engine_binding"] and record.get("own_prepare_marker_removed") is True and
            record.get("original_renamed_same_inode") is True and record.get("host_data_mounted") is False and
            record.get("host_data_encrypted") is True and record.get("host_data_locked") is True and
            record.get("trustcache_sha256") == manifest["virtual_staging"]["trustcache_sha256"] and
            record.get("wrapper_sha256") == manifest["virtual_staging"]["helper_sha256"]["init_data_protection"] and
            record.get("cold_helper_sha256") == manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"],
            "Exactly the installed post-stock-keybag experiment is required")
    require(record.get("baseline") == baseline_evidence(target, manifest), "Original failed-read and Boot-order evidence changed")
    build = target / "data-v2-post-keybag"
    for name, sha in PINS.items():
        verify_hash(build / name, sha)
    verify_hash(build / "keybagd", record["helper_sha256"])
    verify_hash(build / "original-keybagd.public", PUBLIC_PINS["usr/libexec/keybagd"])
    verify_hash(build / "original-VirtualTrustCache", record["original_trustcache_sha256"])
    expected_tc = add_only_shim_tc((build / "original-VirtualTrustCache").read_bytes(), record["helper_cdhash"], manifest["vm_uuid"])
    require(hashlib.sha256(expected_tc).hexdigest() == record["trustcache_sha256"], "Post-keybag trustcache is not exactly old entries plus this shim")
    require((build / "original-prepare-data-marker").read_bytes() == MARKER, "Original own marker backup changed")
    return record


def classify_result(log):
    require(not any(text in log for text in ("ClassD initialization", "fresh MKBCreateSystem", "synthetic canary=")),
            "Post-keybag read must never provision storage or recreate the probe")
    start = "HuntMob: post-keybag stock-init-start"
    exit0 = "HuntMob: post-keybag stock-init-exit=0 signal=0"
    identity = "HuntMob: post-keybag Data UUID CPROTECT and existing-bag identity matched"
    exits = re.findall(r"^HuntMob: post-keybag stock-init-exit=(-?\d+) signal=(\d+)$", log, re.MULTILINE)
    require(exits == [("0", "0")] and "HuntMob: post-keybag stock-binary-pin-failed" not in log and
            "HuntMob: post-keybag data-identity-failed" not in log, "Failed or repeated stock init/identity cannot count as a read success")
    require(log.count(start) == log.count(exit0) == 1 and log.count(identity) == 2 and
            log.index(identity) < log.index(start) < log.index(exit0) < log.rindex(identity),
            "Exact existing Data identity/stock init exit0/rechecked identity order required")
    before = re.findall(r"^HuntMob: post-keybag Class C unlocked-since-boot before=([01])$", log, re.MULTILINE)
    after = re.findall(r"^HuntMob: post-keybag Class C unlocked-since-boot after=([01])$", log, re.MULTILINE)
    access = re.findall(r"^HuntMob: post-keybag Class C access_errno=(\d+) metadata_valid=([01]) read_complete=([01]) digest_match=([01])$", log, re.MULTILINE)
    results = re.findall(r"^HuntMob: post-keybag Class C result=([a-z-]+)$", log, re.MULTILINE)
    require(len(before) == len(after) == len(access) == len(results) == 1 and log.count(STOP_MARKER) == 1,
            "Exactly one post-stock-init probe, unlock pair, result and checkpoint required")
    require(log.rindex(identity) < log.index("HuntMob: post-keybag Class C unlocked-since-boot before=") <
            log.index("HuntMob: post-keybag Class C unlocked-since-boot after=") <
            log.index("HuntMob: post-keybag Class C access_errno=") <
            log.index("HuntMob: post-keybag Class C result=") < log.index(STOP_MARKER), "Probe sequence is out of order")
    result = results[0]
    if result == "afu-read-match":
        require(before == after == ["1"] and access == [("0", "1", "1", "1")], "AFU success requires the actual complete Class C digest match")
    elif result == "bfu-denied":
        require(before == after == ["0"] and access[0][0] in ("1", "13") and access[0][2:] == ("0", "0"), "BFU denial is distinct from AFU/storage failure")
    elif result == "unlock-state-changed-unvalidated":
        require(before != after, "Unvalidated transition requires an actual unlock-state change")
    else:
        raise ValueError("Unsupported or failed post-keybag result")
    return {"result": result, "read_validated": result == "afu-read-match", "cold_read_validated": result == "afu-read-match",
            "bfu_expected_denial_observed": result == "bfu-denied", "native_ready": False, "ready": False}


def consume(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    record = manifest.get("post_keybag_v2", {})
    require(record.get("schema") == SCHEMA and record.get("vm_uuid") == vm_id and record.get("profile") == contract.PROFILE and
            record.get("state") == "launch-requested" and not (target / "data-v2-post-keybag-result.json").exists(),
            "Exactly one native post-keybag observation may be consumed")
    directory = Path(record.get("observation", ""))
    require(directory.parent == target, "Native post-keybag observation belongs to another cohort")
    directory, proof, log, trace = cold.observation(target, manifest, directory.name)
    require(proof.get("post_keybag_class_c_read_requested") is True and proof.get("stock_data_protection_verifier_invoked") is True,
            "Explicit post-keybag flag and unchanged stock verifier required")
    result = classify_result(log)
    record.update(state="observed", **result, observation_sha256=stage.digest(directory / "observation.json"),
                  boot_log_sha256=proof["boot.log_sha256"], trace_log_sha256=proof["trace.log_sha256"])
    durable_intent(target / "data-v2-post-keybag-result.json", record)
    profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("install", "consume", "rearm-after-factory-seed", "rearm-after-update-volume"), default="install")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({**contract.plan(args.vm_uuid, "post-keybag-" + args.action),
                          "keybagd_bytes_preserved": True, "launchd_cache_changed": False,
                          "root_accessed": False, "host_data_mounted": False}, indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    if args.action == "rearm-after-update-volume":
        from stage_ios_virtual_data_v2_update_volume import rearm_after_update_volume
        result = rearm_after_update_volume(args.vm_uuid)
    elif args.action == "rearm-after-factory-seed":
        from stage_ios_virtual_data_v2_factorydata import rearm_after_factory_seed
        result = rearm_after_factory_seed(args.vm_uuid)
    else:
        result = install(args.vm_uuid) if args.action == "install" else consume(args.vm_uuid)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
