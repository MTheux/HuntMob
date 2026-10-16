#!/usr/bin/env python3
"""Own DATA-v2 auxiliary APFS bootstrap. Default is a read-only plan.

AUTHORIZED TESTING ONLY — ISOLATED LAB. No root access or guest launch.
Only the exact new cohort may reserve/delete its empty Data placeholder.
Native xART creation runs separately in the scoped, entitled guest helper.
"""
import argparse
import json
import os
import plistlib
import shutil
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_auxiliary import owned_container, volume_by_guid, add_volume

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-auxiliary.v2"
BOOTSTRAP_SCHEMA = "huntmob.virtual-sep-data-auxiliary-bootstrap.v2"
SOURCE_PINS = {
    "init_auxiliary_virtual_v1.c": "3e6dffe088e0cb883e4efc8e67ae880d514dd72462ee2eb8e8dc18fdcce6d819",
    "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050",
}
BASE_TC_SHA = "af33b3466bd828bf1ccaa1ab35d060bfcce62ade26ee74acf176501b00ea0d7f"
ENTITLEMENTS = {"com.apple.private.apfs.xart": True}


def layout(container, placeholder=None, auxiliary=False):
    """Exact public APFS identity/role checks; no disk operations."""
    prefix = container["ContainerReference"]
    expected = {1: ("System", ["System"])}
    if placeholder is not None:
        expected[2] = ("HuntMobEmptyDataSlotV2", ["Data"])
    if auxiliary:
        expected.update({3: ("xART", ["xART"]), 4: ("Hardware", ["Hardware"]),
                         5: ("Preboot", ["Preboot"])})
    volumes = container["Volumes"]
    require(len(volumes) == len(expected), "Unexpected volumes in DATA-v2 APFS layout")
    for index, (name, roles) in expected.items():
        matches = [v for v in volumes if v.get("DeviceIdentifier") == prefix + "s" + str(index)]
        require(len(matches) == 1 and matches[0].get("Roles") == roles and
                matches[0].get("Encryption") is False and not matches[0].get("MountPoint"),
                "DATA-v2 volume slot/role/encryption/mount differs")
        if index != 1:
            require(matches[0].get("Name") == name, "DATA-v2 volume name differs")
    if placeholder is not None:
        actual = volume_by_guid(container, placeholder["APFSVolumeUUID"])
        require(all(actual.get(k) == placeholder[k] for k in
                    ("Name", "Roles", "APFSVolumeUUID", "Encryption")) and
                actual.get("DeviceIdentifier") == prefix + "s2" and
                actual.get("CapacityInUse") == placeholder["CapacityInUse"],
                "The exact newly reserved empty Data placeholder changed")
    return next(v for v in volumes if v["DeviceIdentifier"] == prefix + "s1")


def validate(vm_id, action):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    require(manifest.get("v2_staging_complete") is True and
            manifest.get("virtual_staging", {}).get("phase") == "restore-checkpoint" and
            manifest.get("mnt2_empty_directory_verified") is True and
            not manifest.get("auxiliary_volumes_staged"), "Pristine DATA-v2 restore staging required")
    record = manifest.get("auxiliary_bootstrap_v2")
    if action == "reserve-bootstrap":
        require(record is None and not (target / "data-v2-auxiliary-intent.json").exists(),
                "DATA-v2 auxiliary bootstrap is single-use")
    else:
        require(record and record.get("schema") == BOOTSTRAP_SCHEMA and
                record.get("profile") == contract.PROFILE and record.get("vm_uuid") == vm_id and
                record.get("state") == "launch-requested" and
                not (target / "data-v2-auxiliary-finalize-intent.json").exists(),
                "Only the native new-cohort bootstrap may be finalized once")
    return target, manifest


def checked_tc(target, manifest):
    base = target / "firmware/RestoreTrustCache"
    tc = Path(manifest["firmware"]["files"]["RestoreTrustCache"]["path"])
    require(not base.is_symlink() and stage.digest(base) == BASE_TC_SHA and
            tc == target / "firmware/VirtualTrustCache" and not tc.is_symlink() and
            stage.digest(tc) == manifest["virtual_staging"]["trustcache_sha256"],
            "Pinned base or owned current trustcache differs")
    return base, tc


def mount_system(target, manifest, device, mount):
    container = owned_container(device)
    system = next(v for v in container["Volumes"] if v.get("Roles") == ["System"])
    mount.mkdir(mode=0o700)
    stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", "/dev/" + system["DeviceIdentifier"], str(mount)])
    return system


