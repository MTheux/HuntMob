#!/usr/bin/env python3
"""Stage/consume one honest existing-probe cold read; default is a plan.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Never launches a guest, opens Keychain,
mounts/unlocks host Data or copies private key material. Install mounts only
the exact owned System volume after native fresh-Data evidence is validated.
"""
import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import uuid
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_auxiliary import owned_container, volume_by_guid
from stage_ios_virtual_data_v2_auxiliary import checked_tc, require_empty_mnt2, BASE_TC_SHA

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-cold-read.v2"
PINS = {
    "verify_cold_data_v2.c": "997463e28fba33edd17fe31cbe0003ee6a67d8c131dc64e66d833264ff7a9821",
    "cold_read_policy_v2.h": "798c469f419b143427c6859a8d091b5c76a5048e73ed8586e62732df3c9b4499",
    "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050",
}
CREATION_SOURCE_SHA = "1926ac9eddc4cccfa9fe22d94f8c40fc84a869a0b09a7d296e8468bb1b4c6953"
ENTITLEMENTS = {"com.apple.keystore.device": True}


def canonical_data_uuid(value):
    parsed = uuid.UUID(value)
    require(str(parsed).upper() == value and parsed.int != 0, "Canonical uppercase nonzero Data UUID required")
    return value


def require_probe_absent(data, public_canary):
    require(re.fullmatch(r"[0-9a-f]{64}", public_canary), "Public probe shape changed")
    require(public_canary.encode() not in data and bytes.fromhex(public_canary) not in data,
            "Cold verifier would contaminate plaintext System with the original probe")


def observation(target, manifest, name):
    require(re.fullmatch(r"data-v2-observation-[0-9]{8}-[0-9]{6}", name or ""), "Exact owned observation basename required")
    directory = target / name
    require(directory.is_dir() and not directory.is_symlink(), "Owned native observation missing")
    proof = contract.read_metadata(directory / "observation.json")
    require(proof.get("schema") == "huntmob.virtual-sep-data-observation.v2" and
            proof.get("vm_uuid") == manifest["vm_uuid"] and proof.get("data_profile") == contract.PROFILE and
            proof.get("data_profile_sha256") == manifest["data_profile_sha256"] and
            proof.get("engine_binding") == manifest["engine_binding"] and proof.get("sep_profile") == "serving" and
            proof.get("qmp_quit_requested") is True and proof.get("qmp_quit_accepted") is True and
            proof.get("exit_code") == 0 and proof.get("checkpoint_observed") is True and
            proof.get("panic_observed") is False and proof.get("virtual_mpe_memory_fault_observed") is False and
            proof.get("mpe_rejected_revocation_observed") is False,
            "Native observation must be a clean matching serving-profile checkpoint")
    require(all(proof.get(key) == 0 for key in ("aess_rejected_command_count", "nvme_error_completion_count",
                "protected_io_rejection_count", "protected_gate_rejection_count")), "Native crypto/storage errors forbid staging")
    texts = []
    for name in ("boot.log", "trace.log"):
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 * 1024 * 1024 and
                stage.digest(path) == proof.get(name + "_sha256"), "Native log/hash changed")
        texts.append(path.read_text(errors="replace"))
    return directory, proof, texts[0], texts[1]


def creation_evidence(target, manifest, name):
    directory, proof, log, trace = observation(target, manifest, name)
    require(all(proof.get(key) is False for key in ("auxiliary_bootstrap_requested", "effaceable_ramdisk_requested",
                "effaceable_observer_requested")) and proof.get("stock_data_protection_verifier_invoked") is True and
            proof.get("aess_command_count", 0) > 0, "Fresh normal Data creation must follow the unchanged stock verifier")
    markers = ("HuntMob: ClassD initialization status=0",
               "HuntMob virtual v1: fresh MKBCreateSystem returned zero",
               "HuntMob: provisioning checkpoint ready; virtual v1 fresh protected Data prepared")
    require(all(log.count(marker) == 1 for marker in markers), "Actual fresh ClassD/MKB/roundtrip checkpoint required")
    probes = re.findall(r"^HuntMob virtual v1: Class C roundtrip; synthetic canary=([0-9a-f]{64})$", log, re.MULTILINE)
    require(len(probes) == 1, "Exactly one public 64-byte Class C canary is required")
    accepted = set(re.findall(r"^pci_nvme_apple_ans_protected_gate sqid=(\d+) cid=(\d+) stage=sq-context result=accepted$",
                              trace, re.MULTILINE))
    writes = set(re.findall(r"^pci_nvme_apple_ans_complete sqid=(\d+) cid=(\d+) opcode=0x01 status=0x0000$",
                            trace, re.MULTILINE))
    require(bool(accepted & writes), "At least one authenticated protected write must complete successfully")
    return {"observation": str(directory), "receipt_sha256": stage.digest(directory / "observation.json"),
            "boot_log_sha256": proof["boot.log_sha256"], "trace_log_sha256": proof["trace.log_sha256"],
            "expected_public_canary": probes[0], "canary_is_public_fixture": True}


