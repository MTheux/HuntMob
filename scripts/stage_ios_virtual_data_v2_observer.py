#!/usr/bin/env python3
"""Stage/consume one cold effaceable observer for the new own DATA-v2 cohort.

AUTHORIZED TESTING ONLY — ISOLATED LAB. Default is a read-only plan.
No Keychain access, guest launch, ClassD call or filesystem creation here.
"""
import argparse
import json
import plistlib
import re
import shutil
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
from install_auxiliary_bootstrap_vm import cdhash
from stage_ios_virtual_auxiliary import owned_container
from stage_ios_virtual_data_v2_auxiliary import checked_tc, layout, require_empty_mnt2

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-observer.v2"
PINS = {"prepare_userdata_virtual_v1.c": "1926ac9eddc4cccfa9fe22d94f8c40fc84a869a0b09a7d296e8468bb1b4c6953",
        "virtual_v1_scope.h": "4b392ea68fed100e76d0dfd1030bc7026d069a4813f0b77e6927c0e851eda050"}
STOP_MARKER = "HuntMob: provisioning checkpoint ready; effaceable observation only; formatted=1"
ENTITLEMENTS_SHA = "52c3e77265406a27eaf9d704847a9d2faf90e8917d9f2146d8f9ab209e002b29"


def native_observation(target, manifest, record, flag):
    observation = Path(record.get("observation", ""))
    require(observation.parent == target and observation.name.startswith("data-v2-observation-") and
            observation.is_dir() and not observation.is_symlink(), "Native observation must belong to this DATA-v2 cohort")
    receipt = contract.read_metadata(observation / "observation.json")
    require(receipt.get("schema") == "huntmob.virtual-sep-data-observation.v2" and
            receipt.get("vm_uuid") == manifest["vm_uuid"] and
            receipt.get("data_profile_sha256") == manifest["data_profile_sha256"] and
            receipt.get("engine_binding") == manifest["engine_binding"] and
            receipt.get(flag) is True and receipt.get("checkpoint_observed") is True and
            receipt.get("panic_observed") is False and receipt.get("qmp_quit_accepted") is True and
            receipt.get("exit_code") == 0, "Native observation did not finish cleanly under this exact contract")
    texts = []
    for name in ("boot.log", "trace.log"):
        path = observation / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 * 1024 * 1024,
                "Native observation log must be bounded and independent")
        require(stage.digest(path) == receipt.get(name + "_sha256"), "Native log fingerprint differs from its receipt")
        texts.append(path.read_text(errors="replace"))
    return observation, texts[0], texts[1]


def validate_formatted_ramdisk(target, manifest):
    record = manifest.get("effaceable_ramdisk_v2", {})
    require(record.get("schema") == "huntmob.virtual-sep-data-effaceable.v2" and
            record.get("state") == "launch-requested" and record.get("vm_uuid") == manifest["vm_uuid"] and
            record.get("profile") == contract.PROFILE, "The new-cohort native trusted initializer is required")
    observation, log, trace = native_observation(target, manifest, record, "effaceable_ramdisk_requested")
    required = ("HuntMob: trusted effaceable root device-is-md0=1",
                "HuntMob: preloaded NVMe online exit=0 signal=0",
                "HuntMob: trusted effaceable before status=0 count=1 formatted=0",
                "HuntMob: trusted effaceable stock format status=0",
                "HuntMob: trusted effaceable after status=0 count=1 formatted=1",
                "HuntMob: provisioning checkpoint ready; trusted effaceable formatted=1")
    require(all(log.count(value) == 1 for value in required) and
            not any(value in log for value in ("ClassD initialization", "fresh MKBCreateSystem", "synthetic canary=")) and
            re.search(r"pci_nvme_apple_ans_submit sqid=1 cid=\d+ opcode=0x01 nsid=6(?:\s|$)", trace),
            "Trusted formatting requires actual query0/stockformat0/query1 and namespace6 writes")
    return {"observation": str(observation), "receipt_sha256": stage.digest(observation / "observation.json"),
            "boot_log_sha256": stage.digest(observation / "boot.log"), "trace_log_sha256": stage.digest(observation / "trace.log")}


