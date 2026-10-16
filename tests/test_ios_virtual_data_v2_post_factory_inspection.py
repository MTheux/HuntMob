import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inspect_ios_virtual_data_v2_mount_contract as inspection
import stage_ios_virtual_data_v2_factorydata as seed


class PostFactoryInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name)
        self.observation = self.target / inspection.POST_FACTORY_BASELINE
        self.observation.mkdir()
        (self.observation / "boot.log").write_text("public failed mount fixture; no handler")
        initialized = {"schema": seed.SCHEMA, "profile": seed.contract.PROFILE, "vm_uuid": inspection.post.VM_UUID,
            "data_uuid": inspection.post.DATA_UUID, "hardware_uuid": inspection.HARDWARE_UUID, "source_sha256": seed.PINS,
            "engine_binding": {}, "state": "observed-original-restored", "observation": str(self.target / inspection.SEED_OBSERVATION),
            "original_helper_restored": True, "original_trustcache_restored": True,
            "own_prepare_marker_removed": True, "owned_device_detached": True}
        retry = {"previous_observation": str(self.target / inspection.BASELINE), "previous_receipt_sha256": inspection.BASELINE_SHA,
                 "factorydata_result_sha256": inspection.SEED_RESULT_SHA, "maximum_retries": 1,
                 "root_recreated": False, "Data_or_keys_reinitialized": False}
        self.manifest = {"vm_uuid": inspection.post.VM_UUID, "engine_binding": {}, "post_keybag_v2": {
            "schema": inspection.post.SCHEMA, "profile": seed.contract.PROFILE, "data_uuid": inspection.post.DATA_UUID,
            "state": "launch-requested", "observation": str(self.observation), "previous_observation": str(self.target / inspection.BASELINE),
            "factorydata_seed_rearmed": retry}, "factorydata_seed_v2": initialized,
            "virtual_staging": {"trustcache_sha256": seed.OLD_TC_SHA, "helper_sha256": {"huntmob-prepare-userdata": seed.OLD_COLD_SHA}}}
        self.proof = {"engine_binding": {}, "vm_uuid": inspection.post.VM_UUID, "post_keybag_class_c_read_requested": True,
            "factorydata_seed_requested": False, "qmp_quit_accepted": True, "exit_code": 0, "panic_observed": True,
            "checkpoint_observed": False, "boot.log_sha256": inspection.POST_FACTORY_BOOT_LOG_SHA,
            "trace.log_sha256": inspection.POST_FACTORY_TRACE_LOG_SHA, "aess_rejected_command_count": 0,
            "nvme_error_completion_count": 0, "protected_io_rejection_count": 0, "protected_gate_rejection_count": 0}
        self.current_receipt_sha = inspection.POST_FACTORY_BASELINE_SHA

    def verify(self):
        def digest(path):
            if path.parent.name == inspection.SEED_OBSERVATION:
                return inspection.SEED_OBSERVATION_SHA
            if path.name == "data-v2-factorydata-result.json":
                return inspection.SEED_RESULT_SHA
            if path.name == "observation.json":
                return self.current_receipt_sha
            return inspection.POST_FACTORY_BOOT_LOG_SHA if path.name == "boot.log" else inspection.POST_FACTORY_TRACE_LOG_SHA
        def metadata(path):
            if path.name == "data-v2-factorydata-result.json":
                return self.manifest["factorydata_seed_v2"]
            if path.name == "data-v2-post-keybag-factory-rearm-intent.json":
                return self.manifest["post_keybag_v2"]["factorydata_seed_rearmed"]
            return self.proof
        with mock.patch.object(inspection.stage, "digest", side_effect=digest), \
             mock.patch.object(inspection.contract, "read_metadata", side_effect=metadata), \
             mock.patch.object(inspection.cold, "observation", return_value=(self.target / inspection.SEED_OBSERVATION,
                {"factorydata_seed_requested": True, "post_keybag_class_c_read_requested": False}, "public fixture", "")), \
             mock.patch.object(seed, "classify_result", return_value={"factorydata_directories_prepared": True}):
            return inspection.baseline(self.target, self.manifest, "post-factory")

    def test_explicit_new_mode_accepts_only_complete_seed_restore_and_current_retry(self):
        result = self.verify()
        self.assertEqual(result["observation_sha256"], inspection.POST_FACTORY_BASELINE_SHA)
        self.assertEqual(result["original_baseline_preserved"], inspection.BASELINE)

    def test_original_mode_never_accepts_later_retry_and_new_mode_never_accepts_old(self):
        with self.assertRaises(ValueError):
            inspection.baseline(self.target, self.manifest)
        self.manifest["post_keybag_v2"]["observation"] = str(self.target / inspection.BASELINE)
        with self.assertRaises(ValueError):
            self.verify()

    def test_original_mode_retains_its_original_pinned_contract(self):
        self.manifest["post_keybag_v2"]["observation"] = str(self.target / inspection.BASELINE)
        proof = {**self.proof, "boot.log_sha256": inspection.BOOT_LOG_SHA, "trace.log_sha256": inspection.TRACE_LOG_SHA}
        def digest(path):
            return inspection.BASELINE_SHA if path.name == "observation.json" else inspection.BOOT_LOG_SHA if path.name == "boot.log" else inspection.TRACE_LOG_SHA
        with mock.patch.object(inspection.stage, "digest", side_effect=digest), \
             mock.patch.object(inspection.contract, "read_metadata", return_value=proof):
            value = inspection.baseline(self.target, self.manifest)
        self.assertEqual(value["observation"], inspection.BASELINE)
        self.assertEqual(value["observation_sha256"], inspection.BASELINE_SHA)

    def test_changed_receipt_current_post_flag_or_crypto_failure_rejected(self):
        self.current_receipt_sha = "changed"
        with self.assertRaises(ValueError):
            self.verify()
        self.current_receipt_sha = inspection.POST_FACTORY_BASELINE_SHA
        self.proof["post_keybag_class_c_read_requested"] = False
        with self.assertRaises(ValueError):
            self.verify()
        self.proof["post_keybag_class_c_read_requested"] = True
        self.proof["protected_io_rejection_count"] = 1
        with self.assertRaises(ValueError):
            self.verify()

    def test_partial_restore_or_changed_prior_identity_refused(self):
        for key in ("original_helper_restored", "original_trustcache_restored", "own_prepare_marker_removed", "owned_device_detached"):
            self.manifest["factorydata_seed_v2"][key] = False
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
            self.manifest["factorydata_seed_v2"][key] = True
        self.manifest["post_keybag_v2"]["factorydata_seed_rearmed"]["root_recreated"] = True
        with self.assertRaises(ValueError):
            self.verify()

    def test_default_cli_remains_original_and_explicit_new_cli_is_noop(self):
        for extra, expected in (([], "original"), (["--baseline", "post-factory"], "post-factory")):
            result = subprocess.run([sys.executable, inspection.__file__, "--vm-uuid", inspection.post.VM_UUID, *extra],
                                    check=True, capture_output=True)
            value = json.loads(result.stdout)
            self.assertTrue(value["read_only"])
            self.assertFalse(value["host_mount_performed"])
            self.assertEqual(value["inspection_baseline"], expected)


if __name__ == "__main__":
    unittest.main()