def checked_layout(container, whole_device, manifest, data_uuid, system_mount=None):
    canonical_data_uuid(data_uuid)
    require(re.fullmatch(r"/dev/disk[0-9]+", whole_device) and
            [v.get("DeviceIdentifier") for v in container.get("PhysicalStores", [])] == [whole_device[5:] + "s1"],
            "One exact newly owned physical store is required")
    reference = container.get("ContainerReference", "")
    require(re.fullmatch(r"disk[0-9]+", reference), "Invalid owned container identifier")
    volumes = container.get("Volumes", [])
    require(len(volumes) == 5 and len({v.get("APFSVolumeUUID") for v in volumes}) == 5,
            "Exactly five independently identified System/Data/auxiliary volumes required")
    auxiliary = manifest["auxiliary_layout"]
    expected = {1: ("System", auxiliary["system_uuid"], False), 2: ("Data", data_uuid, True)}
    created = auxiliary.get("created_volumes", [])
    for index, role in ((3, "xART"), (4, "Hardware"), (5, "Preboot")):
        matches = [v for v in created if v.get("Roles") == [role]]
        require(len(matches) == 1, "Bound auxiliary UUID is missing or ambiguous")
        expected[index] = (role, matches[0]["APFSVolumeUUID"], False)
    for index, (role, identity, encrypted) in expected.items():
        matches = [v for v in volumes if v.get("DeviceIdentifier") == reference + "s" + str(index)]
        require(len(matches) == 1 and matches[0].get("Roles") == [role] and
                matches[0].get("APFSVolumeUUID") == identity and matches[0].get("Encryption") is encrypted,
                "Volume slot/UUID/role/encryption state differs")
        # APFS LIST can omit/stale-cache a manually mounted System path. This
        # topology check deliberately does not attest a live System mount;
        # validate_system_mount() binds that mount through the real VFS device.
        if index != 1 or system_mount is None:
            require(not matches[0].get("MountPoint"), "Unexpected mounted volume")
        if index == 2:
            require(matches[0].get("Name") == "Data" and matches[0].get("Locked") is True,
                    "Exact encrypted Data must stay locked and unmounted on the host")
        elif index > 2:
            require(matches[0].get("Name") == role, "Auxiliary volume name changed")
    return "/dev/" + reference + "s1"


def validate_system_mount(mount, system, manifest):
    require(re.fullmatch(r"/dev/disk[0-9]+s1", system), "Exact owned System volume path required")
    point, block = mount.lstat(), Path(system).lstat()
    require(stat.S_ISDIR(point.st_mode) and stat.S_ISBLK(block.st_mode) and
            mount.stat().st_dev == Path(system).stat().st_rdev,
            "Mounted directory is not the exact System block device")
    info = profile.run_plist(["/usr/sbin/diskutil", "info", "-plist", system])
    require(info.get("DeviceNode") == system and info.get("DeviceIdentifier") == system[5:],
            "System device metadata contradicts its owned path")
    if "Mounted" in info:
        require(info["Mounted"] is True, "System metadata explicitly reports unmounted")
    if "MountPoint" in info:
        value = info["MountPoint"]
        require(isinstance(value, str) and value and Path(value).exists() and
                os.path.samefile(value, mount), "System INFO mountpoint contradicts the real VFS mount")
    for key in ("APFSVolumeUUID", "VolumeUUID"):
        if key in info:
            require(info[key] == manifest["auxiliary_layout"]["system_uuid"], "System INFO UUID contradicts the scoped volume")
    if "FilesystemType" in info:
        require(info["FilesystemType"] == "apfs", "System filesystem metadata contradicts APFS")


