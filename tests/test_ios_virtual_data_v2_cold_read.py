"""Public fixtures only. No host volume, native VM, Data or Keychain access."""
import contextlib
import copy
import hashlib
import io
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_cold_read as cold
import ios_virtual_data_v2_contract as contract

VM_ID = "d550c662-a0d4-49d5-a102-811c89e02030"
DATA_ID = "A91BC479-BB65-4B42-A10A-972D8C5BE36B"
CANARY = "ab" * 32
IDENTITY = "HuntMob: cold Class C exact Data UUID and readonly CPROTECT matched\n"


class ColdReadGuards(unittest.TestCase):
    def manifest(self):
        return {"vm_uuid": VM_ID, "data_profile_sha256": contract.canonical_hash(contract.PROFILE),
                "engine_binding": {"public-fixture": "engine"},
                "auxiliary_layout": {"system_uuid": "SYSTEM-PUBLIC", "created_volumes": [
                    {"Roles": [role], "APFSVolumeUUID": role + "-PUBLIC"} for role in ("xART", "Hardware", "Preboot")]}}

    def proof(self, manifest, log, trace):
        proof = {"schema": "huntmob.virtual-sep-data-observation.v2", "vm_uuid": VM_ID,
                 "data_profile": contract.PROFILE, "data_profile_sha256": manifest["data_profile_sha256"],
                 "engine_binding": manifest["engine_binding"], "sep_profile": "serving",
                 "qmp_quit_requested": True, "qmp_quit_accepted": True, "exit_code": 0,
                 "checkpoint_observed": True, "panic_observed": False, "virtual_mpe_memory_fault_observed": False,
                 "mpe_rejected_revocation_observed": False, "stock_data_protection_verifier_invoked": True,
                 "aess_command_count": 10, "auxiliary_bootstrap_requested": False,
                 "effaceable_ramdisk_requested": False, "effaceable_observer_requested": False,
                 "boot.log_sha256": hashlib.sha256(log.encode()).hexdigest(),
                 "trace.log_sha256": hashlib.sha256(trace.encode()).hexdigest()}
        proof.update({key: 0 for key in ("aess_rejected_command_count", "nvme_error_completion_count",
                     "protected_io_rejection_count", "protected_gate_rejection_count")})
        return proof

    def logs(self):
        return ("HuntMob: ClassD initialization status=0\n"
                "HuntMob virtual v1: fresh MKBCreateSystem returned zero\n"
                "HuntMob virtual v1: Class C roundtrip; synthetic canary=" + CANARY + "\n"
                "HuntMob: provisioning checkpoint ready; virtual v1 fresh protected Data prepared\n",
                "pci_nvme_apple_ans_protected_gate sqid=1 cid=7 stage=sq-context result=accepted\n"
                "pci_nvme_apple_ans_complete sqid=1 cid=7 opcode=0x01 status=0x0000\n")

    def fixture(self, root, alter_proof=None, alter_log=None, alter_trace=None):
        target = Path(root)
        name = "data-v2-observation-20261015-120000"
        directory = target / name
        directory.mkdir()
        manifest = self.manifest()
        log, trace = self.logs()
        if alter_log:
            log = alter_log(log)
        if alter_trace:
            trace = alter_trace(trace)
        proof = self.proof(manifest, log, trace)
        if alter_proof:
            alter_proof(proof)
        (directory / "boot.log").write_text(log)
        (directory / "trace.log").write_text(trace)
        (directory / "observation.json").write_text(json.dumps(proof))
        return target, manifest, name

    def test_default_plan_does_not_read_or_mutate_a_cohort(self):
        with patch("sys.argv", [cold.__file__, "--vm-uuid", VM_ID]), \
             patch.object(cold.contract, "validate_manifest", side_effect=AssertionError("no cohort")), \
             patch.object(cold.stage, "run", side_effect=AssertionError("no process")), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            cold.main()
        value = json.loads(output.getvalue())
        self.assertTrue(value["read_only"])
        self.assertTrue(value["reads_existing_probe_only"])
        self.assertFalse(value["attempts_keybag_unlock"])

    def test_apply_requires_authorization_before_any_stage(self):
        with patch("sys.argv", [cold.__file__, "--vm-uuid", VM_ID, "--apply"]), self.assertRaises(ValueError):
            cold.main()

    def test_actual_fresh_creation_fixture_passes_without_mounts(self):
        with tempfile.TemporaryDirectory() as root:
            target, manifest, name = self.fixture(root)
            evidence = cold.creation_evidence(target, manifest, name)
            self.assertEqual(evidence["expected_public_canary"], CANARY)
            self.assertTrue(evidence["canary_is_public_fixture"])

    def test_missing_mkb_zero_roundtrip_or_protected_completion_refuses_staging(self):
        variants = [dict(alter_log=lambda x: x.replace("returned zero", "rejected (-4)")),
                    dict(alter_log=lambda x: x.replace("synthetic canary=", "missing probe=")),
                    dict(alter_trace=lambda x: x.replace("status=0x0000", "status=0x4002")),
                    dict(alter_proof=lambda p: p.update(nvme_error_completion_count=1)),
                    dict(alter_proof=lambda p: p.update(engine_binding={"other": "engine"}))]
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as root:
                target, manifest, name = self.fixture(root, **variant)
                with self.assertRaises(ValueError):
                    cold.creation_evidence(target, manifest, name)

    def test_modified_log_is_not_accepted_under_old_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            target, manifest, name = self.fixture(root)
            (target / name / "boot.log").write_text("modified PUBLIC fixture")
            with self.assertRaisesRegex(ValueError, "log/hash"):
                cold.creation_evidence(target, manifest, name)

    def container(self):
        roles = ["System", "Data", "xART", "Hardware", "Preboot"]
        identities = ["SYSTEM-PUBLIC", DATA_ID, "xART-PUBLIC", "Hardware-PUBLIC", "Preboot-PUBLIC"]
        volumes = [{"Roles": [role], "Name": role, "DeviceIdentifier": "disk91s" + str(index),
                    "APFSVolumeUUID": identity, "Encryption": role == "Data"}
                   for index, (role, identity) in enumerate(zip(roles, identities), 1)]
        volumes[1]["Locked"] = True
        return {"ContainerReference": "disk91", "PhysicalStores": [{"DeviceIdentifier": "disk90s1"}], "Volumes": volumes}

    def test_exact_encrypted_locked_unmounted_data_and_bound_roles_required(self):
        baseline = self.container()
        self.assertEqual(cold.checked_layout(baseline, "/dev/disk90", self.manifest(), DATA_ID), "/dev/disk91s1")
        for key, value in (("Locked", False), ("Encryption", False), ("MountPoint", "/Volumes/Data"),
                           ("APFSVolumeUUID", "DIFFERENT"), ("Roles", ["System"])):
            modified = copy.deepcopy(baseline)
            modified["Volumes"][1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                cold.checked_layout(modified, "/dev/disk90", self.manifest(), DATA_ID)

    def test_list_mountpoint_is_not_authoritative_but_data_and_aux_stay_unmounted(self):
        container = self.container()
        container["Volumes"][0]["MountPoint"] = "/public-own-stage"
        cold.checked_layout(container, "/dev/disk90", self.manifest(), DATA_ID, system_mount=Path("/another"))
        with self.assertRaises(ValueError):
            cold.checked_layout(container, "/dev/disk90", self.manifest(), DATA_ID)
        for index in (1, 2, 3, 4):
            modified = copy.deepcopy(container)
            modified["Volumes"][index]["MountPoint"] = "/not-system"
            with self.subTest(index=index), self.assertRaises(ValueError):
                cold.checked_layout(modified, "/dev/disk90", self.manifest(), DATA_ID, system_mount=Path("/another"))

    def test_real_vfs_device_identity_handles_omitted_info_mount_fields(self):
        mount = Path("/public-mount")
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_dev=123)
        block = SimpleNamespace(st_mode=stat.S_IFBLK | 0o600, st_rdev=123)
        info = {"DeviceNode": "/dev/disk91s1", "DeviceIdentifier": "disk91s1"}
        def metadata(path, *args, **kwargs):
            return directory if path == mount else block
        with patch.object(Path, "lstat", metadata), patch.object(Path, "stat", metadata), \
             patch.object(cold.profile, "run_plist", return_value=info):
            cold.validate_system_mount(mount, "/dev/disk91s1", self.manifest())
            for key, value in (("Mounted", False), ("VolumeUUID", "OTHER"), ("FilesystemType", "hfs"),
                               ("DeviceNode", "/dev/disk92s1"), ("MountPoint", "")):
                with self.subTest(key=key), patch.object(cold.profile, "run_plist", return_value={**info, key: value}), \
                     self.assertRaises(ValueError):
                    cold.validate_system_mount(mount, "/dev/disk91s1", self.manifest())
            directory.st_dev = 999
            with self.assertRaisesRegex(ValueError, "exact System"):
                cold.validate_system_mount(mount, "/dev/disk91s1", self.manifest())

    def test_system_info_mountpoint_must_match_real_mount_when_reported(self):
        mount = Path("/public-mount")
        def metadata(path, *args, **kwargs):
            return SimpleNamespace(st_mode=stat.S_IFDIR if path == mount else stat.S_IFBLK,
                                   st_dev=123, st_rdev=123)
        info = {"DeviceNode": "/dev/disk91s1", "DeviceIdentifier": "disk91s1", "MountPoint": "/alias"}
        with patch.object(Path, "lstat", metadata), patch.object(Path, "stat", metadata), \
             patch.object(Path, "exists", return_value=True), patch.object(cold.os.path, "samefile", return_value=True), \
             patch.object(cold.profile, "run_plist", return_value=info):
            cold.validate_system_mount(mount, "/dev/disk91s1", self.manifest())
            with patch.object(cold.os.path, "samefile", return_value=False), self.assertRaises(ValueError):
                cold.validate_system_mount(mount, "/dev/disk91s1", self.manifest())

    def partial_fixture(self, root):
        target, manifest, name = self.fixture(root)
        evidence = cold.creation_evidence(target, manifest, name)
        build = target / "data-v2-cold-read"
        build.mkdir()
        for source in cold.PINS:
            shutil.copyfile(cold.stage.PROVISIONING / source, build / source)
        contents = {build / "original-huntmob-prepare-userdata": b"public-original-helper",
                    build / "original-VirtualTrustCache": b"public-original-tc",
                    build / "huntmob-prepare-userdata": b"public-new-helper",
                    target / "firmware/VirtualTrustCache": b"public-new-tc",
                    target / "firmware/RestoreTrustCache": b"public-stock-tc",
                    target / "virtual-helper-build-data-checkpoint/init_data_protection": b"public-wrapper"}
        for path, data in contents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        record = {"schema": cold.SCHEMA, "profile": contract.PROFILE, "vm_uuid": VM_ID, "state": "preparing",
                  "data_uuid": DATA_ID, "creation_evidence": evidence, "source_sha256": dict(cold.PINS),
                  "root_accessed": False, "host_data_mounted": False,
                  "class_d_or_newfs_or_mkb_create_called": False, "cold_read_validated": False,
                  "native_ready": False, "ready": False,
                  "expected_probe_sha256": hashlib.sha256(CANARY.encode()).hexdigest()}
        (target / "data-v2-cold-read-intent.json").write_text(json.dumps(record))
        record.update(original_helper_sha256=cold.stage.digest(build / "original-huntmob-prepare-userdata"),
                      original_trustcache_sha256=cold.stage.digest(build / "original-VirtualTrustCache"),
                      helper_sha256=cold.stage.digest(build / "huntmob-prepare-userdata"),
                      trustcache_sha256=cold.stage.digest(target / "firmware/VirtualTrustCache"),
                      host_data_uuid=DATA_ID, host_data_encrypted=True, host_data_locked=True)
        manifest.update(cold_read_v2=record, root_provisioned=True, restore_checkpoint_observed=True,
                        effaceable_cold_persistence_observed=True, backings={"namespace-1.raw": {}})
        manifest["virtual_staging"] = {"phase": "data-checkpoint", "source_sha256": {
            "prepare_userdata_virtual_v1.c": cold.CREATION_SOURCE_SHA}, "helper_sha256": {
            "huntmob-prepare-userdata": record["original_helper_sha256"], "init_data_protection":
            cold.stage.digest(target / "virtual-helper-build-data-checkpoint/init_data_protection")},
            "trustcache_sha256": record["original_trustcache_sha256"]}
        manifest["firmware"] = {"files": {"RestoreTrustCache": {"path": str(target / "firmware/VirtualTrustCache"),
            "sha256": record["original_trustcache_sha256"]}}}
        return target, manifest

    def partial_context(self, target):
        stack = contextlib.ExitStack()
        stack.enter_context(patch.object(cold, "BASE_TC_SHA", cold.stage.digest(target / "firmware/RestoreTrustCache")))
        stack.enter_context(patch.object(cold, "cdhash", return_value="PUBLIC"))
        stack.enter_context(patch.object(cold.stage, "merged_trustcache", return_value=b"public-new-tc"))
        return stack

    def test_partial_recovery_binds_original_intent_new_files_backups_and_receipt(self):
        for alteration in ("none", "backup", "new-tc", "intent", "cold-observed", "single-use", "old-stage-hash", "receipt"):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as root:
                target, manifest = self.partial_fixture(root)
                if alteration == "backup":
                    (target / "data-v2-cold-read/original-huntmob-prepare-userdata").write_bytes(b"changed")
                elif alteration == "new-tc":
                    (target / "firmware/VirtualTrustCache").write_bytes(b"changed")
                elif alteration == "intent":
                    (target / "data-v2-cold-read-intent.json").write_text('{"state":"preparing"}')
                elif alteration == "cold-observed":
                    directory = target / "data-v2-observation-20261015-130000"
                    directory.mkdir()
                    (directory / "observation.json").write_text('{"cold_class_c_read_requested":true}')
                elif alteration == "single-use":
                    (target / "data-v2-cold-read-complete-partial-intent.json").write_text("{}")
                elif alteration == "old-stage-hash":
                    manifest["virtual_staging"]["trustcache_sha256"] = "0" * 64
                elif alteration == "receipt":
                    Path(manifest["cold_read_v2"]["creation_evidence"]["observation"], "boot.log").write_text("changed")
                with self.partial_context(target), patch.object(cold.stage, "attach_backing", side_effect=AssertionError("read only")), \
                     patch.object(cold.stage, "run", side_effect=AssertionError("read only")):
                    if alteration == "none":
                        self.assertIs(cold.checked_partial_install(target, manifest), manifest["cold_read_v2"])
                    else:
                        with self.assertRaises(ValueError):
                            cold.checked_partial_install(target, manifest)

    def test_partial_completion_only_reads_existing_system_files_and_commits_after_detach(self):
        for bad_live_helper in (False, True):
            with self.subTest(bad_live_helper=bad_live_helper), tempfile.TemporaryDirectory() as root:
                target, manifest = self.partial_fixture(root)
                calls, writes = [], []
                def run(argv, **kwargs):
                    calls.append(argv)
                    if argv[0] == "/sbin/mount_apfs":
                        self.assertEqual(argv[2], "rdonly,nobrowse,noowners")
                        mount = Path(argv[-1])
                        for name, data in {"usr/libexec/seputil": b"public-stock",
                            "usr/libexec/huntmob-original/init_data_protection": b"public-stock",
                            "usr/libexec/init_data_protection": b"public-wrapper",
                            "usr/libexec/huntmob-prepare-userdata": b"changed" if bad_live_helper else b"public-new-helper"}.items():
                            path = mount / name
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_bytes(data)
                    return SimpleNamespace(stdout=cold.plistlib.dumps(cold.ENTITLEMENTS))
                def write_manifest(*args):
                    self.assertEqual(calls[-1][:2], ["/usr/bin/hdiutil", "detach"])
                    writes.append(copy.deepcopy(args[1]))
                with self.partial_context(target), contextlib.ExitStack() as stack:
                    for obj, name, value in ((cold.contract, "target_for", lambda v: target),
                        (cold.contract, "validate_manifest", lambda t, m=None: manifest if m is None else m),
                        (cold.contract, "verify_engine", lambda m: None),
                        (cold.stage, "attach_backing", lambda *a: ("/dev/disk90", {})),
                        (cold, "owned_container", lambda d: self.container()),
                        (cold, "validate_system_mount", lambda *a: None),
                        (cold, "require_empty_mnt2", lambda *a: None),
                        (cold.profile, "verify_attachment", lambda *a: None),
                        (cold.profile, "write_manifest", write_manifest), (cold.stage, "run", run),
                        (cold.stage, "replace_known", lambda *a: self.fail("Recovery must not rewrite helper or TC"))):
                        stack.enter_context(patch.object(obj, name, value))
                    stack.enter_context(patch.object(cold.stage, "STOCK_SHA", hashlib.sha256(b"public-stock").hexdigest()))
                    if bad_live_helper:
                        with self.assertRaisesRegex(ValueError, "Already-installed cold helper"):
                            cold.complete_partial_install(VM_ID)
                        self.assertEqual(manifest["cold_read_v2"]["state"], "preparing")
                        self.assertEqual(writes, [])
                    else:
                        result = cold.complete_partial_install(VM_ID)
                        self.assertEqual(result["state"], "installed")
                        self.assertTrue(result["partial_install_completed_by_readback"])
                        self.assertEqual(len(writes), 1)
                    self.assertEqual(calls[-2][0], "/sbin/umount")
                    self.assertEqual(calls[-1], ["/usr/bin/hdiutil", "detach", "/dev/disk90"])
                    self.assertFalse(any("xcrun" in cmd or "newfs" in str(cmd) for cmd in calls))

    def test_bfu_denial_is_never_success_and_afu_match_requires_unlock(self):
        bfu = IDENTITY + "HuntMob: cold Class C unlocked-since-boot before=0\nHuntMob: cold Class C unlocked-since-boot after=0\nHuntMob: cold Class C result=bfu-denied\n"
        result = cold.classify_result(bfu)
        self.assertTrue(result["bfu_expected_denial_observed"])
        self.assertFalse(result["cold_read_validated"])
        with self.assertRaises(ValueError):
            cold.classify_result(bfu.replace("result=bfu-denied", "result=afu-read-match"))
        afu = bfu.replace("before=0", "before=1").replace("after=0", "after=1").replace("result=bfu-denied", "result=afu-read-match")
        self.assertTrue(cold.classify_result(afu)["cold_read_validated"])
        with self.assertRaises(ValueError):
            cold.classify_result(afu.replace(IDENTITY, ""))

    def test_mount_failure_before_unlock_remains_unvalidated(self):
        result = cold.classify_result("HuntMob: cold Class C unlocked-since-boot before=0\nHuntMob: cold Class C unlocked-since-boot after=0\nHuntMob: cold Class C result=bfu-mount-unvalidated\n")
        self.assertFalse(result["cold_read_validated"])
        self.assertFalse(result["bfu_expected_denial_observed"])

    def test_original_ascii_and_decoded_probe_are_forbidden_in_binary(self):
        cold.require_probe_absent(hashlib.sha256(CANARY.encode()).digest(), CANARY)
        for data in (b"public-prefix" + CANARY.encode(), b"public-prefix" + bytes.fromhex(CANARY)):
            with self.assertRaisesRegex(ValueError, "contaminate"):
                cold.require_probe_absent(data, CANARY)

    def test_helper_has_no_provision_or_keybag_load_path(self):
        source = (cold.stage.PROVISIONING / "verify_cold_data_v2.c").read_text()
        for token in ("O_CREAT", "O_TRUNC", "MKBLoad", "MKBKeyBagCreateSystem", "MKBDeviceObliterateClassDKey",
                      "newfs_apfs", "arc4random_buf", "HUNTMOB_EXPECTED_CANARY["):
            self.assertNotIn(token, source)
        self.assertIn("CC_SHA256(actual", source)
        self.assertIn("O_RDONLY | O_NOFOLLOW", source)

    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_native_c_bfu_policy_boundaries_public_fixture(self):
        code = '''#include "cold_read_policy_v2.h"
int main(void) {
if(huntmob_cold_classify(0,0,EACCES,0,0,0)!=HUNTMOB_COLD_BFU_DENIED)return 1;
if(huntmob_cold_classify(0,0,EPERM,0,0,0)!=HUNTMOB_COLD_BFU_DENIED)return 2;
if(huntmob_cold_classify(0,0,ENXIO,1,0,0)!=HUNTMOB_COLD_FAILURE)return 3;
if(huntmob_cold_classify(0,0,0,1,1,1)!=HUNTMOB_COLD_UNEXPECTED_BFU_ACCESS)return 4;
if(huntmob_cold_classify(0,1,0,1,1,1)!=HUNTMOB_COLD_STATE_CHANGED)return 5;
if(huntmob_cold_classify(1,1,0,1,1,1)!=HUNTMOB_COLD_AFU_MATCH)return 6;
if(huntmob_cold_classify(1,1,0,1,1,0)!=HUNTMOB_COLD_FAILURE)return 7;
if(huntmob_cold_classify(1,1,0,0,1,1)!=HUNTMOB_COLD_FAILURE)return 8;
return 0;}'''
        with tempfile.TemporaryDirectory(prefix="hm-cold-public-policy-") as root:
            source, binary = Path(root) / "public.c", Path(root) / "public-policy"
            source.write_text(code)
            subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-I", str(cold.stage.PROVISIONING), str(source), "-o", str(binary)],
                           check=True, capture_output=True, timeout=30)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=5)

    @unittest.skipUnless(shutil.which("xcrun"), "iPhoneOS SDK unavailable")
    def test_iphone_helper_build_uses_digest_only_and_contains_no_original_probe(self):
        sdk = subprocess.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], check=True, capture_output=True, text=True, timeout=30).stdout.strip()
        with tempfile.TemporaryDirectory(prefix="hm-cold-public-iphone-") as root:
            binary = Path(root) / "public-cold-helper"
            subprocess.run(["xcrun", "--sdk", "iphoneos", "clang", "-target", "arm64-apple-ios14.0", "-isysroot", sdk,
                            "-Wall", "-Wextra", "-Werror", "-O2", '-DHUNTMOB_VM_UUID="' + VM_ID + '"',
                            '-DHUNTMOB_EXPECTED_DATA_UUID="' + DATA_ID + '"',
                            '-DHUNTMOB_EXPECTED_CANARY_SHA256="' + hashlib.sha256(CANARY.encode()).hexdigest() + '"',
                            str(cold.stage.PROVISIONING / "verify_cold_data_v2.c"), "-o", str(binary)],
                           check=True, capture_output=True, timeout=60)
            cold.require_probe_absent(binary.read_bytes(), CANARY)


if __name__ == "__main__":
    unittest.main()
