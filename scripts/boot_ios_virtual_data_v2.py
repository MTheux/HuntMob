#!/usr/bin/env python3
"""Bounded own DATA-v2 launcher; default is a read-only plan.

AUTHORIZED TESTING ONLY — ISOLATED LAB. --apply creates/looks up only the new
UUID's VirtualSEP.v1 root through the pinned native pipe helper. Python never
reads root bytes. No v1 cohort, historical root, backing or QMP is accepted.
"""
import argparse
import json
import os
import resource
import re
import stat
import subprocess
import tempfile
import time
from pathlib import Path

import boot_ios_virtual_profile as legacy
import ios_virtual_data_v2_contract as contract
import prepare_ios_virtual_profile as preparation
from boot_ios_research import command, digest, SEP_INPUTS, RESEARCH
from boot_ios_installed_research import normal_sep_machine, quit_owned_vm, boot_observations

require = contract.require


def storage_failure_observations(trace):
    """Consume fixed, nonsecret event metadata; do not copy frame contents."""
    result = {"nvme_error_completion_count": 0, "protected_io_rejection_count": 0,
              "protected_gate_rejection_count": 0, "mpe_rejected_revocation_observed": False}
    for line in trace.splitlines():
        match = re.fullmatch(r"pci_nvme_apple_ans_complete sqid=\d+ cid=\d+ opcode=0x[0-9a-f]{2} status=0x([0-9a-f]{4})", line)
        if match and int(match[1], 16) != 0:
            result["nvme_error_completion_count"] += 1
        if line.startswith("pci_nvme_apple_ans_protected_io_rejected "):
            result["protected_io_rejection_count"] += 1
        match = re.fullmatch(r"pci_nvme_apple_ans_protected_gate sqid=\d+ cid=\d+ stage=[a-z-]+ result=([a-z-]+)", line)
        if match and match[1] != "accepted":
            result["protected_gate_rejection_count"] += 1
        if re.fullmatch(r"apple_sep_virtual_mpe_control action=revoked reg=0x[0-9a-f]+ value=0x[0-9a-f]+ accepted=0", line):
            result["mpe_rejected_revocation_observed"] = True
    return result


def cleanup_short_sockets(directory, identity):
    """Delete only sockets in this invocation's unchanged private directory."""
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino, info.st_uid) == identity and
            info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "Private socket directory ownership changed; cleanup refused")
    for name in ("qmp.sock", "usb.sock"):
        path = directory / name
        if path.exists() or path.is_symlink():
            require(stat.S_ISSOCK(path.lstat().st_mode), "Unrecognized private socket entry; cleanup refused")
            path.unlink()
    # Deliberately nonrecursive. Unexpected entries are preserved for review.
    directory.rmdir()