def install(vm_id, data_uuid, data_observation):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    canonical_data_uuid(data_uuid)
    staging = manifest.get("virtual_staging", {})
    require(manifest.get("root_provisioned") is True and manifest.get("restore_checkpoint_observed") is True and
            manifest.get("effaceable_cold_persistence_observed") is True and
            staging.get("phase") == "data-checkpoint" and manifest.get("auxiliary_layout", {}).get("completed") is True and
            manifest["auxiliary_layout"].get("data_slot_2_absent") is True and
            staging.get("source_sha256", {}).get("prepare_userdata_virtual_v1.c") == CREATION_SOURCE_SHA and
            manifest.get("cold_read_v2") is None and not (target / "data-v2-cold-read-intent.json").exists(),
            "Only a fresh successfully created own DATA-v2 can receive one cold verifier")
    evidence = creation_evidence(target, manifest, data_observation)
    for name, pin in PINS.items():
        require(not (stage.PROVISIONING / name).is_symlink() and stage.digest(stage.PROVISIONING / name) == pin,
                "Reviewed cold verifier source changed")
    base, tc = checked_tc(target, manifest)
    record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id, "state": "preparing",
              "data_uuid": data_uuid, "creation_evidence": evidence, "source_sha256": dict(PINS),
              "root_accessed": False, "host_data_mounted": False, "class_d_or_newfs_or_mkb_create_called": False,
              "cold_read_validated": False, "native_ready": False, "ready": False}
    expected_digest = hashlib.sha256(evidence["expected_public_canary"].encode()).hexdigest()
    record["expected_probe_sha256"] = expected_digest
    stage.write_new(target / "data-v2-cold-read-intent.json", json.dumps(record, indent=2).encode())
    manifest["cold_read_v2"] = record
    profile.write_manifest(target, manifest)
    build = target / "data-v2-cold-read"
    build.mkdir(mode=0o700)
    for name, pin in PINS.items():
        shutil.copyfile(stage.PROVISIONING / name, build / name)
        require(stage.digest(build / name) == pin, "Cold source copy changed")
    ent = build / "entitlements.plist"
    stage.write_new(ent, plistlib.dumps(ENTITLEMENTS))
    sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
    binary = build / "huntmob-prepare-userdata"
    stage.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
               "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"',
               '-DHUNTMOB_EXPECTED_DATA_UUID="' + data_uuid + '"',
               '-DHUNTMOB_EXPECTED_CANARY_SHA256="' + expected_digest + '"',
               str(build / "verify_cold_data_v2.c"), "-o", str(binary)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.huntmob.virtual-sep.cold-read",
               "--entitlements", str(ent), str(binary)])
    stage.run(["codesign", "--verify", "--strict", str(binary)])
    actual = stage.run(["codesign", "-d", "--entitlements", ":-", str(binary)])
    require(plistlib.loads(actual.stdout) == ENTITLEMENTS, "Cold verifier gained unexpected entitlements")
    require_probe_absent(binary.read_bytes(), evidence["expected_public_canary"])
    wrapper = target / "virtual-helper-build-data-checkpoint/init_data_protection"
    require(stage.digest(wrapper) == staging["helper_sha256"]["init_data_protection"], "Original stock wrapper changed")
    custom_tc = stage.merged_trustcache(base.read_bytes(), [cdhash(wrapper), cdhash(binary)], vm_id)
    require_probe_absent(custom_tc, evidence["expected_public_canary"])
    device, before = stage.attach_backing(target, manifest)
    mounted = False
    mount = target / "DataV2ColdReadSystem"
    try:
        container = owned_container(device)
        system = checked_layout(container, device, manifest, data_uuid)
        # Host never mounts/unlocks Data. The only mounted path is System s1.
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", system, str(mount)])
        mounted = True
        validate_system_mount(mount, system, manifest)
        require_empty_mnt2(mount)
        for path in ("usr/libexec/seputil", "usr/libexec/huntmob-original/init_data_protection"):
            require(stage.digest(stage.safe_path(mount, path)) == stage.STOCK_SHA, "Stock verifier/seputil changed")
        guest = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        expected = staging["helper_sha256"]["huntmob-prepare-userdata"]
        require(not guest.is_symlink() and stage.digest(guest) == expected, "Current own Data helper changed")
        stage.write_new(build / "original-huntmob-prepare-userdata", guest.read_bytes(), 0o755)
        stage.write_new(build / "original-VirtualTrustCache", tc.read_bytes())
        record.update(original_helper_sha256=expected, original_trustcache_sha256=stage.digest(tc),
                      helper_sha256=stage.digest(binary), trustcache_sha256=hashlib.sha256(custom_tc).hexdigest(),
                      host_data_uuid=data_uuid, host_data_encrypted=True, host_data_locked=True,
                      host_layout_sha256=contract.canonical_hash(container))
        profile.write_manifest(target, manifest)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.replace_known(guest, binary.read_bytes(), expected)
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        require(stage.digest(guest) == record["helper_sha256"], "Cold helper readback changed")
        stage.replace_known(tc, custom_tc, staging["trustcache_sha256"])
        checked_layout(owned_container(device), device, manifest, data_uuid, system_mount=mount)
        validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record["state"] = "installed"
    record["binary_and_trustcache_original_probe_absent"] = True
    staging["helper_sha256"]["huntmob-prepare-userdata"] = record["helper_sha256"]
    staging["trustcache_sha256"] = stage.digest(tc)
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    profile.write_manifest(target, manifest)
    return record