def require_empty_mnt2(mount):
    path = stage.safe_path(mount, "mnt2")
    require(path.is_dir() and not path.is_symlink() and not any(path.iterdir()),
            "Staged System /mnt2 must remain an empty ordinary directory")


def reserve_bootstrap(vm_id):
    target, manifest = validate(vm_id, "reserve-bootstrap")
    base, tc = checked_tc(target, manifest)
    for name, pin in SOURCE_PINS.items():
        source = stage.PROVISIONING / name
        require(not source.is_symlink() and stage.digest(source) == pin, "Reviewed auxiliary source differs")
    record = {"schema": BOOTSTRAP_SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id,
              "state": "preparing", "historical_data_or_keys_copied": False, "ready": False,
              "source_sha256": dict(SOURCE_PINS), "entitlements": ENTITLEMENTS}
    # Intent is durable before any image attachment, compiler, APFS or helper mutation.
    stage.write_new(target / "data-v2-auxiliary-intent.json", json.dumps(record, indent=2).encode())
    manifest["auxiliary_bootstrap_v2"] = record
    profile.write_manifest(target, manifest)
    build = target / "data-v2-auxiliary-build"
    build.mkdir(mode=0o700)
    for name in SOURCE_PINS:
        shutil.copyfile(stage.PROVISIONING / name, build / name)
        require(stage.digest(build / name) == SOURCE_PINS[name], "Copied source readback differs")
    ent = build / "entitlements.plist"
    stage.write_new(ent, plistlib.dumps(ENTITLEMENTS))
    binary = build / "init_data_protection"
    sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
    stage.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
               "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"',
               str(build / "init_auxiliary_virtual_v1.c"), "-o", str(binary)], timeout=60)
    stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.apple.seputil",
               "--entitlements", str(ent), str(binary)])
    stage.run(["codesign", "--verify", "--strict", str(binary)])
    actual = stage.run(["codesign", "-d", "--entitlements", ":-", str(binary)])
    require(plistlib.loads(actual.stdout) == ENTITLEMENTS, "Auxiliary parent entitlement differs")
    staging = manifest["virtual_staging"]
    userdata = target / "virtual-helper-build-restore-checkpoint/huntmob-prepare-userdata"
    require(not userdata.is_symlink() and stage.digest(userdata) == staging["helper_sha256"][userdata.name],
            "Original fresh Data helper changed")
    custom = stage.merged_trustcache(base.read_bytes(), [cdhash(binary), cdhash(userdata)], vm_id)
    device, before = stage.attach_backing(target, manifest)
    mount = target / "DataV2AuxiliarySystem"
    mounted = False
    try:
        initial = owned_container(device)
        system = layout(initial)
        reserve = add_volume(target, manifest, device, before, initial["ContainerReference"],
                             "HuntMobEmptyDataSlotV2", "D", 2, ["Data"])
        observed = volume_by_guid(owned_container(device), reserve["APFSVolumeUUID"])
        require(isinstance(observed.get("CapacityInUse"), int) and observed["CapacityInUse"] >= 0,
                "Empty placeholder capacity metadata missing")
        reserve["CapacityInUse"] = observed["CapacityInUse"]
        record.update(new_empty_placeholder=reserve, system_uuid=system["APFSVolumeUUID"])
        profile.write_manifest(target, manifest)
        mount_system(target, manifest, device, mount)
        mounted = True
        require_empty_mnt2(mount)
        for relative in ("usr/libexec/seputil", "usr/libexec/huntmob-original/init_data_protection"):
            require(stage.digest(stage.safe_path(mount, relative)) == stage.STOCK_SHA, "Stock verifier changed")
        wrapper = stage.safe_path(mount, "usr/libexec/init_data_protection")
        expected = staging["helper_sha256"]["init_data_protection"]
        require(not wrapper.is_symlink() and stage.digest(wrapper) == expected, "Owned restore wrapper differs")
        stage.write_new(build / "original-init_data_protection", wrapper.read_bytes(), 0o755)
        stage.write_new(build / "original-VirtualTrustCache", tc.read_bytes())
        record.update(original_wrapper_sha256=expected, original_trustcache_sha256=stage.digest(tc),
                      bootstrap_wrapper_sha256=stage.digest(binary))
        profile.write_manifest(target, manifest)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.replace_known(wrapper, binary.read_bytes(), expected)
        require(stage.digest(wrapper) == stage.digest(binary), "Bootstrap helper readback differs")
        stage.run(["codesign", "--verify", "--strict", str(wrapper)])
        stage.replace_known(tc, custom, staging["trustcache_sha256"])
    finally:
        if mounted:
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record.update(state="installed", trustcache_sha256=stage.digest(tc))
    staging["helper_sha256"]["init_data_protection"] = stage.digest(binary)
    staging["trustcache_sha256"] = stage.digest(tc)
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    profile.write_manifest(target, manifest)
    return record


