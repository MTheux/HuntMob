#!/usr/bin/env python3
"""Read-only own System/public-mount and fresh Hardware metadata inspection.

AUTHORIZED TESTING ONLY — ISOLATED LAB. This explicit auxiliary scope never
mounts host Data or reads Hardware file contents. Default is a no-op plan.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import stat
import time
import uuid
from pathlib import Path

import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as profile
import stage_ios_virtual_profile as stage
import stage_ios_virtual_data_v2_cold_read as cold
import stage_ios_virtual_data_v2_post_keybag as post
from stage_ios_virtual_auxiliary import owned_container
from inspect_ios_virtual_data_v2_boot import checked_readonly_system, resolve_public, write_receipt

require = contract.require
SCHEMA = "huntmob.virtual-sep-data-mount-contract-inspection.v2"
HARDWARE_UUID = "A264DAE3-874A-4B57-9FAD-50DDB8E77A47"
BASELINE = "data-v2-observation-20261015-165040"
BASELINE_SHA = "c4324e475bfd7d5eb88cbdbe2e1a75674feca889540c9647945b68465559edbf"
BOOT_LOG_SHA = "7bed91a22c594a6e5f479af7e23b0013da93602806cc66279c3d19c9a7cecaa3"
TRACE_LOG_SHA = "b660e972e653ee29768a27e4b8ebde08bc668cc5e92bf3cef6f0c2bbaf6b9884"
POST_FACTORY_SCHEMA = "huntmob.virtual-sep-data-mount-contract-inspection.post-factory.v2"
POST_FACTORY_BASELINE = "data-v2-observation-20261015-170842"
POST_FACTORY_BASELINE_SHA = "f034df896a16c4ced774c6dffc9c06835378f67e99c900dd6986ead9e78b16a0"
POST_FACTORY_BOOT_LOG_SHA = "2792b8e1764150d31f686a08773928f5a8e9db2d9e5aaf47a43a509826135ba2"
POST_FACTORY_TRACE_LOG_SHA = "7f8698fa8d55e05a0847fc7e1d0b2eba8cd4cbc3386c89f56efc14fe11aebf16"
SEED_OBSERVATION = "data-v2-observation-20261015-170707"
SEED_OBSERVATION_SHA = "4e8a5b53c3239887498380dfd312cb45ae9904ad086abfa2bac7123d08f66828"
SEED_RESULT_SHA = "536ca977ce100650b9339354ec553fc99715b36298b2e50f984755b41f03dd99"
SYSTEM_PATHS = ("", "System", "System/Library", "System/Library/Caches", "System/Library/Caches/com.apple.factorydata")
HARDWARE_PATHS = ("", "FactoryData", "FactoryData/System", "FactoryData/System/Library", "FactoryData/System/Library/Caches",
                  "FactoryData/System/Library/Caches/com.apple.factorydata")
PUBLIC_FILE = "sbin/mount"


def kind(mode):
    return "directory" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "symlink" if stat.S_ISLNK(mode) else "other"


def metadata_only(mount, relative, allowed):
    require(relative in allowed and not Path(relative).is_absolute() and ".." not in Path(relative).parts,
            "Only the fixed FactoryData ancestry may be inventoried")
    current = mount
    parts = Path(relative).parts
    for index, component in enumerate(parts):
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            return {"exists": False, "first_missing_component": str(Path(*parts[:index + 1])), "file_contents_read": False}
        if index != len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            return {"exists": False, "blocked_by_ancestor": str(Path(*parts[:index + 1])),
                    "ancestor_type": kind(info.st_mode), "file_contents_read": False}
    info = current.lstat()
    result = {"exists": True, "type": kind(info.st_mode), "mode": oct(stat.S_IMODE(info.st_mode)),
              "device": info.st_dev, "inode": info.st_ino, "file_contents_read": False}
    if stat.S_ISDIR(info.st_mode):
        entries = []
        for entry in current.iterdir():
            require(len(entries) < 4096, "FactoryData ancestry inventory exceeded its bounded entry count")
            entries.append({"name": entry.name, "type": kind(entry.lstat().st_mode)})
        result["directory_names"] = sorted(entries, key=lambda entry: entry["name"])
    return result


def copy_public_mount(mount, output):
    source = resolve_public(mount, PUBLIC_FILE, (PUBLIC_FILE,))
    require(source is not None, "Normal System public /sbin/mount is missing")
    before = source.lstat()
    require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 16 * 1024 * 1024, "Public mount utility must be a bounded regular file")
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) ==
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns), "Public mount utility changed while opening")
        data = bytearray()
        while len(data) < opened.st_size:
            block = os.read(fd, min(1024 * 1024, opened.st_size - len(data)))
            require(block, "Short public mount utility read")
            data.extend(block)
        after = os.fstat(fd)
        require((after.st_size, after.st_mtime_ns, after.st_ctime_ns) ==
                (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns), "Public mount utility changed while reading")
    finally:
        os.close(fd)
    artifact = output / "public-system/sbin/mount"
    artifact.parent.mkdir(mode=0o700, parents=True)
    stage.write_new(artifact, data)
    sha = hashlib.sha256(data).hexdigest()
    require(stage.digest(artifact) == sha, "Public mount utility artifact readback mismatch")
    return {"artifact": "public-system/sbin/mount", "sha256": sha, "bytes": len(data),
            "source_device": before.st_dev, "source_inode": before.st_ino}


def hardware_from_layout(container, device, manifest, mount=None):
    """Allow only the exact declared Hardware mount; Data remains strict."""
    adjusted = copy.deepcopy(container)
    matches = [item for item in adjusted.get("Volumes", []) if item.get("APFSVolumeUUID") == HARDWARE_UUID]
    require(len(matches) == 1 and matches[0].get("Roles") == ["Hardware"] and
            matches[0].get("DeviceIdentifier") == adjusted.get("ContainerReference", "") + "s4",
            "Exact owned Hardware slot/role/UUID required")
    if mount is not None:
        value = matches[0].get("MountPoint")
        if value is not None:
            require(isinstance(value, str) and value and Path(value).exists() and os.path.samefile(value, mount),
                    "APFS Hardware mount metadata contradicts the real inspected mount")
            del matches[0]["MountPoint"]
    cold.checked_layout(adjusted, device, manifest, post.DATA_UUID)
    return "/dev/" + matches[0]["DeviceIdentifier"]


def validate_hardware_mount(mount, block_device):
    require(re.fullmatch(r"/dev/disk[0-9]+s4", block_device), "Only the exact Hardware slot4 may be inspected")
    point, block = mount.lstat(), Path(block_device).lstat()
    require(stat.S_ISDIR(point.st_mode) and stat.S_ISBLK(block.st_mode) and point.st_dev == block.st_rdev and
            os.statvfs(mount).f_flag & os.ST_RDONLY, "Hardware inspection must bind the exact read-only VFS block device")
    info = profile.run_plist(["/usr/sbin/diskutil", "info", "-plist", block_device])
    require(info.get("DeviceNode") == block_device and info.get("DeviceIdentifier") == block_device[5:], "Hardware INFO device differs")
    if "Mounted" in info:
        require(info["Mounted"] is True, "Hardware explicitly reports unmounted")
    if "MountPoint" in info:
        value = info["MountPoint"]
        require(isinstance(value, str) and value and Path(value).exists() and os.path.samefile(value, mount), "Hardware INFO mountpoint contradicts VFS")
    for name in ("APFSVolumeUUID", "VolumeUUID"):
        if name in info:
            require(info[name] == HARDWARE_UUID, "Hardware INFO UUID differs")
    if "FilesystemType" in info:
        require(info["FilesystemType"] == "apfs", "Hardware INFO filesystem differs")


def baseline(target, manifest, mode="original"):
    if mode == "post-factory":
        return post_factory_baseline(target, manifest)
    require(mode == "original", "Unknown explicit inspection baseline")
    require(manifest.get("vm_uuid") == post.VM_UUID and manifest.get("post_keybag_v2", {}).get("data_uuid") == post.DATA_UUID and
            manifest["post_keybag_v2"].get("state") == "launch-requested" and
            manifest["post_keybag_v2"].get("observation") == str(target / BASELINE) and
            not (target / ".data-v2-launch.lock").exists(), "Stopped exact post-keybag mount-failure cohort required")
    directory = target / BASELINE
    proof = contract.read_metadata(directory / "observation.json")
    require(stage.digest(directory / "observation.json") == BASELINE_SHA and proof.get("engine_binding") == manifest["engine_binding"] and
            proof.get("vm_uuid") == post.VM_UUID and proof.get("post_keybag_class_c_read_requested") is True and
            proof.get("qmp_quit_accepted") is True and proof.get("exit_code") == 0 and proof.get("panic_observed") is True and
            stage.digest(directory / "boot.log") == BOOT_LOG_SHA == proof.get("boot.log_sha256") and
            stage.digest(directory / "trace.log") == TRACE_LOG_SHA == proof.get("trace.log_sha256"), "Exact native mount-phase-2 failure evidence required")
    for name in ("aess_rejected_command_count", "nvme_error_completion_count", "protected_io_rejection_count", "protected_gate_rejection_count"):
        require(proof.get(name) == 0, "Unexpected crypto/storage rejection changes this inspection's scope")
    return {"observation": BASELINE, "observation_sha256": BASELINE_SHA, "boot_log_sha256": BOOT_LOG_SHA, "trace_log_sha256": TRACE_LOG_SHA}


def post_factory_baseline(target, manifest):
    # Lazy import preserves the original inspector/seed adapter dependency.
    # This explicitly newer scope must never attest the original empty state.
    import stage_ios_virtual_data_v2_factorydata as seed
    record = manifest.get("post_keybag_v2", {})
    initialized = manifest.get("factorydata_seed_v2", {})
    require(manifest.get("vm_uuid") == post.VM_UUID and record.get("schema") == post.SCHEMA and
            record.get("profile") == contract.PROFILE and record.get("data_uuid") == post.DATA_UUID and
            record.get("state") == "launch-requested" and record.get("observation") == str(target / POST_FACTORY_BASELINE) and
            record.get("previous_observation") == str(target / BASELINE) and
            not (target / ".data-v2-launch.lock").exists(), "Stopped exact post-factory retry cohort required")
    require(initialized.get("schema") == seed.SCHEMA and initialized.get("profile") == contract.PROFILE and
            initialized.get("vm_uuid") == post.VM_UUID and initialized.get("data_uuid") == post.DATA_UUID and
            initialized.get("hardware_uuid") == HARDWARE_UUID and initialized.get("source_sha256") == seed.PINS and
            initialized.get("engine_binding") == manifest["engine_binding"] and
            initialized.get("state") == "observed-original-restored" and
            initialized.get("observation") == str(target / SEED_OBSERVATION) and
            all(initialized.get(key) is True for key in ("original_helper_restored", "original_trustcache_restored",
                "own_prepare_marker_removed", "owned_device_detached")) and
            manifest["virtual_staging"]["trustcache_sha256"] == seed.OLD_TC_SHA and
            manifest["virtual_staging"]["helper_sha256"]["huntmob-prepare-userdata"] == seed.OLD_COLD_SHA,
            "The exact completed native seed must have restored the original helper/trustcache")
    result = target / "data-v2-factorydata-result.json"
    require(stage.digest(result) == SEED_RESULT_SHA and contract.read_metadata(result) == initialized,
            "Pinned completed seed result/manifest changed")
    retry = record.get("factorydata_seed_rearmed", {})
    intent = contract.read_metadata(target / "data-v2-post-keybag-factory-rearm-intent.json")
    require(intent == retry and retry.get("previous_observation") == str(target / BASELINE) and
            retry.get("previous_receipt_sha256") == BASELINE_SHA and retry.get("factorydata_result_sha256") == SEED_RESULT_SHA and
            retry.get("maximum_retries") == 1 and retry.get("root_recreated") is False and
            retry.get("Data_or_keys_reinitialized") is False, "Exact one-time post-factory retry evidence required")
    directory, proof, log, trace = cold.observation(target, manifest, SEED_OBSERVATION)
    require(stage.digest(directory / "observation.json") == SEED_OBSERVATION_SHA and
            proof.get("factorydata_seed_requested") is True and proof.get("post_keybag_class_c_read_requested") is False and
            seed.classify_result(log)["factorydata_directories_prepared"] is True,
            "Native root-owned Hardware seed checkpoint changed")
    directory = target / POST_FACTORY_BASELINE
    proof = contract.read_metadata(directory / "observation.json")
    require(stage.digest(directory / "observation.json") == POST_FACTORY_BASELINE_SHA and
            proof.get("engine_binding") == manifest["engine_binding"] and proof.get("vm_uuid") == post.VM_UUID and
            proof.get("post_keybag_class_c_read_requested") is True and proof.get("factorydata_seed_requested") is False and
            proof.get("qmp_quit_accepted") is True and proof.get("exit_code") == 0 and proof.get("panic_observed") is True and
            proof.get("checkpoint_observed") is False and
            stage.digest(directory / "boot.log") == POST_FACTORY_BOOT_LOG_SHA == proof.get("boot.log_sha256") and
            stage.digest(directory / "trace.log") == POST_FACTORY_TRACE_LOG_SHA == proof.get("trace.log_sha256"),
            "Exact post-factory mount failure observation/logs required")
    for name in ("aess_rejected_command_count", "nvme_error_completion_count", "protected_io_rejection_count", "protected_gate_rejection_count"):
        require(proof.get(name) == 0, "Unexpected crypto/storage rejection changes the post-factory inspection scope")
    require("HuntMob: post-keybag" not in (directory / "boot.log").read_text(errors="replace"),
            "Post-keybag handler execution changes the intended mount-failure scope")
    return {"contract_mode": "post-factory", "observation": POST_FACTORY_BASELINE,
            "observation_sha256": POST_FACTORY_BASELINE_SHA, "boot_log_sha256": POST_FACTORY_BOOT_LOG_SHA,
            "trace_log_sha256": POST_FACTORY_TRACE_LOG_SHA, "seed_observation_sha256": SEED_OBSERVATION_SHA,
            "seed_result_sha256": SEED_RESULT_SHA, "original_baseline_preserved": BASELINE}


def inspect(vm_id, baseline_mode="original"):
    target = contract.target_for(vm_id)
    manifest = contract.validate_manifest(target)
    contract.verify_engine(manifest)
    evidence = baseline(target, manifest, baseline_mode)
    output = target / ("data-v2-mount-contract-inspection-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    output.mkdir(mode=0o700)
    manifest_sha = stage.digest(target / "virtual-profile.json")
    record = {"schema": POST_FACTORY_SCHEMA if baseline_mode == "post-factory" else SCHEMA,
              "inspection_baseline": baseline_mode, "vm_uuid": vm_id, "data_uuid": post.DATA_UUID, "hardware_uuid": HARDWARE_UUID,
              "engine_binding": manifest["engine_binding"], "manifest_sha256": manifest_sha, "baseline": evidence,
              "state": "attaching-owned-backing", "root_accessed": False, "data_mounted": False, "data_unlocked": False,
              "hardware_file_contents_read": False, "vm_started": False, "cohort_mutation_requested": False,
              "whole_backing_content_unchanged_validated": False, "metadata": {}, "native_ready": False, "ready": False}
    write_receipt(output, record)
    device = before = active = None
    try:
        device, before = stage.attach_backing(target, manifest)
        initial = owned_container(device)
        system = cold.checked_layout(initial, device, manifest, post.DATA_UUID)
        hardware = hardware_from_layout(initial, device, manifest)
        record.update(whole_device=device, system_device=system, hardware_device=hardware, initial_volume_metadata=initial)
        for role, block_device, allowed in (("System", system, SYSTEM_PATHS), ("Hardware", hardware, HARDWARE_PATHS)):
            point = output / (role + "ReadOnly")
            point.mkdir(mode=0o700)
            stage.run(["/sbin/mount_apfs", "-o", "rdonly,nobrowse,noowners", block_device, str(point)])
            active = (role, point, block_device)
            if role == "System":
                checked_readonly_system(point, block_device, manifest)
                cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID, system_mount=point)
                record["public_mount_binary"] = copy_public_mount(point, output)
            else:
                validate_hardware_mount(point, block_device)
                hardware_from_layout(owned_container(device), device, manifest, mount=point)
            record.update(state="inspecting-" + role.lower() + "-readonly")
            record["metadata"][role] = {}
            write_receipt(output, record)
            for relative in allowed:
                record["metadata"][role][relative] = metadata_only(point, relative, allowed)
                write_receipt(output, record)
            if role == "System":
                checked_readonly_system(point, block_device, manifest)
                cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID, system_mount=point)
            else:
                validate_hardware_mount(point, block_device)
                hardware_from_layout(owned_container(device), device, manifest, mount=point)
            stage.run(["/sbin/umount", str(point)])
            active = None
            cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID)
            record[role.lower() + "_unmounted"] = True
            write_receipt(output, record)
        require(stage.digest(target / "virtual-profile.json") == manifest_sha, "Cohort manifest changed during inspection")
        record["state"] = "readonly-inspection-collected"
    except BaseException as error:
        record.update(state="inspection-failed", failure_type=type(error).__name__)
        raise
    finally:
        try:
            if active is not None:
                role, point, block_device = active
                if role == "System":
                    checked_readonly_system(point, block_device, manifest)
                    cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID, system_mount=point)
                else:
                    validate_hardware_mount(point, block_device)
                    hardware_from_layout(owned_container(device), device, manifest, mount=point)
                stage.run(["/sbin/umount", str(point)])
                record[role.lower() + "_unmounted"] = True
            if device is not None:
                profile.verify_attachment(target / "namespace-1.raw", manifest["backings"]["namespace-1.raw"], device, before)
                cold.checked_layout(owned_container(device), device, manifest, post.DATA_UUID)
                stage.run(["/usr/bin/hdiutil", "detach", device])
                require(not any(entry.get("image-path") == str(target / "namespace-1.raw") for entry in profile.image_inventory()), "Owned backing is still attached")
                record["owned_device_detached"] = True
        except BaseException as cleanup:
            record.update(cleanup_failed=True, cleanup_failure_type=type(cleanup).__name__)
            raise
        finally:
            if record["state"] == "readonly-inspection-collected" and record.get("owned_device_detached") is True:
                record["state"] = "completed-readonly-inspection"
            write_receipt(output, record)
    return output, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--baseline", choices=("original", "post-factory"), default="original")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({**contract.plan(args.vm_uuid, "inspect-mount-phase-2-contract"), "public_file_allowlist": [PUBLIC_FILE],
                          "inspection_baseline": args.baseline,
                          "system_metadata_paths": SYSTEM_PATHS, "hardware_metadata_paths": HARDWARE_PATHS,
                          "hardware_file_contents_read": False, "host_mount_performed": False}, indent=2))
        return
    require(args.authorized_lab, "Host read-only attachment/mount requires --authorized-lab")
    output, receipt = inspect(args.vm_uuid, args.baseline)
    print(json.dumps({"output": str(output), "state": receipt["state"], "owned_device_detached": receipt.get("owned_device_detached", False), "ready": False}, indent=2))


if __name__ == "__main__":
    main()