def checked_partial_install(target, manifest):
    """Read-only exact-shape verification; does not mount, compile or replace."""
    record = manifest.get("cold_read_v2", {})
    staging = manifest.get("virtual_staging", {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] and record.get("state") == "preparing" and
            record.get("source_sha256") == PINS and record.get("host_data_mounted") is False and
            record.get("host_data_encrypted") is True and record.get("host_data_locked") is True and
            record.get("host_data_uuid") == record.get("data_uuid") and
            record.get("root_accessed") is False and record.get("class_d_or_newfs_or_mkb_create_called") is False and
            not record.get("observation") and record.get("cold_read_validated") is False and
            manifest.get("root_provisioned") is True and manifest.get("restore_checkpoint_observed") is True and
            manifest.get("effaceable_cold_persistence_observed") is True and
            staging.get("phase") == "data-checkpoint" and
            staging.get("source_sha256", {}).get("prepare_userdata_virtual_v1.c") == CREATION_SOURCE_SHA,
            "Only the exact never-launched readback-pending partial install can be completed")
    canonical_data_uuid(record["data_uuid"])
    require(not (target / "data-v2-cold-read-complete-partial-intent.json").exists() and
            not (target / "data-v2-cold-read-result.json").exists(), "Partial completion is single-use")
    intent_path = target / "data-v2-cold-read-intent.json"
    intent = contract.read_metadata(intent_path)
    intent_keys = {"schema", "profile", "vm_uuid", "state", "data_uuid", "creation_evidence", "source_sha256",
                   "root_accessed", "host_data_mounted", "class_d_or_newfs_or_mkb_create_called", "cold_read_validated",
                   "native_ready", "ready", "expected_probe_sha256"}
    require(set(intent) == intent_keys and intent.get("state") == "preparing" and
            all(record.get(key) == value for key, value in intent.items()),
            "Original durable install intent no longer matches this partial install")
    evidence = record["creation_evidence"]
    previous = Path(evidence.get("observation", ""))
    require(previous.parent == target and creation_evidence(target, manifest, previous.name) == evidence,
            "The native Data creation receipt/probe binding changed")
    require(record.get("expected_probe_sha256") == hashlib.sha256(evidence["expected_public_canary"].encode()).hexdigest(),
            "Expected public probe digest changed")
    for directory in target.glob("data-v2-observation-*"):
        path = directory / "observation.json"
        if path.exists():
            require(contract.read_metadata(path).get("cold_class_c_read_requested") is not True,
                    "A cold verifier observation already exists; recovery cannot rearm it")
    build = target / "data-v2-cold-read"
    for name, expected in PINS.items():
        require(not (build / name).is_symlink() and stage.digest(build / name) == expected and
                not (stage.PROVISIONING / name).is_symlink() and stage.digest(stage.PROVISIONING / name) == expected,
                "Partial-install source binding changed")
    original, binary = build / "original-huntmob-prepare-userdata", build / "huntmob-prepare-userdata"
    original_tc, tc = build / "original-VirtualTrustCache", target / "firmware/VirtualTrustCache"
    require(all(re.fullmatch(r"[0-9a-f]{64}", str(record.get(key, ""))) for key in
                ("original_helper_sha256", "original_trustcache_sha256", "helper_sha256", "trustcache_sha256")),
            "Both original and new partial-install hashes are mandatory")
    require(staging["helper_sha256"]["huntmob-prepare-userdata"] == record["original_helper_sha256"] and
            staging["trustcache_sha256"] == record["original_trustcache_sha256"] and
            manifest["firmware"]["files"]["RestoreTrustCache"]["path"] == str(tc) and
            manifest["firmware"]["files"]["RestoreTrustCache"]["sha256"] == record["original_trustcache_sha256"] and
            record["helper_sha256"] != record["original_helper_sha256"] and
            record["trustcache_sha256"] != record["original_trustcache_sha256"],
            "Manifest is not the exact old-metadata/new-files partial-install shape")
    for path, expected in ((original, record["original_helper_sha256"]), (original_tc, record["original_trustcache_sha256"]),
                           (binary, record["helper_sha256"]), (tc, record["trustcache_sha256"])):
        profile.fingerprint(path)
        require(stage.digest(path) == expected, "Partial-install file/backup hash changed")
    base = target / "firmware/RestoreTrustCache"
    require(not base.is_symlink() and stage.digest(base) == BASE_TC_SHA, "Pinned base trustcache changed")
    wrapper = target / "virtual-helper-build-data-checkpoint/init_data_protection"
    require(not wrapper.is_symlink() and stage.digest(wrapper) == staging["helper_sha256"]["init_data_protection"],
            "Unchanged stock-verifier wrapper binding differs")
    expected_tc = stage.merged_trustcache(base.read_bytes(), [cdhash(wrapper), cdhash(binary)], manifest["vm_uuid"])
    require(hashlib.sha256(expected_tc).hexdigest() == record["trustcache_sha256"] and tc.read_bytes() == expected_tc,
            "Current trustcache is not exactly the reviewed wrapper plus new cold helper")
    require_probe_absent(binary.read_bytes(), evidence["expected_public_canary"])
    require_probe_absent(expected_tc, evidence["expected_public_canary"])
    return record