def checked_observation(target, manifest):
    record = manifest["auxiliary_bootstrap_v2"]
    observation = Path(record.get("observation", ""))
    require(observation.parent == target and observation.name.startswith("data-v2-observation-") and
            observation.is_dir() and not observation.is_symlink(), "Native bootstrap observation must belong to this cohort")
    receipt = contract.read_metadata(observation / "observation.json")
    require(receipt.get("schema") == "huntmob.virtual-sep-data-observation.v2" and
            receipt.get("vm_uuid") == manifest["vm_uuid"] and
            receipt.get("data_profile_sha256") == manifest["data_profile_sha256"] and
            receipt.get("engine_binding") == manifest["engine_binding"] and
            receipt.get("auxiliary_bootstrap_requested") is True and receipt.get("checkpoint_observed") is True and
            receipt.get("panic_observed") is False and receipt.get("qmp_quit_accepted") is True and
            receipt.get("exit_code") == 0, "Native auxiliary bootstrap did not finish cleanly")
    log_path = observation / "boot.log"
    require(not log_path.is_symlink() and log_path.stat().st_size <= 64 * 1024 * 1024, "Native log differs")
    require(stage.digest(log_path) == receipt.get("boot.log_sha256"), "Native bootstrap log fingerprint differs from its receipt")
    log = log_path.read_text(errors="replace")
    require(all(log.count("HuntMob virtual v1: auxiliary step=" + str(n) + " status=0") == 1
                for n in (1, 2, 3)) and
            "HuntMob: provisioning checkpoint ready; virtual v1 auxiliary volumes prepared" in log,
            "All three actual guest APFS creation steps must succeed")
    return {"observation_sha256": stage.digest(observation / "observation.json"),
            "boot_log_sha256": stage.digest(log_path)}