def validate_boot(target, *, create_root, sep_profile, effaceable_ramdisk=False, auxiliary_bootstrap=False,
                  effaceable_observer=False, cold_class_c_read=False, post_keybag_class_c_read=False,
                  factorydata_seed=False, update_volume_bootstrap=False, normal_boot=False, ui_process_observer=False):
    require(sum((effaceable_ramdisk, auxiliary_bootstrap, effaceable_observer, cold_class_c_read,
                 post_keybag_class_c_read, factorydata_seed, update_volume_bootstrap, normal_boot, ui_process_observer)) <= 1,
            "Provisioning modes are mutually exclusive")
    manifest = contract.validate_manifest(target)
    binary = contract.verify_engine(manifest)
    require(manifest.get("restore_completed") is True and manifest.get("owned_device_detached") is True and
            manifest.get("v2_staging_complete") is True and manifest.get("host_staging_complete") is True and
            manifest.get("stock_files_staged") is True and manifest.get("private_artifact_absence_checked") is True,
            "Verified fresh DATA-v2 host staging is required")
    staging = manifest.get("virtual_staging", {})
    phase = staging.get("phase")
    require(staging.get("stock_verifier_preserved") is True and staging.get("stock_seputil_unchanged") is True and
            phase in {"restore-checkpoint", "data-checkpoint"}, "Stock verifier/helper phase binding missing")
    require(manifest.get("mnt2_empty_directory_verified") is True, "Empty /mnt2 staging is mandatory")
    if auxiliary_bootstrap:
        auxiliary = manifest.get("auxiliary_bootstrap_v2", {})
        require(not effaceable_ramdisk and phase == "restore-checkpoint" and
                auxiliary.get("schema") == "huntmob.virtual-sep-data-auxiliary-bootstrap.v2" and
                auxiliary.get("profile") == contract.PROFILE and auxiliary.get("vm_uuid") == manifest["vm_uuid"] and
                auxiliary.get("state") == "installed", "Exact fresh auxiliary bootstrap adapter is required")
    else:
        require(manifest.get("auxiliary_volumes_staged") is True, "DATA-v2 auxiliary APFS adapter must complete first")
        auxiliary = manifest.get("auxiliary_layout", {})
        require(auxiliary.get("vm_uuid") == manifest["vm_uuid"] and auxiliary.get("completed") is True and
                auxiliary.get("historical_data_or_keys_copied") is False and auxiliary.get("data_slot_2_absent") is True,
                "Fresh matching auxiliary layout is mandatory")
    expected = "restore" if phase == "restore-checkpoint" else "serving"
    require(sep_profile == expected, "Provisioning phase requires its exact SEP profile")
    require(create_root == (manifest.get("root_provisioned") is False),
            "Create the new root exactly once; later boots only look up the same UUID")
    require(not legacy.HELPER.is_symlink() and digest(legacy.HELPER) == legacy.HELPER_SHA,
            "Unreviewed native Keychain helper")
    require(all(preparation.image_path(entry["image-path"]).resolve() != (target / "namespace-1.raw").resolve()
                for entry in preparation.image_inventory() if entry.get("image-path")), "Backing is still attached")
    files = manifest.get("firmware", {}).get("files", {})
    require(files and files.get("RestoreTrustCache", {}).get("sha256") == staging.get("trustcache_sha256"),
            "Staged helper trustcache binding differs")
    for record in files.values():
        path = Path(record["path"])
        require(path.is_absolute() and path.resolve() == path and path.is_relative_to(target / "firmware") and
                digest(path) == record["sha256"],
                "Staged firmware path/hash changed")
    for name, sha in SEP_INPUTS.items():
        require(digest(RESEARCH / "firmware" / name) == sha, "Pinned SEP inputs changed")
    if effaceable_ramdisk:
        from stage_ios_virtual_data_v2_effaceable import inputs
        require(phase == "data-checkpoint" and not create_root and manifest.get("restore_checkpoint_observed") is True,
                "Effaceable initializer needs the same restored identity")
        files = {**files, **inputs(target, manifest)}
    elif effaceable_observer:
        from stage_ios_virtual_data_v2_observer import validate_for_boot
        require(phase == "data-checkpoint" and not create_root, "Cold observer requires existing Data-phase identity")
        validate_for_boot(target, manifest)
    elif ui_process_observer:
        from stage_ios_virtual_data_v2_ui_observer import validate_for_boot
        require(phase == "data-checkpoint" and not create_root,
                "UI process metadata observation requires the existing protected identity")
        validate_for_boot(target, manifest)
    elif normal_boot:
        from stage_ios_virtual_data_v2_normal_boot import validate_for_boot
        require(phase == "data-checkpoint" and not create_root,
                "Normal boot requires the existing protected identity")
        validate_for_boot(target, manifest)
    elif update_volume_bootstrap:
        from stage_ios_virtual_data_v2_update_volume import validate_for_boot
        require(phase == "data-checkpoint" and not create_root and
                manifest.get("effaceable_cold_persistence_observed") is True,
                "Update volume preparation requires the existing restored identity")
        validate_for_boot(target, manifest)
    elif factorydata_seed:
        from stage_ios_virtual_data_v2_factorydata import validate_for_boot
        require(phase == "data-checkpoint" and not create_root and
                manifest.get("effaceable_cold_persistence_observed") is True,
                "FactoryData preparation requires the existing restored identity")
        validate_for_boot(target, manifest)
    elif post_keybag_class_c_read:
        from stage_ios_virtual_data_v2_post_keybag import validate_for_boot
        require(phase == "data-checkpoint" and not create_root and
                manifest.get("effaceable_cold_persistence_observed") is True,
                "Post-keybag read requires the existing provisioned identity")
        require(manifest.get("factorydata_seed_v2", {}).get("state") in (None, "observed-original-restored"),
                "FactoryData preparation must restore the post-keybag helper binding first")
        require(manifest.get("update_volume_v2", {}).get("state") in (None, "observed-original-restored"),
                "Update volume preparation must restore the post-keybag helper binding first")
        validate_for_boot(target, manifest)
    elif cold_class_c_read:
        from stage_ios_virtual_data_v2_cold_read import validate_for_boot
        require(phase == "data-checkpoint" and not create_root and manifest.get("effaceable_cold_persistence_observed") is True,
                "Cold Class C read requires the existing provisioned identity")
        require(manifest.get("post_keybag_v2") is None,
                "The post-keybag stage cannot execute the superseded early probe")
        validate_for_boot(target, manifest)
    elif phase == "data-checkpoint":
        require(manifest.get("cold_read_v2") is None, "Installed cold verifier requires its explicit launch mode")
        require(manifest.get("restore_checkpoint_observed") is True and
                manifest.get("effaceable_formatted_observed") is True,
                "Actual stock restore and persistent effaceable formatting must precede Data boot")
    return manifest, binary, files