def complete_partial_install(vm_id):
    """Read back an already-written helper/TC; never rewrite them or provision."""
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    record = checked_partial_install(target, manifest)
    recovery = {"schema": "huntmob.virtual-sep-data-cold-read-partial-completion.v2", "vm_uuid": vm_id,
                "data_uuid": record["data_uuid"], "original_intent_sha256": stage.digest(target / "data-v2-cold-read-intent.json"),
                "preparing_record_sha256": contract.canonical_hash(record), "readback_existing_only": True,
                "helper_or_trustcache_rewritten": False, "data_mounted": False, "ready": False}
    stage.write_new(target / "data-v2-cold-read-complete-partial-intent.json", json.dumps(recovery, indent=2).encode())
    device, before = stage.attach_backing(target, manifest)
    mounted = False
    mount = target / "DataV2ColdReadCompletePartialSystem"
    try:
        system = checked_layout(owned_container(device), device, manifest, record["data_uuid"])
        mount.mkdir(mode=0o700, exist_ok=False)
        stage.run(["/sbin/mount_apfs", "-o", "rdonly,nobrowse,noowners", system, str(mount)])
        mounted = True
        validate_system_mount(mount, system, manifest)
        require_empty_mnt2(mount)
        for name in ("usr/libexec/seputil", "usr/libexec/huntmob-original/init_data_protection"):
            require(stage.digest(stage.safe_path(mount, name)) == stage.STOCK_SHA, "Stock verifier/seputil readback changed")
        wrapper = stage.safe_path(mount, "usr/libexec/init_data_protection")
        require(stage.digest(wrapper) == manifest["virtual_staging"]["helper_sha256"]["init_data_protection"],
                "Live unchanged wrapper differs")
        guest = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        profile.fingerprint(guest)
        require(stage.digest(guest) == record["helper_sha256"], "Already-installed cold helper differs; no rewrite attempted")
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        entitlements = stage.run(["codesign", "-d", "--entitlements", ":-", str(guest)])
        require(plistlib.loads(entitlements.stdout) == ENTITLEMENTS, "Installed cold helper entitlements differ")
        require_probe_absent(guest.read_bytes(), record["creation_evidence"]["expected_public_canary"])
        tc = target / "firmware/VirtualTrustCache"
        require(stage.digest(tc) == record["trustcache_sha256"], "Already-written cold trustcache changed")
        require_probe_absent(tc.read_bytes(), record["creation_evidence"]["expected_public_canary"])
        checked_layout(owned_container(device), device, manifest, record["data_uuid"], system_mount=mount)
        validate_system_mount(mount, system, manifest)
    finally:
        if mounted:
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="installed", binary_and_trustcache_original_probe_absent=True,
                  partial_install_completed_by_readback=True,
                  partial_completion_intent_sha256=stage.digest(target / "data-v2-cold-read-complete-partial-intent.json"))
    manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] = record["helper_sha256"]
    manifest["virtual_staging"]["trustcache_sha256"] = record["trustcache_sha256"]
    tc = target / "firmware/VirtualTrustCache"
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=record["trustcache_sha256"], bytes=tc.stat().st_size)
    contract.validate_manifest(target, manifest)
    profile.write_manifest(target, manifest)
    return record