def validate_for_boot(target, manifest):
    record = manifest.get("effaceable_observer_v2", {})
    require(record.get("schema") == SCHEMA and record.get("vm_uuid") == manifest["vm_uuid"] and
            record.get("profile") == contract.PROFILE and record.get("state") == "installed" and
            manifest.get("virtual_staging", {}).get("phase") == "data-checkpoint" and
            record.get("observe_only") is True and record.get("source_sha256") == PINS and
            record.get("observer_sha256") == manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"],
            "Exactly the installed observation-only helper is required before cold boot")
    build = target / "data-v2-effaceable-observer"
    require(stage.digest(build / "huntmob-prepare-userdata") == record["observer_sha256"], "Observer binary changed")
    for name, sha in PINS.items():
        require(stage.digest(build / name) == sha, "Observer source changed")
    return validate_formatted_ramdisk(target, manifest)


def change(vm_id, finalize=False):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    require(manifest.get("restore_checkpoint_observed") is True and
            manifest.get("virtual_staging", {}).get("phase") == "data-checkpoint" and
            manifest.get("auxiliary_layout", {}).get("completed") is True and
            manifest["auxiliary_layout"].get("data_slot_2_absent") is True,
            "Fresh post-restore DATA-v2 checkpoint required")
    base, tc = checked_tc(target, manifest)
    staging = manifest["virtual_staging"]
    build = target / "data-v2-effaceable-observer"
    if not finalize:
        require(not manifest.get("effaceable_observer_v2") and not build.exists(), "Observer installation is single-use")
        for name, sha in PINS.items():
            require(stage.digest(stage.PROVISIONING / name) == sha and staging["source_sha256"].get(name) == sha,
                    "Current Data helper source differs")
        require(stage.digest(stage.PROVISIONING / "userdata-entitlements.plist") == ENTITLEMENTS_SHA,
                "Pinned Data-helper entitlements changed")
        record = {"schema": SCHEMA, "vm_uuid": vm_id, "profile": contract.PROFILE, "state": "preparing",
                  "observe_only": True, "source_sha256": dict(PINS), "ready": False}
        stage.write_new(target / "data-v2-observer-intent.json", json.dumps(record, indent=2).encode())
        manifest["effaceable_observer_v2"] = record
        profile.write_manifest(target, manifest)
        build.mkdir(mode=0o700)
        for name in (*PINS, "userdata-entitlements.plist"):
            shutil.copyfile(stage.PROVISIONING / name, build / name)
        require(stage.digest(build / "userdata-entitlements.plist") == ENTITLEMENTS_SHA and
                all(stage.digest(build / name) == sha for name, sha in PINS.items()),
                "Copied observer source/entitlements differ")
        sdk = stage.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"]).stdout.decode().strip()
        binary = build / "huntmob-prepare-userdata"
        stage.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
                   "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + vm_id + '"',
                   "-DHUNTMOB_EFFACEABLE_OBSERVE_ONLY=1", str(build / "prepare_userdata_virtual_v1.c"), "-o", str(binary)], timeout=60)
        stage.run(["codesign", "-s", "-", "--force", "--identifier", "com.huntmob.virtual-sep.prepare-userdata",
                   "--entitlements", str(build / "userdata-entitlements.plist"), str(binary)])
        stage.run(["codesign", "--verify", "--strict", str(binary)])
        displayed = stage.run(["codesign", "-d", "--entitlements", ":-", str(binary)])
        require(plistlib.loads(displayed.stdout) == plistlib.loads((build / "userdata-entitlements.plist").read_bytes()),
                "Observer entitlements differ")
        wrapper = target / "virtual-helper-build-data-checkpoint/init_data_protection"
        require(stage.digest(wrapper) == staging["helper_sha256"]["init_data_protection"], "Current wrapper differs")
        new_tc = stage.merged_trustcache(base.read_bytes(), [cdhash(wrapper), cdhash(binary)], vm_id)
        expected = staging["helper_sha256"]["huntmob-prepare-userdata"]
    else:
        record = manifest.get("effaceable_observer_v2", {})
        require(record.get("schema") == SCHEMA and record.get("state") == "launch-requested" and
                record.get("vm_uuid") == vm_id and record.get("profile") == contract.PROFILE and
                not (target / "data-v2-persistence-finalize-intent.json").exists(), "Exactly one cold observer must run before finalization")
        formatted = validate_formatted_ramdisk(target, manifest)
        observation, log, trace = native_observation(target, manifest, record, "effaceable_observer_requested")
        require(STOP_MARKER in log and "HuntMob: effaceable before-ClassD query status=0 count=1 formatted=1" in log and
                not re.search(r"pci_nvme_apple_ans_submit sqid=\d+ cid=\d+ opcode=0x01 nsid=6(?:\s|$)", trace) and
                not any(value in log for value in ("ClassD initialization", "fresh MKBCreateSystem", "stock format status=", "synthetic canary=")),
                "Cold observation must preserve formatted storage without namespace6 writes or Data initialization")
        stage.write_new(target / "data-v2-persistence-finalize-intent.json", json.dumps({"vm_uuid": vm_id,
            "formatted": formatted, "cold_observation": str(observation), "ready": False}, indent=2).encode())
        record["cold_persistence_evidence"] = {"receipt_sha256": stage.digest(observation / "observation.json"),
            "boot_log_sha256": stage.digest(observation / "boot.log"), "trace_log_sha256": stage.digest(observation / "trace.log")}
        binary = build / "original-huntmob-prepare-userdata"
        require(stage.digest(binary) == record["original_helper_sha256"], "Original Data helper backup differs")
        saved_tc = build / "original-VirtualTrustCache"
        require(stage.digest(saved_tc) == record["original_trustcache_sha256"], "Original owned trustcache backup differs")
        new_tc = saved_tc.read_bytes()
        expected = record["observer_sha256"]
    device, before = stage.attach_backing(target, manifest)
    mount = target / ("DataV2ObserverRestore" if finalize else "DataV2ObserverInstall")
    mounted = False
    try:
        system = layout(owned_container(device), auxiliary=True)
        mount.mkdir(mode=0o700)
        stage.run(["/sbin/mount_apfs", "-o", "nobrowse,noowners", "/dev/" + system["DeviceIdentifier"], str(mount)])
        mounted = True
        require_empty_mnt2(mount)
        guest = stage.safe_path(mount, "usr/libexec/huntmob-prepare-userdata")
        require(stage.digest(guest) == expected and not guest.is_symlink(), "Current owned Data helper differs")
        if not finalize:
            stage.write_new(build / "original-huntmob-prepare-userdata", guest.read_bytes(), 0o755)
            stage.write_new(build / "original-VirtualTrustCache", tc.read_bytes())
            record.update(original_helper_sha256=expected, original_trustcache_sha256=stage.digest(tc), observer_sha256=stage.digest(binary))
            profile.write_manifest(target, manifest)
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.replace_known(guest, binary.read_bytes(), expected)
        stage.run(["codesign", "--verify", "--strict", str(guest)])
        require(stage.digest(guest) == stage.digest(binary), "Data helper readback differs")
        stage.replace_known(tc, new_tc, staging["trustcache_sha256"])
    finally:
        if mounted:
            stage.run(["/sbin/umount", str(mount)])
        profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
        stage.run(["/usr/bin/hdiutil", "detach", device])
    record["state"] = "cold-persistence-validated-original-restored" if finalize else "installed"
    if finalize:
        manifest.update(effaceable_formatted_observed=True, effaceable_cold_persistence_observed=True)
    staging["helper_sha256"]["huntmob-prepare-userdata"] = stage.digest(binary)
    staging["trustcache_sha256"] = stage.digest(tc)
    manifest["firmware"]["files"]["RestoreTrustCache"].update(sha256=stage.digest(tc), bytes=tc.stat().st_size)
    profile.write_manifest(target, manifest)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--action", choices=("install-observer", "finalize-persistence-and-restore"), required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(contract.plan(args.vm_uuid, args.action), indent=2))
        return
    require(args.authorized_lab, "Mutation requires --authorized-lab")
    print(json.dumps(change(args.vm_uuid, args.action == "finalize-persistence-and-restore"), indent=2))


if __name__ == "__main__":
    main()