def checked_startup_failure(target, manifest):
    """One exact pre-CPU Unix socket-length failure; no guest retry is inferred."""
    record = manifest.get("auxiliary_bootstrap_v2", {})
    require(record.get("schema") == BOOTSTRAP_SCHEMA and record.get("profile") == contract.PROFILE and
            record.get("vm_uuid") == manifest["vm_uuid"] and record.get("state") == "launch-requested" and
            manifest.get("root_provisioned") is True and not record.get("startup_failure_rearmed") and
            not (target / "data-v2-auxiliary-startup-rearm-intent.json").exists() and
            not (target / ".data-v2-launch.lock").exists() and not (target / "qmp.sock").exists(),
            "Only one stopped, pre-guest auxiliary startup failure may be rearmed")
    observation = Path(record.get("observation", ""))
    require(observation.parent == target and observation.name.startswith("data-v2-observation-") and
            observation.is_dir() and not observation.is_symlink(), "Startup failure must belong to this cohort")
    receipt_path = observation / "observation.json"
    receipt = contract.read_metadata(receipt_path)
    require(receipt.get("schema") == "huntmob.virtual-sep-data-observation.v2" and
            receipt.get("vm_uuid") == manifest["vm_uuid"] and receipt.get("data_profile") == contract.PROFILE and
            receipt.get("data_profile_sha256") == manifest["data_profile_sha256"] and
            receipt.get("engine_binding") == manifest["engine_binding"] and
            receipt.get("auxiliary_bootstrap_requested") is True and
            receipt.get("effaceable_ramdisk_requested") is False and
            receipt.get("effaceable_observer_requested") is False and receipt.get("root_pipe_delivered") is True and
            receipt.get("root_in_python") is False and receipt.get("stop_reason") == "engine-exited" and
            receipt.get("exit_code") == 1 and receipt.get("checkpoint_observed") is False and
            receipt.get("panic_observed") is False and receipt.get("qmp_quit_requested") is False and
            receipt.get("qmp_quit_accepted") is False and
            isinstance(receipt.get("elapsed_seconds"), (int, float)) and 0 <= receipt["elapsed_seconds"] <= 1 and
            receipt.get("aess_command_count") == 0 and receipt.get("aess_commands") == [] and
            receipt.get("virtual_mpe_controls") == [] and receipt.get("virtual_mpe_boot_jump_requested") is False and
            receipt.get("sep_os_alive_observed") is False and
            receipt.get("stock_data_protection_verifier_invoked") is False,
            "Receipt does not prove this exact pre-guest QMP startup failure")
    qmp = str(target / "qmp.sock")
    command_qmp = "unix:" + qmp + ",server=on,wait=off"
    command = receipt.get("command", [])
    require(isinstance(command, list) and command.count("-qmp") == 1 and
            command.index("-qmp") + 1 < len(command) and
            command[command.index("-qmp") + 1] == command_qmp and len(qmp.encode()) >= 104,
            "Only the exact original overlong QMP path may be corrected")
    expected = ("-qmp " + command_qmp + ": UNIX socket path '" + qmp + "' is too long\n"
                "Path must be less than 104 bytes\n").encode()
    log = observation / "boot.log"
    require(log.is_file() and not log.is_symlink() and log.stat().st_size == len(expected) and
            log.read_bytes() == expected and stage.digest(log) == receipt.get("boot.log_sha256"),
            "Startup log is not exactly the known pre-guest socket-length error")
    trace = observation / "trace.log"
    empty_sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    require(not trace.is_symlink() and (not trace.exists() or (trace.is_file() and trace.stat().st_size == 0)) and
            receipt.get("trace.log_sha256") == empty_sha, "Any trace activity forbids an automatic bootstrap retry")
    return {"original_observation": str(observation), "observation_sha256": stage.digest(receipt_path),
            "boot_log_sha256": stage.digest(log), "trace_log_sha256": empty_sha,
            "reason": "pre-guest-unix-qmp-path-too-long", "root_recreation_allowed": False,
            "guest_execution_observed": False, "maximum_retries": 1}