def validate_for_boot(target, manifest):
    record = manifest.get("cold_read_v2", {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] and record.get("state") == "installed" and
            record.get("source_sha256") == PINS and record.get("host_data_encrypted") is True and
            record.get("host_data_locked") is True and record.get("host_data_mounted") is False and
            record.get("helper_sha256") == manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"],
            "Exactly the installed existing-probe-only cold verifier is required")
    canonical_data_uuid(record["data_uuid"])
    build = target / "data-v2-cold-read"
    for name, pin in PINS.items():
        require(stage.digest(build / name) == pin, "Cold source binding changed")
    require(stage.digest(build / "huntmob-prepare-userdata") == record["helper_sha256"], "Cold verifier binary changed")
    require_probe_absent((build / "huntmob-prepare-userdata").read_bytes(), record["creation_evidence"]["expected_public_canary"])
    return record


def classify_result(log):
    results = re.findall(r"^HuntMob: cold Class C result=([a-z-]+)$", log, re.MULTILINE)
    before = re.findall(r"^HuntMob: cold Class C unlocked-since-boot before=([01])$", log, re.MULTILINE)
    after = re.findall(r"^HuntMob: cold Class C unlocked-since-boot after=([01])$", log, re.MULTILINE)
    require(len(results) == len(before) == len(after) == 1, "Exactly one classified cold-read result and unlock pair required")
    result = results[0]
    require(result in {"afu-read-match", "bfu-denied", "bfu-mount-unvalidated", "unlock-state-changed-unvalidated"},
            "Unknown cold-read result")
    identity = "HuntMob: cold Class C exact Data UUID and readonly CPROTECT matched" in log
    if result == "afu-read-match":
        require(before == after == ["1"] and identity, "AFU read requires unlock and exact readonly Data identity")
    elif result in {"bfu-denied", "bfu-mount-unvalidated"}:
        require(before == after == ["0"] and (identity or result == "bfu-mount-unvalidated"),
                "BFU denial must remain distinct from an invalid identity or AFU I/O failure")
    else:
        require(before != after and identity, "Unlock transition requires matching Data identity")
    require(not any(token in log for token in ("ClassD initialization", "fresh MKBCreateSystem", "synthetic canary=")),
            "Cold helper must not provision or create a new probe")
    return {"result": result, "cold_read_validated": result == "afu-read-match",
            "bfu_expected_denial_observed": result == "bfu-denied", "read_unvalidated": result != "afu-read-match"}


def consume(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    record = manifest.get("cold_read_v2", {})
    require(record.get("schema") == SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == vm_id and record.get("state") == "launch-requested" and
            not (target / "data-v2-cold-read-result.json").exists(), "One actual cold verifier launch is required")
    path = Path(record.get("observation", ""))
    require(path.parent == target, "Cold observation belongs to another cohort")
    directory, proof, log, trace = observation(target, manifest, path.name)
    require(proof.get("cold_class_c_read_requested") is True, "Explicit cold-read launch receipt required")
    result = classify_result(log)
    record.update(state="observed", **result,
                  observation_sha256=stage.digest(directory / "observation.json"),
                  boot_log_sha256=proof["boot.log_sha256"], trace_log_sha256=proof["trace.log_sha256"])
    stage.write_new(target / "data-v2-cold-read-result.json", json.dumps(record, indent=2).encode())
    profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("install", "consume", "complete-partial-install"), default="install")
    parser.add_argument("--data-uuid")
    parser.add_argument("--data-observation")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        plan = contract.plan(args.vm_uuid, "cold-read-" + args.action)
        plan.update(data_uuid=args.data_uuid, data_observation=args.data_observation,
                    reads_existing_probe_only=True, attempts_keybag_unlock=False)
        print(json.dumps(plan, indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    if args.action == "install":
        require(args.data_uuid and args.data_observation, "Exact native Data UUID and creation observation required")
        result = install(args.vm_uuid, args.data_uuid, args.data_observation)
    elif args.action == "complete-partial-install":
        result = complete_partial_install(args.vm_uuid)
    else:
        result = consume(args.vm_uuid)
    print(json.dumps({key: result.get(key) for key in
                      ("state", "data_uuid", "result", "cold_read_validated", "ready", "native_ready")}, indent=2))


if __name__ == "__main__":
    main()