def launch_command(binary, target, files, vm_id, sep_profile, effaceable_ramdisk, socket_dir):
    launch = command(binary, target, files, sep=True, companion_profile="x86_64",
                     tcg_thread="single", create_disks=False)
    if not effaceable_ramdisk:
        index = launch.index("-initrd")
        del launch[index:index + 2]
    launch.remove("-snapshot")
    index = launch.index("-M") + 1
    old_usb = "usb-conn-addr=" + str(target / "usb.sock")
    require(launch[index].count(old_usb) == 1, "Unexpected owned USB socket configuration")
    launch[index] = launch[index].replace(old_usb, "usb-conn-addr=" + str(socket_dir / "usb.sock"))
    canonical = "restore-preload" if sep_profile == "restore" else "serving"
    launch[index] = normal_sep_machine(launch[index], canonical)
    launch[index] += (",boot-mode=" + ("enter_recovery" if effaceable_ramdisk else "exit_recovery") +
                      ",huntmob-virtual-sep-root-secret=virtual-root,huntmob-virtual-sep-vm-id=" + vm_id +
                      ",huntmob-virtual-data-profile=v2")
    qmp = socket_dir / "qmp.sock"
    require(len(os.fsencode(qmp)) < 104 and len(os.fsencode(socket_dir / "usb.sock")) < 104,
            "Private socket path exceeds macOS bound")
    launch[launch.index("-qmp") + 1] = "unix:" + str(qmp) + ",server=on,wait=off"
    return launch


