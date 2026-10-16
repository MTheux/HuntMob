#!/usr/bin/env python3
"""Single-use own DATA-v2 UI-process metadata observer staging.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a no-op plan. Apply changes
only the exact owned System volume and its owned trustcache. No guest launch,
Keychain, Data mount/unlock, process memory or crash-content read occurs here.
A completed metadata sampler never validates UI, IPA or native readiness.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import struct
import uuid

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
import stage_ios_virtual_data_v2_cold_read as cold
import stage_ios_virtual_data_v2_post_keybag as post
import stage_ios_virtual_data_v2_normal_boot as normal
import stage_ios_virtual_data_v2_update_volume as update
import verify_ios_virtual_data_v2_storage_probe as reader
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_auxiliary import owned_container
from stage_ios_virtual_data_v2_auxiliary import BASE_TC_SHA

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-ui-process-observer.v2"
RECORD = "ui_process_observer_v2"
BUILD = "data-v2-ui-process-observer"
VM_UUID = "9b133fb6-cac4-462f-b2e7-15a6d1f8e0f4"
DATA_UUID = "2F4BDE84-276C-414B-839A-2B2E996C1BF6"
BASELINE = "data-v2-observation-20261015-180951"
BASELINE_SHA = "2c5e1343ae50885dd42e3c794d8c6778e7bb0072a7e3e52266a2320ca68e5722"
BASELINE_LOG_SHA = "f79e63bed493cc9906ed28d4fafed3b1617c7052985b0297727216577db8bbbf"
BASELINE_TRACE_SHA = "0f210cfe0a2a7aa0ce400ec7bcca37da1ec3c34bd65f776b5aa2866f8174bc2c"
SCAN = "data-v2-storage-scan-20261015-181946-beb6c17f"
SCAN_SHA = "463ae4443f17fff29bd1bcb38b301262174c81b7ce5264e2e697e70d28c2e7be"
SAMPLER = "usr/libexec/huntmob-ui-process-observer"
STOCK = "usr/libexec/huntmob-original/keybagd"
SAMPLER_SOURCE = "observe_ui_processes_v2.c"
WRAPPER_SOURCE = "keybagd_ui_process_observer_v2.c"
PINS = {
    "observe_ui_processes_v2.c": "9245a4732e69f5104180fcf69b6de5f87b1d61ab1a370ea5ed2dd432825a4a4f",
    "keybagd_ui_process_observer_v2.c": "7e25f2b61831d92111d67db767ffeb2728e738cd5e63296c1b5e614549dfd696",
    "ui_process_observer_policy_v2.h": "974502773b8e0c3d07b8b7962eea8c1abdeb4afa81e4370f013cf13198b7567f",
    "post_keybag_sequence_v2.h": "496c8e139b9ad3260dad1dee90fc98eef4277f32e16a6f8c92deacad4836d361",
    "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050",
}
WRAPPER_ENTITLEMENTS = {"com.apple.keystore.device": True}
SERVICES = {"SpringBoard", "backboardd", "runningboardd"}
BEGIN = "HuntMob:ui-proc begin metadata_only=1 samples_max=24"
END = "HuntMob:ui-proc end samples=24 metadata_only=1 readiness=0"
IDENTITY_KEYS = ("keychain_service", "keychain_account", "root_provisioned", "root_helper_sha256",
                 "crypto_provider_source_sha256", "kdf_id")


def source_pins(build=None):
    expected = {SAMPLER_SOURCE, WRAPPER_SOURCE, "ui_process_observer_policy_v2.h",
                "post_keybag_sequence_v2.h", "virtual_v1_scope.h"}
    require(set(PINS) == expected and all(re.fullmatch(r"[0-9a-f]{64}", v or "") for v in PINS.values()),
            "Reviewed native observer sources must be frozen before staging")
    root = stage.PROVISIONING if build is None else build
    for name, sha in PINS.items():
        post.verify_hash(root / name, sha)


def checked_normal_observation(target, manifest):
    directory = target / BASELINE
    post.verify_hash(directory / "observation.json", BASELINE_SHA)
    proof = contract.read_metadata(directory / "observation.json")
    require(proof.get("schema") == "huntmob.virtual-sep-data-observation.v2" and
            proof.get("vm_uuid") == VM_UUID and proof.get("engine_binding") == manifest["engine_binding"] and
            proof.get("data_profile") == contract.PROFILE and
            proof.get("data_profile_sha256") == manifest["data_profile_sha256"] and
            proof.get("normal_boot_requested") is True and proof.get("sep_profile") == "serving" and
            proof.get("stock_early_boot_marker_observed") is True and
            proof.get("stop_reason") == "bounded-observation-ended" and
            proof.get("elapsed_seconds") == 180.01 and proof.get("headless_refresh_accepted_count") == 1629 and
            proof.get("headless_refresh_hz_requested") == 10 and
            proof.get("headless_refresh_does_not_validate_ui") is True and
            proof.get("qmp_quit_requested") is True and proof.get("qmp_quit_accepted") is True and
            proof.get("exit_code") == 0, "Exact completed stock normal/headless observation required")
    require(all(proof.get(k) is False for k in ("panic_observed", "own_checkpoint_unexpected", "checkpoint_observed",
                "virtual_mpe_memory_fault_observed", "mpe_rejected_revocation_observed", "ready", "native_ready",
                "springboard_validated", "ipa_execution_validated")), "Baseline must remain clean and UI-unvalidated")
    require(all(proof.get(k) == 0 for k in ("aess_rejected_command_count", "nvme_error_completion_count",
                "protected_io_rejection_count", "protected_gate_rejection_count")), "Baseline contains instrumented rejections")
    for name, sha in (("boot.log", BASELINE_LOG_SHA), ("trace.log", BASELINE_TRACE_SHA)):
        _, observed, _ = reader.stable_blob(directory / name, 64 * 1024 * 1024)
        require(observed == sha == proof[name + "_sha256"], "Frozen baseline log changed")
    return {"observation": BASELINE, "receipt_sha256": BASELINE_SHA,
            "boot_log_sha256": BASELINE_LOG_SHA, "trace_log_sha256": BASELINE_TRACE_SHA}


def checked_scan(target, manifest, current=False):
    path = target / SCAN / "receipt.json"
    post.verify_hash(path, SCAN_SHA)
    value = contract.read_metadata(path)
    require(value.get("schema") == "huntmob.virtual-sep-data-storage-probe-scan.v1" and
            value.get("state") == "completed-readonly-scan" and value.get("vm_uuid") == VM_UUID and
            value.get("data_profile") == contract.PROFILE and value.get("engine_binding") == manifest["engine_binding"] and
            value.get("total_bytes_scanned") == sum(profile.SIZES.values()) and
            set(value.get("backings", {})) == set(profile.SIZES) and value.get("total_matches") == 0 and
            value.get("public_probe_absent") is True and value.get("global_source_identity_unchanged") is True and
            value.get("host_backings_not_attached_before_after") is True and
            value.get("historical_finding_status") == "OPEN" and
            value.get("scoped_native_cold_read", {}).get("validated") is True and
            all(value.get(k) is False for k in ("root_accessed", "keychain_accessed", "vm_started", "backings_written",
                "Data_mounted_or_unlocked", "cryptography_validated_by_scan", "ready", "native_ready")),
            "Exact complete post-refresh nine-backing scan required")
    for name, size in profile.SIZES.items():
        item = value["backings"][name]
        before, after = item["identity_before"], item["identity_after"]
        require(before == after and item.get("bytes_scanned") == size and
                {key: after[key] for key in ("device", "inode", "bytes", "links")} == manifest["backings"][name],
                "Frozen scan backing identity differs")
        require(set(item.get("matches", {})) == {"ascii_hex64", "decoded32"} and
                all(entry.get("count") == 0 and entry.get("offsets") == [] and entry.get("offsets_truncated") is False
                    for entry in item["matches"].values()), "Frozen scan is incomplete or contains a marker hit")
        if current:
            require(reader.path_identity(target / name) == after, "Backing changed after the post-refresh scan")
    return {"receipt": SCAN, "receipt_sha256": SCAN_SHA, "total_bytes_scanned": value["total_bytes_scanned"]}


def evidence(target, manifest, *, current_scan=False):
    require(manifest.get("vm_uuid") == VM_UUID and manifest.get("root_provisioned") is True and
            manifest.get("cold_read_v2", {}).get("data_uuid") == DATA_UUID,
            "Only the exact existing protected DATA-v2 cohort is accepted")
    restored = manifest.get("normal_boot_v2", {})
    require(restored.get("vm_uuid") == VM_UUID and restored.get("engine_binding") == manifest["engine_binding"] and
            restored.get("state") == "launch-requested" and restored.get("observation") == str(target / BASELINE) and
            all(restored.get(k) is True for k in ("stock_keybag_same_inode_restored", "stock_data_protection_restored",
                "all_owned_helpers_removed_from_trustcache", "own_restore_preparation_markers_absent",
                "existing_six_volumes_preserved", "owned_device_detached")), "Exact stock normal boot restoration required")
    return {"native_normal": checked_normal_observation(target, manifest),
            "full_raw_scan": checked_scan(target, manifest, current_scan)}


def trustcache_transition(base, hashes, vm_id):
    require(hashlib.sha256(base).hexdigest() == BASE_TC_SHA and len(hashes) == 2 and len(set(hashes)) == 2 and
            all(re.fullmatch(r"[0-9a-f]{40}", h or "") for h in hashes), "Exact base plus two distinct owned code hashes required")
    stock = stage.trustcache_entries(base)
    additions = {bytes.fromhex(h) + b"\x02\x00" for h in hashes}
    require(not any(entry[:20].hex() in hashes for entry in stock), "Owned code hash collides with stock")
    result = stage.merged_trustcache(base, hashes, vm_id)
    count, = struct.unpack_from("<I", result, 20)
    entries = [result[24 + n * 22:24 + (n + 1) * 22] for n in range(count)]
    require(entries == sorted(stock | additions) and len(result) == 24 + 22 * count and
            set(entries) - stock == additions, "Canonical cache must preserve all stock entries and add only two observers")
    return result


@contextmanager
def owned_lock(target, manifest):
    path = target / ".data-v2-launch.lock"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    identity = None
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, ("ui-observer-stage " + str(os.getpid()) + "\n").encode())
        os.fsync(fd)
        identity = reader.file_identity(os.fstat(fd))
        contract.validate_manifest(target, manifest, owned_launch_lock=fd)
        yield fd
    finally:
        os.close(fd)
        if identity is not None:
            require(reader.path_identity(path) == identity, "Refuse removing a replaced observer lock")
            path.unlink()


def compile_helpers(build, vm_id):
    source_pins()
    build.mkdir(mode=0o700, exist_ok=False)
    for name in PINS:
        stage.write_new(build / name, (stage.PROVISIONING / name).read_bytes())
    source_pins(build)
    sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
    common = ["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
              "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"']
    sampler = build / "huntmob-ui-process-observer"
    wrapper = build / "keybagd"
    stage.run(common + [str(build / SAMPLER_SOURCE), "-o", str(sampler)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.huntmob.ui-process-observer", str(sampler)])
    stage.run(["codesign", "--verify", "--strict", str(sampler)])
    sampler_sha = stage.digest(sampler)
    ent = build / "keybagd-entitlements.plist"
    stage.write_new(ent, plistlib.dumps(WRAPPER_ENTITLEMENTS))
    stage.run(common + ['-Wno-deprecated-declarations', '-DHUNTMOB_EXPECTED_DATA_UUID="' + DATA_UUID + '"',
               '-DHUNTMOB_EXPECTED_OBSERVER_SHA256="' + sampler_sha + '"', str(build / WRAPPER_SOURCE),
               "-o", str(wrapper)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.apple.keybagd",
               "--entitlements", str(ent), str(wrapper)])
    stage.run(["codesign", "--verify", "--strict", str(wrapper)])
    observed = stage.run(["codesign", "-d", "--entitlements", ":-", str(wrapper)])
    require(plistlib.loads(observed.stdout) == WRAPPER_ENTITLEMENTS, "Wrapper entitlements differ")
    # No root, probe bytes, arbitrary scripts or inherited entitlements are injected.
    source_pins(build)
    return sampler, wrapper


def unchanged_system(mount, manifest, *, installed=False, record=None):
    normal.require_absent_markers(mount)
    for relative, expected in (("sbin/launchd", post.PUBLIC_PINS["sbin/launchd"]),
            ("System/Library/xpc/launchd.plist", post.PUBLIC_PINS["System/Library/xpc/launchd.plist"]),
            ("usr/libexec/seputil", stage.STOCK_SHA), ("usr/libexec/init_data_protection", stage.STOCK_SHA),
            ("usr/libexec/huntmob-original/init_data_protection", stage.STOCK_SHA)):
        post.verify_hash(stage.safe_path(mount, relative), expected)
    keybag = stage.safe_path(mount, "usr/libexec/keybagd")
    original = stage.safe_path(mount, STOCK)
    sampler = stage.safe_path(mount, SAMPLER)
    if installed:
        post.verify_hash(keybag, record["wrapper_sha256"])
        post.verify_hash(original, post.PUBLIC_PINS["usr/libexec/keybagd"])
        post.verify_hash(sampler, record["sampler_sha256"])
        info = original.lstat()
        require(info.st_ino == record["stock_keybag_inode"] and stat.S_IMODE(info.st_mode) == record["stock_keybag_mode"] and
                info.st_nlink == 1, "Original stock keybag inode/mode changed")
    else:
        post.verify_hash(keybag, post.PUBLIC_PINS["usr/libexec/keybagd"])
        require(not original.exists() and not original.is_symlink() and not sampler.exists() and not sampler.is_symlink(),
                "No prior observer/original alias may exist before this stage")


def mounted_guard(target, manifest, device, before, mount, system):
    profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
    cold.validate_system_mount(mount, system, manifest)
    update.checked_updated_layout(owned_container(device), device, manifest, normal.UPDATE_UUID, system_mount=mount)


def file_snapshots(target):
    return {name: reader.path_identity(target / name) for name in profile.SIZES}


def install(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    require(vm_id == VM_UUID and not manifest.get(RECORD) and not (target / "data-v2-ui-observer-intent.json").exists(),
            "UI process observer installation is exact and single-use")
    source_pins()
    with owned_lock(target, manifest) as lock_fd:
        frozen = evidence(target, manifest, current_scan=True)
        reader.require_no_attached_backings(target, profile.SIZES)
        base = target / "firmware/RestoreTrustCache"
        tc = Path(manifest["firmware"]["files"]["RestoreTrustCache"]["path"])
        require(tc == target / "firmware/VirtualTrustCache" and
                manifest["virtual_staging"]["trustcache_sha256"] == BASE_TC_SHA and
                manifest["firmware"]["files"]["RestoreTrustCache"].get("format") == "stock-original-IM4P-rtsc",
                "Only the exact restored stock trustcache may be extended")
        post.verify_hash(base, BASE_TC_SHA)
        post.verify_hash(tc, BASE_TC_SHA)
        record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id, "data_uuid": DATA_UUID,
                  "state": "preparing", "evidence": frozen, "source_sha256": dict(PINS),
                  "engine_binding": manifest["engine_binding"],
                  "identity_binding": {k: manifest.get(k) for k in IDENTITY_KEYS},
                  "original_helper_map": dict(manifest["virtual_staging"]["helper_sha256"]),
                  "normal_trustcache_sha256": BASE_TC_SHA, "host_data_mounted": False,
                  "root_accessed": False, "Data_or_keys_reinitialized": False,
                  "sampler_metadata_only": True, "headless_refresh_hz_required": 10, "observation_seconds_required": 240,
                  "native_ready": False, "ready": False,
                  "springboard_validated": False, "ipa_execution_validated": False}
        post.durable_intent(target / "data-v2-ui-observer-intent.json", record)
        manifest[RECORD] = record
        profile.write_manifest(target, manifest)
        build = target / BUILD
        sampler, wrapper = compile_helpers(build, vm_id)
        hashes = [cdhash(wrapper), cdhash(sampler)]
        custom = trustcache_transition(base.read_bytes(), hashes, vm_id)
        stage.write_new(build / "original-stock-TrustCache", base.read_bytes())
        record.update(sampler_sha256=stage.digest(sampler), wrapper_sha256=stage.digest(wrapper),
                      owned_cdhashes=hashes, trustcache_sha256=hashlib.sha256(custom).hexdigest())
        profile.write_manifest(target, manifest)
        # Recheck all raw identities after compilation, before any attachment.
        evidence(target, manifest, current_scan=True)
        contract.validate_manifest(target, manifest, owned_launch_lock=lock_fd)
        reader.require_no_attached_backings(target, profile.SIZES)
        device, before = stage.attach_backing(target, manifest)
        mount = target / "DataV2UIObserverSystem"
        mounted = False
        try:
            system, _ = update.checked_updated_layout(owned_container(device), device, manifest, normal.UPDATE_UUID)
            mount.mkdir(mode=0o700)
            stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
            mounted = True
            mounted_guard(target, manifest, device, before, mount, system)
            unchanged_system(mount, manifest)
            keybag = stage.safe_path(mount, "usr/libexec/keybagd")
            original = stage.safe_path(mount, STOCK)
            guest_sampler = stage.safe_path(mount, SAMPLER)
            stock_stat = keybag.lstat()
            require(stat.S_ISREG(stock_stat.st_mode) and stock_stat.st_nlink == 1 and not stock_stat.st_mode & 0o022,
                    "Stock keybag mode/link differs")
            stage.write_new(build / "original-keybagd.public", keybag.read_bytes(), 0o755)
            post.verify_hash(build / "original-keybagd.public", post.PUBLIC_PINS["usr/libexec/keybagd"])
            record.update(stock_keybag_inode=stock_stat.st_ino, stock_keybag_mode=stat.S_IMODE(stock_stat.st_mode))
            profile.write_manifest(target, manifest)
            mounted_guard(target, manifest, device, before, mount, system)
            require(not original.exists() and not original.is_symlink(), "Stock destination appeared unexpectedly")
            os.rename(keybag, original)
            normal.require_stock_inode_preserved(stock_stat, original.lstat())
            post.verify_hash(original, post.PUBLIC_PINS["usr/libexec/keybagd"])
            mounted_guard(target, manifest, device, before, mount, system)
            stage.write_new(keybag, wrapper.read_bytes(), 0o755)
            mounted_guard(target, manifest, device, before, mount, system)
            stage.write_new(guest_sampler, sampler.read_bytes(), 0o755)
            unchanged_system(mount, manifest, installed=True, record=record)
            stage.run(["codesign", "--verify", "--strict", str(keybag)])
            stage.run(["codesign", "--verify", "--strict", str(guest_sampler)])
            mounted_guard(target, manifest, device, before, mount, system)
            stage.replace_known(tc, custom, BASE_TC_SHA)
            post.verify_hash(tc, record["trustcache_sha256"])
        finally:
            if mounted:
                mounted_guard(target, manifest, device, before, mount, system)
                stage.run(["/sbin/umount", str(mount)])
            profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
            update.checked_updated_layout(owned_container(device), device, manifest, normal.UPDATE_UUID)
            stage.run(["/usr/bin/hdiutil", "detach", device])
        record.update(state="installed", stock_keybag_same_inode_moved=True,
                      original_stock_program_bytes_preserved=True, owned_device_detached=True,
                      existing_six_volumes_preserved=True, post_install_backings=file_snapshots(target))
        manifest["virtual_staging"]["helper_sha256"].update(keybagd=record["wrapper_sha256"],
                                                          **{"huntmob-ui-process-observer": record["sampler_sha256"]})
        manifest["virtual_staging"]["trustcache_sha256"] = record["trustcache_sha256"]
        manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=record["trustcache_sha256"], bytes=len(custom),
                                                               format="raw-v1-own-ui-process-observer")
        profile.write_manifest(target, manifest)
        return record


def validate_for_boot(target, manifest):
    record = manifest.get(RECORD, {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] == VM_UUID and record.get("data_uuid") == DATA_UUID and
            record.get("state") == "installed" and record.get("source_sha256") == PINS and
            record.get("engine_binding") == manifest["engine_binding"] and
            record.get("identity_binding") == {k: manifest.get(k) for k in IDENTITY_KEYS} and
            record.get("host_data_mounted") is False and record.get("sampler_metadata_only") is True and
            record.get("headless_refresh_hz_required") == 10 and record.get("observation_seconds_required") == 240 and
            all(record.get(k) is True for k in ("stock_keybag_same_inode_moved", "original_stock_program_bytes_preserved",
                "owned_device_detached", "existing_six_volumes_preserved")), "Exact single-use metadata observer stage required")
    require(record.get("evidence") == evidence(target, manifest) and
            record.get("post_install_backings") == file_snapshots(target), "Evidence/backings changed after installation")
    source_pins(target / BUILD)
    for name, sha in (("huntmob-ui-process-observer", record["sampler_sha256"]), ("keybagd", record["wrapper_sha256"]),
                      ("original-keybagd.public", post.PUBLIC_PINS["usr/libexec/keybagd"]),
                      ("original-stock-TrustCache", BASE_TC_SHA)):
        post.verify_hash(target / BUILD / name, sha)
    expected = trustcache_transition((target / BUILD / "original-stock-TrustCache").read_bytes(), record["owned_cdhashes"], VM_UUID)
    tc = Path(manifest["firmware"]["files"]["RestoreTrustCache"]["path"])
    require(tc == target / "firmware/VirtualTrustCache" and hashlib.sha256(expected).hexdigest() == record["trustcache_sha256"] and
            manifest["virtual_staging"]["trustcache_sha256"] == record["trustcache_sha256"] and
            manifest["firmware"]["files"]["RestoreTrustCache"].get("format") == "raw-v1-own-ui-process-observer",
            "Observer cache binding differs")
    post.verify_hash(tc, record["trustcache_sha256"])
    expected_map = {**record["original_helper_map"], "keybagd": record["wrapper_sha256"],
                    "huntmob-ui-process-observer": record["sampler_sha256"]}
    require(manifest["virtual_staging"]["helper_sha256"] == expected_map, "Unexpected helper map changed")
    return record


def classify_result(log):
    """Known optional diagnostic failures may be restored, never promoted."""
    require(not any(value in log for value in ("fresh MKBCreateSystem", "ClassD initialization", "synthetic canary=",
                "HuntMob: provisioning checkpoint ready;", "HuntMob: post-keybag", "HuntMob: cold Class C")),
            "Unexpected provisioning/probe/checkpoint is not accepted")
    start = "HuntMob:ui-proc stock-init-start"
    exit0 = "HuntMob:ui-proc stock-init-exit=0 signal=0"
    exits = re.findall(r"^HuntMob:ui-proc stock-init-exit=(-?\d+) signal=(\d+)$", log, re.MULTILINE)
    require(exits == [("0", "0")] and log.count(start) == 1 and log.index(start) < log.index(exit0),
            "Exactly one successful unchanged stock init is required")
    failure_names = {"failed", "wrapper-guard-failed", "wrapper-data-guard-failed", "wrapper-post-init-guard-failed",
                     "observer-spawn-failed", "observer-group-failed"}
    known = {BEGIN, END, start, exit0}
    failures, spawned, rows = [], [], []
    for line in log.splitlines():
        if not line.startswith("HuntMob:ui-proc "):
            continue
        if line in known:
            continue
        value = line.removeprefix("HuntMob:ui-proc ")
        if value in failure_names:
            failures.append(value)
            continue
        match = re.fullmatch(r"HuntMob:ui-proc observer-spawned pid=([1-9]\d{0,9})", line)
        if match:
            require(int(match[1]) <= 2147483647, "Observer PID exceeds native signed range")
            spawned.append(int(match[1]))
            continue
        match = re.fullmatch(r"HuntMob:ui-proc sample=(\d{1,2}) service=(SpringBoard|backboardd|runningboardd) pid=([1-9]\d{0,9}) state=([1-7])", line)
        require(match is not None and int(match[1]) < 24 and int(match[3]) <= 2147483647,
                "Only bounded allowlisted process metadata is accepted")
        require(log.count(BEGIN) == 1 and log.index(BEGIN) < log.index(line) and
                (END not in log or log.index(line) < log.index(END)), "Metadata row outside collection window")
        rows.append((int(match[1]), match[2], int(match[3]), int(match[4])))
    require(len(failures) <= 4 and len(spawned) <= 1 and log.count(BEGIN) <= 1 and log.count(END) <= 1,
            "Repeated sampler/spawn/failure metadata refused")
    require(len(rows) <= 72 and len({(r[0], r[1]) for r in rows}) == len(rows) and
            [r[0] for r in rows] == sorted(r[0] for r in rows), "Duplicate, excessive or out-of-order sample rows")
    if BEGIN in log:
        require(log.index(exit0) < log.index(BEGIN), "Sampler began before stock init completed")
    if END in log:
        require(BEGIN in log and log.index(BEGIN) < log.index(END), "Sampler end without ordered begin")
    if not failures:
        require(len(spawned) == 1 and log.count(BEGIN) == log.count(END) == 1,
                "A completed sampler or explicit known diagnostic failure is required")
    require(log.count("Early boot complete. Continuing system boot.") == 1 and
            not any(t in log for t in ("panic(cpu", "Boot task failed:", "boot task failure:")),
            "Stock early-boot marker without panic/task failure is required")
    completed = not failures
    return {"sampler_completed": completed,
            "result": "metadata-collected-ui-unvalidated" if completed else "diagnostic-incomplete-stock-restorable",
            "diagnostic_failure_labels": failures,
            "sample_snapshots_reported": 24 if completed else None,
            "process_row_count": len(rows), "process_rows": [{"sample": a, "service": b, "pid": p, "state": v} for a, b, p, v in rows],
            "process_presence_is_not_ui_or_missing_process_crash_proof": True,
            "full_boot_validated": False, "springboard_validated": False, "ipa_execution_validated": False,
            "native_ready": False, "ready": False}


def consumed_observation(target, manifest, record):
    directory = Path(record.get("observation", ""))
    require(directory.parent == target and re.fullmatch(r"data-v2-observation-[0-9]{8}-[0-9]{6}", directory.name),
            "Exact owned native observation required")
    _, receipt_sha, receipt_identity = reader.stable_blob(directory / "observation.json", 1024 * 1024)
    proof = contract.read_metadata(directory / "observation.json")
    # This immutable first observer receipt omitted only this false field.
    # Preserve it verbatim and constrain compatibility to its exact provenance.
    full_boot_false = proof.get("full_boot_validated") is False or (
        "full_boot_validated" not in proof and
        directory.name == "data-v2-observation-20261015-183446" and
        receipt_sha == "13770ec679cfe6b5aa8c5fe76bbb9fab4267b4890255e702f6c14f40ec3f5c6a")
    require(proof.get("schema") == "huntmob.virtual-sep-data-observation.v2" and proof.get("vm_uuid") == VM_UUID and
            proof.get("engine_binding") == manifest["engine_binding"] and proof.get("data_profile") == contract.PROFILE and
            proof.get("data_profile_sha256") == manifest["data_profile_sha256"] and
            proof.get("ui_process_observer_requested") is True and proof.get("normal_boot_requested") is False and
            proof.get("sep_profile") == "serving" and proof.get("headless_refresh_hz_requested") == 10 and
            proof.get("headless_refresh_does_not_validate_ui") is True and
            proof.get("headless_refresh_accepted_count", 0) > 0 and proof.get("headless_refresh_error") is not True and
            proof.get("seconds") == 240 and 240 <= proof.get("elapsed_seconds", 0) <= 241 and
            proof.get("stop_reason") == "bounded-observation-ended" and proof.get("stock_early_boot_marker_observed") is True and
            proof.get("qmp_quit_requested") is True and proof.get("qmp_quit_accepted") is True and proof.get("exit_code") == 0 and
            full_boot_false and
            all(proof.get(k) is False for k in ("panic_observed", "own_checkpoint_unexpected", "checkpoint_observed",
                "virtual_mpe_memory_fault_observed", "mpe_rejected_revocation_observed", "ready", "native_ready",
                "springboard_validated", "ipa_execution_validated", "auxiliary_bootstrap_requested",
                "effaceable_ramdisk_requested", "effaceable_observer_requested", "cold_class_c_read_requested",
                "post_keybag_class_c_read_requested", "factorydata_seed_requested", "update_volume_bootstrap_requested")) and
            all(proof.get(k) == 0 for k in ("aess_rejected_command_count", "nvme_error_completion_count",
                "protected_io_rejection_count", "protected_gate_rejection_count")), "Clean completed exact metadata observation required")
    texts, hashes, snapshots = {}, {}, {}
    for name in ("boot.log", "trace.log"):
        blob, sha, identity = reader.stable_blob(directory / name, 64 * 1024 * 1024)
        require(sha == proof.get(name + "_sha256"), "Native observer log provenance changed")
        texts[name] = blob.decode(errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        hashes[name], snapshots[name] = sha, identity
    result = classify_result(texts["boot.log"])
    # Independently recompute the launcher's existing fixed metadata counters.
    from boot_ios_virtual_data_v2 import storage_failure_observations
    from boot_ios_virtual_profile import virtual_memory_observations
    memory = virtual_memory_observations(texts["trace.log"])
    storage = storage_failure_observations(texts["trace.log"])
    require(memory["aess_command_count"] == proof.get("aess_command_count") and memory["aess_command_count"] > 0 and
            memory["aess_rejected_command_count"] == 0 and not memory["virtual_mpe_memory_fault_observed"] and
            not storage["mpe_rejected_revocation_observed"] and
            all(storage[k] == 0 for k in ("nvme_error_completion_count", "protected_io_rejection_count",
                                         "protected_gate_rejection_count")), "Actual trace contradicts the clean metadata receipt")
    require(reader.path_identity(directory / "observation.json") == receipt_identity and
            all(reader.path_identity(directory / name) == identity for name, identity in snapshots.items()),
            "Native evidence changed during validation")
    return {"observation": str(directory), "observation_sha256": receipt_sha,
            "boot_log_sha256": hashes["boot.log"], "trace_log_sha256": hashes["trace.log"], **result}


def consume_restore(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    record = manifest.get(RECORD, {})
    require(record.get("state") == "launch-requested" and record.get("schema") == SCHEMA and
            record.get("vm_uuid") == vm_id == VM_UUID and record.get("source_sha256") == PINS and
            record.get("engine_binding") == manifest["engine_binding"] and
            record.get("identity_binding") == {k: manifest.get(k) for k in IDENTITY_KEYS} and
            record.get("host_data_mounted") is False and not (target / "data-v2-ui-observer-result.json").exists(),
            "Only one matching completed observer may be consumed and restored")
    with owned_lock(target, manifest):
        require(record.get("evidence") == evidence(target, manifest), "Frozen pre-observation evidence changed")
        source_pins(target / BUILD)
        result = consumed_observation(target, manifest, record)
        reader.require_no_attached_backings(target, profile.SIZES)
        tc = target / "firmware/VirtualTrustCache"
        build = target / BUILD
        post.verify_hash(tc, record["trustcache_sha256"])
        base = (build / "original-stock-TrustCache").read_bytes()
        expected = trustcache_transition(base, record["owned_cdhashes"], VM_UUID)
        require(hashlib.sha256(expected).hexdigest() == record["trustcache_sha256"], "Only this observer's two cache entries may be removed")
        post.durable_intent(target / "data-v2-ui-observer-result.json", {**result, "state": "observed-restoring-stock"})
        record.update(state="observed-restoring-stock", result=result)
        profile.write_manifest(target, manifest)
        device, before = stage.attach_backing(target, manifest)
        mount = target / "DataV2UIObserverRestoreSystem"
        mounted = False
        try:
            system, _ = update.checked_updated_layout(owned_container(device), device, manifest, normal.UPDATE_UUID)
            mount.mkdir(mode=0o700)
            stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
            mounted = True
            mounted_guard(target, manifest, device, before, mount, system)
            unchanged_system(mount, manifest, installed=True, record=record)
            keybag = stage.safe_path(mount, "usr/libexec/keybagd")
            original = stage.safe_path(mount, STOCK)
            sampler = stage.safe_path(mount, SAMPLER)
            saved = original.lstat()
            mounted_guard(target, manifest, device, before, mount, system)
            os.replace(original, keybag)
            normal.require_stock_inode_preserved(saved, keybag.lstat())
            post.verify_hash(keybag, post.PUBLIC_PINS["usr/libexec/keybagd"])
            mounted_guard(target, manifest, device, before, mount, system)
            post.verify_hash(sampler, record["sampler_sha256"])
            sampler.unlink()
            mounted_guard(target, manifest, device, before, mount, system)
            stage.replace_known(tc, base, record["trustcache_sha256"])
            post.verify_hash(tc, BASE_TC_SHA)
            unchanged_system(mount, manifest)
            stage.run(["codesign", "--verify", "--strict", str(keybag)])
        finally:
            if mounted:
                mounted_guard(target, manifest, device, before, mount, system)
                stage.run(["/sbin/umount", str(mount)])
            profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
            update.checked_updated_layout(owned_container(device), device, manifest, normal.UPDATE_UUID)
            stage.run(["/usr/bin/hdiutil", "detach", device])
        record.update(state="observed-original-restored", original_stock_same_inode_restored=True,
                      sampler_removed=True, original_trustcache_restored=True, owned_device_detached=True,
                      existing_six_volumes_preserved=True)
        manifest["virtual_staging"]["helper_sha256"] = record["original_helper_map"]
        manifest["virtual_staging"]["trustcache_sha256"] = BASE_TC_SHA
        manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=BASE_TC_SHA, bytes=len(base), format="stock-original-IM4P-rtsc")
        profile.write_manifest(target, manifest)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("install", "consume-restore"), default="install")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"schema": SCHEMA, "state": "plan-only", "target": str(contract.target_for(args.vm_uuid)),
                          "action": args.action, "metadata_only": True, "vm_started": False, "host_data_mounted": False,
                          "root_accessed": False, "ready": False, "native_ready": False,
                          "springboard_validated": False, "ipa_execution_validated": False}, indent=2))
        return
    require(args.authorized_lab, "System-only staging requires --authorized-lab")
    result = install(args.vm_uuid) if args.action == "install" else consume_restore(args.vm_uuid)
    print(json.dumps({k: result.get(k) for k in ("schema", "state", "vm_uuid", "data_uuid", "ready", "native_ready")}, indent=2))


if __name__ == "__main__":
    main()