def rearm_startup_failure(vm_id):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    require(manifest.get("virtual_staging", {}).get("phase") == "restore-checkpoint" and
            manifest.get("auxiliary_volumes_staged") is not True, "Only the unexecuted auxiliary bootstrap is eligible")
    evidence = checked_startup_failure(target, manifest)
    intent = target / "data-v2-auxiliary-startup-rearm-intent.json"
    stage.write_new(intent, json.dumps({"schema": "huntmob.virtual-sep-data-startup-rearm.v2",
                    "vm_uuid": vm_id, **evidence, "ready": False}, indent=2).encode())
    descriptor = os.open(intent, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    record = manifest["auxiliary_bootstrap_v2"]
    record.update(startup_failure_rearmed=evidence, state="installed")
    # Preserve the original observation and every helper/placeholder/identity
    # field. The corrected launcher must look up the same already-created root.
    profile.write_manifest(target, manifest)
    return {"state": record["state"], "startup_failure_rearmed": evidence, "root_provisioned": True, "ready": False}


def copy_preboot(source, destination, mount):
    require(source.is_dir() and not source.is_symlink() and not destination.exists(), "Fresh Preboot source/destination differs")
    copied = {}
    for directory, folders, files in os.walk(source, followlinks=False):
        output = destination / Path(directory).relative_to(source)
        output.mkdir(mode=0o755, parents=True, exist_ok=True)
        for name in folders:
            require(not (Path(directory) / name).is_symlink(), "Preboot directory symlink refused")
        for name in files:
            original = Path(directory) / name
            require(original.is_file() and not original.is_symlink(), "Preboot source must be regular")
            stage.write_new(output / name, original.read_bytes(), 0o644)
            require(stage.digest(output / name) == stage.digest(original), "Preboot readback differs")
            copied[str((output / name).relative_to(mount))] = stage.digest(original)
    return copied


def finalize(vm_id):
    target, manifest = validate(vm_id, "finalize")
    bootstrap = manifest["auxiliary_bootstrap_v2"]
    evidence = checked_observation(target, manifest)
    _, tc = checked_tc(target, manifest)
    build = target / "data-v2-auxiliary-build"
    original, original_tc = build / "original-init_data_protection", build / "original-VirtualTrustCache"
    require(stage.digest(original) == bootstrap["original_wrapper_sha256"] and
            stage.digest(original_tc) == bootstrap["original_trustcache_sha256"], "Original owned wrapper/trustcache backup differs")
    record = {"schema": SCHEMA, "profile": contract.PROFILE, "vm_uuid": vm_id, **evidence,
              "historical_data_or_keys_copied": False, "ready": False, "completed": False}
    stage.write_new(target / "data-v2-auxiliary-finalize-intent.json", json.dumps(record, indent=2).encode())
    device, before = stage.attach_backing(target, manifest)
    mounted = []
    try:
        container = owned_container(device)
        reserve = bootstrap["new_empty_placeholder"]
        system = layout(container, reserve, auxiliary=True)
        require(system["APFSVolumeUUID"] == bootstrap["system_uuid"], "Stock System UUID changed")
        system_mount, preboot_mount = target / "DataV2FinalizeSystem", target / "DataV2FinalizePreboot"
        mount_system(target, manifest, device, system_mount)
        mounted.append(system_mount)
        require_empty_mnt2(system_mount)
        preboot_mount.mkdir(mode=0o700)
        preboot = next(v for v in container["Volumes"] if v.get("Roles") == ["Preboot"])
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", "/dev/" + preboot["DeviceIdentifier"], str(preboot_mount)])
        mounted.append(preboot_mount)
        ticket = manifest["virtual_staging"]["preboot_ticket_sha384"].upper()
        copied = copy_preboot(stage.safe_path(system_mount, "private/preboot/" + ticket), preboot_mount / ticket, preboot_mount)
        require(copied.get(ticket + "/usr/standalone/firmware/sep-firmware.img4") == stage.SEP["serving"][1],
                "Public serving SEP fingerprint differs")
        wrapper = stage.safe_path(system_mount, "usr/libexec/init_data_protection")
        stage.replace_known(wrapper, original.read_bytes(), bootstrap["bootstrap_wrapper_sha256"])
        require(stage.digest(wrapper) == bootstrap["original_wrapper_sha256"], "Original owned restore wrapper readback differs")
        stage.run(["codesign", "--verify", "--strict", str(wrapper)])
        stage.replace_known(tc, original_tc.read_bytes(), bootstrap["trustcache_sha256"])
        # Every mounted auxiliary is detached before delete/layout checks.
        for mount in reversed(mounted):
            stage.run(["/sbin/umount", str(mount)])
        mounted.clear()
        current = owned_container(device)
        layout(current, reserve, auxiliary=True)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        # No arbitrary Data UUID/path is accepted. This single newly created,
        # never-mounted, unencrypted reservation is the only deletable volume.
        placeholder = volume_by_guid(current, reserve["APFSVolumeUUID"])
        stage.run(["/usr/sbin/diskutil", "apfs", "deleteVolume", "/dev/" + placeholder["DeviceIdentifier"]], timeout=60)
        final = owned_container(device)
        layout(final, auxiliary=True)
        require(not any(v.get("APFSVolumeUUID") == reserve["APFSVolumeUUID"] for v in final["Volumes"]), "Placeholder remains")
        fields = ("Name", "Roles", "DeviceIdentifier", "APFSVolumeUUID", "Encryption")
        record.update(system_uuid=system["APFSVolumeUUID"], created_volumes=[{k: v[k] for k in fields}
                      for v in final["Volumes"] if v.get("Roles") != ["System"]],
                      preboot_file_sha256=copied, placeholder_deleted=True, data_slot_2_absent=True,
                      mnt2_empty_directory_verified=True, completed=True)
    finally:
        for mount in reversed(mounted):
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    manifest.update(auxiliary_volumes_staged=True, auxiliary_layout=record, owned_device_detached=True)
    bootstrap["state"] = "finalized-original-restored"
    manifest["virtual_staging"]["helper_sha256"]["init_data_protection"] = bootstrap["original_wrapper_sha256"]
    manifest["virtual_staging"]["trustcache_sha256"] = stage.digest(tc)
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    stage.write_new(target / "data-v2-auxiliary-completed.json", json.dumps(record, indent=2).encode())
    profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("reserve-bootstrap", "finalize", "rearm-startup-failure"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(contract.plan(args.vm_uuid, args.action), indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    if args.action == "rearm-startup-failure":
        result = rearm_startup_failure(args.vm_uuid)
    else:
        result = reserve_bootstrap(args.vm_uuid) if args.action == "reserve-bootstrap" else finalize(args.vm_uuid)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