def boot(target, seconds, create_root, sep_profile, effaceable_ramdisk=False, auxiliary_bootstrap=False,
         effaceable_observer=False, cold_class_c_read=False, post_keybag_class_c_read=False,
         factorydata_seed=False, update_volume_bootstrap=False, normal_boot=False, headless_refresh_hz=0,
         ui_process_observer=False):
    require(10 <= seconds <= (240 if ui_process_observer else 180), "Bounded observation exceeds this mode's time limit")
    require(headless_refresh_hz in (0, 10) and (not headless_refresh_hz or normal_boot or ui_process_observer),
            "Headless refresh is limited to the normal-boot 10 Hz experiment")
    require(not ui_process_observer or (seconds == 240 and headless_refresh_hz == 10),
            "UI process observation requires its exact bounded 240 s/10 Hz plan")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    manifest, binary, files = validate_boot(target, create_root=create_root, sep_profile=sep_profile,
                                          effaceable_ramdisk=effaceable_ramdisk, auxiliary_bootstrap=auxiliary_bootstrap,
                                          effaceable_observer=effaceable_observer, cold_class_c_read=cold_class_c_read,
                                          post_keybag_class_c_read=post_keybag_class_c_read,
                                          factorydata_seed=factorydata_seed,
                                          update_volume_bootstrap=update_volume_bootstrap, normal_boot=normal_boot,
                                          ui_process_observer=ui_process_observer)
    if normal_boot:
        require(manifest["normal_boot_v2"].get("headless_refresh_hz_required", 0) == headless_refresh_hz,
                "Normal-boot continuation requires its exact reviewed display refresh mode")
    lock = target / ".data-v2-launch.lock"
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    read_fd = -1
    process = None
    run_dir = None
    receipt = None
    socket_dir = None
    socket_identity = None
    refresher = None
    try:
        os.write(lock_fd, (str(os.getpid()) + "\n").encode())
        os.fsync(lock_fd)
        # Repeat identity checks after taking the exclusive launch lock.
        contract.validate_manifest(target, manifest, owned_launch_lock=lock_fd)
        run_dir = target / ("data-v2-observation-" + time.strftime("%Y%m%d-%H%M%S"))
        run_dir.mkdir(mode=0o700, exist_ok=False)
        socket_dir = Path(tempfile.mkdtemp(prefix="hm-v2-", dir="/tmp"))
        os.chmod(socket_dir, 0o700)
        info = socket_dir.lstat()
        socket_identity = (info.st_dev, info.st_ino, info.st_uid)
        if headless_refresh_hz:
            from ios_virtual_headless_refresh import HeadlessRefresh
            refresher = HeadlessRefresh(socket_dir / "qmp.sock", headless_refresh_hz)
        launch = launch_command(binary, target, files, manifest["vm_uuid"], sep_profile, effaceable_ramdisk, socket_dir)
        events = run_dir / "trace-events.txt"
        events.write_text("\n".join(legacy.EVENTS) + "\n")
        launch += ["-trace", "events=" + str(events) + ",file=" + str(run_dir / "trace.log")]
        read_fd, status = legacy.root_pipe(manifest["vm_uuid"], create_root)
        require(not create_root or status.get("created") is True, "Native helper did not create an independent new root")
        manifest.update(root_provisioned=True, root_lookup_performed=not create_root,
                        root_helper_sha256=legacy.HELPER_SHA,
                        crypto_provider_source_sha256=manifest["engine_binding"]["reviewed_source_sha256"]["crypto/huntmob-virtual-sep.c"])
        if effaceable_ramdisk:
            manifest["effaceable_ramdisk_v2"].update(state="launch-requested", observation=str(run_dir))
        if auxiliary_bootstrap:
            manifest["auxiliary_bootstrap_v2"].update(state="launch-requested", observation=str(run_dir))
        if effaceable_observer:
            manifest["effaceable_observer_v2"].update(state="launch-requested", observation=str(run_dir))
        if cold_class_c_read:
            manifest["cold_read_v2"].update(state="launch-requested", observation=str(run_dir))
        if post_keybag_class_c_read:
            manifest["post_keybag_v2"].update(state="launch-requested", observation=str(run_dir))
        if factorydata_seed:
            manifest["factorydata_seed_v2"].update(state="launch-requested", observation=str(run_dir))
        if update_volume_bootstrap:
            manifest["update_volume_v2"].update(state="launch-requested", observation=str(run_dir))
        if normal_boot:
            manifest["normal_boot_v2"].update(state="launch-requested", observation=str(run_dir))
        if ui_process_observer:
            manifest["ui_process_observer_v2"].update(state="launch-requested", observation=str(run_dir))
        preparation.write_manifest(target, manifest)
        launch += ["-object", "secret,id=virtual-root,file=/dev/fd/" + str(read_fd) + ",format=raw"]
        receipt = {"schema": "huntmob.virtual-sep-data-observation.v2", "vm_uuid": manifest["vm_uuid"],
                   "data_profile": contract.PROFILE, "engine_binding": manifest["engine_binding"],
                   "data_profile_sha256": manifest["data_profile_sha256"],
                   "auxiliary_bootstrap_requested": auxiliary_bootstrap,
                   "effaceable_observer_requested": effaceable_observer,
                   "cold_class_c_read_requested": cold_class_c_read,
                   "post_keybag_class_c_read_requested": post_keybag_class_c_read,
                   "factorydata_seed_requested": factorydata_seed,
                   "update_volume_bootstrap_requested": update_volume_bootstrap,
                   "normal_boot_requested": normal_boot,
                   "ui_process_observer_requested": ui_process_observer,
                   "cold_read_validated": False,
                   "kdf_id": contract.KDF_ID, "root_pipe_delivered": True, "root_in_python": False,
                   "core_dumps_disabled": True, "sep_profile": sep_profile, "command": launch,
                   "seconds": seconds, "ready": False, "native_ready": False,
                   "full_boot_validated": False, "springboard_validated": False, "ipa_execution_validated": False,
                   "apple_sep_equivalent": False, "effaceable_ramdisk_requested": effaceable_ramdisk,
                   "qmp_quit_requested": False, "qmp_quit_accepted": False,
                   "qmp_socket": str(socket_dir / "qmp.sock"), "usb_socket": str(socket_dir / "usb.sock")}
        started = time.monotonic()
        reason = "engine-exited"
        with (run_dir / "boot.log").open("xb") as output:
            process = subprocess.Popen(launch, pass_fds=(read_fd,), cwd=run_dir, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            os.close(read_fd)
            read_fd = -1
            while process.poll() is None:
                if time.monotonic() - started >= seconds:
                    reason = "bounded-observation-ended"
                    break
                if refresher is not None:
                    try:
                        refresher.tick()
                    except (OSError, ValueError):
                        reason = "headless-refresh-error"
                        receipt["headless_refresh_error"] = True
                        break
                if any(path.stat().st_size > 16 * 1024 * 1024 for path in
                       (run_dir / "boot.log", run_dir / "trace.log") if path.exists()):
                    reason = "metadata-log-bound-reached"
                    break
                with (run_dir / "boot.log").open("rb") as reader:
                    reader.seek(max(0, (run_dir / "boot.log").stat().st_size - 32768))
                    recent = reader.read(32768)
                if b"panic(cpu" in recent:
                    reason = "guest-panic-observed"
                    break
                trace = run_dir / "trace.log"
                if trace.exists():
                    with trace.open("rb") as reader:
                        reader.seek(max(0, trace.stat().st_size - 32768))
                        recent_trace = reader.read(32768)
                    state = legacy.virtual_memory_observations(recent_trace.decode("ascii", errors="replace"))
                    if state["virtual_mpe_memory_fault_observed"] or any(
                            item["action"] == "revoked" and not item["accepted"]
                            for item in state["virtual_mpe_controls"]):
                        reason = "virtual-mpe-contract-rejected"
                        break
                if b"HuntMob: provisioning checkpoint ready;" in recent:
                    reason = "provisioning-checkpoint-observed"
                    break
                time.sleep(.1)
        receipt.update(elapsed_seconds=round(time.monotonic() - started, 2), stop_reason=reason)
    finally:
        if refresher is not None:
            try:
                if receipt is not None and process is not None and process.poll() is None:
                    refresher.save_final_frame(run_dir / "headless-refresh-final.ppm")
                    receipt["headless_refresh_final_frame_saved"] = True
            except (OSError, ValueError):
                if receipt is not None:
                    receipt["headless_refresh_final_frame_saved"] = False
            finally:
                refresher.close()
                if receipt is not None:
                    receipt.update(refresher.metadata())
        if read_fd >= 0:
            os.close(read_fd)
        if process is not None and process.poll() is None:
            if receipt is not None:
                receipt["qmp_quit_requested"] = True
            accepted = quit_owned_vm(socket_dir / "qmp.sock")
            if receipt is not None:
                receipt["qmp_quit_accepted"] = accepted
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        if receipt is not None:
            receipt["exit_code"] = process.returncode if process else None
            content = (run_dir / "boot.log").read_text(errors="replace")
            receipt.update(boot_observations(content, timed_out=receipt.get("stop_reason") == "bounded-observation-ended"))
            trace = run_dir / "trace.log"
            if trace.exists():
                trace_content = trace.read_text(errors="replace")
                receipt.update(legacy.virtual_memory_observations(trace_content))
                receipt.update(storage_failure_observations(trace_content))
            for name in ("boot.log", "trace.log"):
                path = run_dir / name
                if path.exists():
                    receipt[name + "_sha256"] = digest(path)
            # A checkpoint marker is evidence of a matching helper phase, not
            # evidence of full boot, APFS persistence, SpringBoard or an IPA.
            checkpoint = (not normal_boot and not ui_process_observer and receipt.get("stop_reason") == "provisioning-checkpoint-observed" and
                          not receipt["panic_observed"] and receipt.get("qmp_quit_requested") is True and
                          receipt.get("qmp_quit_accepted") is True and receipt.get("exit_code") == 0 and
                          not receipt.get("virtual_mpe_memory_fault_observed", False) and
                          not receipt.get("mpe_rejected_revocation_observed", False) and
                          receipt.get("aess_rejected_command_count", 0) == 0 and
                          receipt.get("nvme_error_completion_count", 0) == 0 and
                          receipt.get("protected_io_rejection_count", 0) == 0 and
                          receipt.get("protected_gate_rejection_count", 0) == 0)
            receipt["provisioning_checkpoint_observed"] = checkpoint
            receipt["checkpoint_observed"] = checkpoint
            if normal_boot:
                # Task names are observations. Neither a task log, a quiet
                # timeout nor a SpringBoard string proves a usable interface.
                from stage_ios_virtual_data_v2_normal_boot import classify_result
                try:
                    receipt.update(classify_result(content))
                except ValueError:
                    receipt.update(normal_boot_log_observed=False, normal_boot_result_invalid=True,
                                   full_boot_validated=False, springboard_validated=False,
                                   ipa_execution_validated=False, native_ready=False, ready=False)
                receipt["normal_boot_tasks_observed"] = re.findall(
                    r"Doing boot task: ([A-Za-z0-9_.-]{1,64})", content)
                receipt["normal_boot_observation_only"] = True
                receipt["normal_boot_window_ended"] = receipt.get("stop_reason") == "bounded-observation-ended"
                receipt["own_checkpoint_unexpected"] = "HuntMob: provisioning checkpoint ready;" in content
            if ui_process_observer:
                from stage_ios_virtual_data_v2_ui_observer import classify_result
                receipt["own_checkpoint_unexpected"] = "HuntMob: provisioning checkpoint ready;" in content
                receipt["stock_early_boot_marker_observed"] = "Early boot complete. Continuing system boot." in content
                receipt["normal_boot_tasks_observed"] = re.findall(r"Doing boot task: ([A-Za-z0-9_.-]{1,64})", content)
                try:
                    receipt.update(classify_result(content))
                except ValueError:
                    receipt.update(ui_process_metadata_validated=False, ui_process_observer_result_invalid=True)
            if checkpoint and cold_class_c_read:
                from stage_ios_virtual_data_v2_cold_read import classify_result
                try:
                    receipt.update(classify_result(content))
                except ValueError:
                    receipt.update(cold_read_validated=False, cold_result_invalid=True)
            if checkpoint and post_keybag_class_c_read:
                from stage_ios_virtual_data_v2_post_keybag import classify_result
                try:
                    receipt.update(classify_result(content))
                except ValueError:
                    receipt.update(cold_read_validated=False, post_keybag_result_invalid=True)
            if checkpoint and factorydata_seed:
                from stage_ios_virtual_data_v2_factorydata import classify_result
                try:
                    receipt.update(classify_result(content))
                except ValueError:
                    receipt.update(factorydata_seed_validated=False, factorydata_seed_result_invalid=True)
            if checkpoint and update_volume_bootstrap:
                from stage_ios_virtual_data_v2_update_volume import classify_result
                try:
                    receipt.update(classify_result(content))
                except ValueError:
                    receipt.update(update_volume_created=False, update_volume_result_invalid=True)
            if (checkpoint and sep_profile == "restore" and not effaceable_ramdisk and not auxiliary_bootstrap and
                    not effaceable_observer and not cold_class_c_read and not post_keybag_class_c_read and
                    not factorydata_seed and not update_volume_bootstrap and not normal_boot and not ui_process_observer):
                manifest["restore_checkpoint_observed"] = True
                manifest["restore_checkpoint_observation"] = str(run_dir)
                preparation.write_manifest(target, manifest)
        if socket_dir is not None:
            try:
                cleanup_short_sockets(socket_dir, socket_identity)
                if receipt is not None:
                    receipt["private_socket_directory_removed"] = True
            except (OSError, ValueError):
                if receipt is not None:
                    receipt["private_socket_directory_removed"] = False
        if receipt is not None:
            (run_dir / "observation.json").write_text(json.dumps(receipt, indent=2) + "\n")
        os.close(lock_fd)
        lock.unlink()
    return run_dir, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-uuid", required=True)
    parser.add_argument("--sep-profile", choices=("restore", "serving"), default="restore")
    parser.add_argument("--seconds", type=int, choices=range(10, 241), default=60)
    parser.add_argument("--create-root", action="store_true")
    parser.add_argument("--effaceable-ramdisk", action="store_true")
    parser.add_argument("--auxiliary-bootstrap", action="store_true")
    parser.add_argument("--effaceable-observer", action="store_true")
    parser.add_argument("--cold-class-c-read", action="store_true")
    parser.add_argument("--post-keybag-class-c-read", action="store_true")
    parser.add_argument("--factorydata-seed", action="store_true")
    parser.add_argument("--update-volume-bootstrap", action="store_true")
    parser.add_argument("--normal-boot", action="store_true")
    parser.add_argument("--headless-refresh-hz", type=int, choices=(0, 10), default=0)
    parser.add_argument("--ui-process-observer", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--authorized-lab", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        result = contract.plan(args.vm_uuid, "boot")
        result.update(sep_profile=args.sep_profile, seconds=args.seconds, create_root_requested=args.create_root,
                      effaceable_ramdisk_requested=args.effaceable_ramdisk, engine_validation_performed=False)
        result["auxiliary_bootstrap_requested"] = args.auxiliary_bootstrap
        result["effaceable_observer_requested"] = args.effaceable_observer
        result["cold_class_c_read_requested"] = args.cold_class_c_read
        result["post_keybag_class_c_read_requested"] = args.post_keybag_class_c_read
        result["factorydata_seed_requested"] = args.factorydata_seed
        result["update_volume_bootstrap_requested"] = args.update_volume_bootstrap
        result["normal_boot_requested"] = args.normal_boot
        result["headless_refresh_hz_requested"] = args.headless_refresh_hz
        result["ui_process_observer_requested"] = args.ui_process_observer
        print(json.dumps(result, indent=2))
        return
    require(args.authorized_lab, "VM launch requires --authorized-lab")
    run_dir, result = boot(contract.target_for(args.vm_uuid), args.seconds, args.create_root,
                           args.sep_profile, args.effaceable_ramdisk, args.auxiliary_bootstrap, args.effaceable_observer,
                           args.cold_class_c_read, args.post_keybag_class_c_read, args.factorydata_seed,
                           args.update_volume_bootstrap, args.normal_boot, args.headless_refresh_hz, args.ui_process_observer)
    print(json.dumps({"observation": str(run_dir), "stop_reason": result["stop_reason"],
                      "ready": False, "native_ready": False}))


if __name__ == "__main__":
    main()
