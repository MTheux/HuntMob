import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_auxiliary as auxiliary
import ios_virtual_data_v2_contract as contract


class PreGuestStartupRearmTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / ("virtual-sep-data-v2-" + "a" * 70)
        self.target.mkdir()
        self.run = self.target / "data-v2-observation-test"
        self.run.mkdir()
        self.manifest = {"vm_uuid": "new", "data_profile_sha256": "profile", "engine_binding": {"binary": "engine"},
                         "root_provisioned": True, "auxiliary_bootstrap_v2": {"schema": auxiliary.BOOTSTRAP_SCHEMA,
                         "profile": contract.PROFILE, "vm_uuid": "new", "state": "launch-requested", "observation": str(self.run)}}
        qmp = str(self.target / "qmp.sock")
        command_qmp = "unix:" + qmp + ",server=on,wait=off"
        content = ("-qmp " + command_qmp + ": UNIX socket path '" + qmp + "' is too long\nPath must be less than 104 bytes\n").encode()
        (self.run / "boot.log").write_bytes(content)
        self.receipt = {"schema": "huntmob.virtual-sep-data-observation.v2", "vm_uuid": "new", "data_profile": contract.PROFILE,
            "data_profile_sha256": "profile", "engine_binding": {"binary": "engine"}, "auxiliary_bootstrap_requested": True,
            "effaceable_ramdisk_requested": False, "effaceable_observer_requested": False, "root_pipe_delivered": True,
            "root_in_python": False, "stop_reason": "engine-exited", "exit_code": 1, "checkpoint_observed": False,
            "panic_observed": False, "qmp_quit_requested": False, "qmp_quit_accepted": False, "elapsed_seconds": 0.1,
            "aess_command_count": 0, "aess_commands": [], "virtual_mpe_controls": [], "virtual_mpe_boot_jump_requested": False,
            "sep_os_alive_observed": False, "stock_data_protection_verifier_invoked": False,
            "command": ["engine", "-qmp", command_qmp], "boot.log_sha256": hashlib.sha256(content).hexdigest(),
            "trace.log_sha256": hashlib.sha256(b"").hexdigest()}
        self.write()

    def write(self):
        (self.run / "observation.json").write_text(json.dumps(self.receipt))

    def test_exact_failure_can_rearm_without_recreating_root(self):
        evidence = auxiliary.checked_startup_failure(self.target, self.manifest)
        self.assertFalse(evidence["root_recreation_allowed"])
        self.assertEqual(evidence["maximum_retries"], 1)

    def test_any_trace_or_changed_log_refused(self):
        (self.run / "trace.log").write_text("cpu-started")
        with self.assertRaises(ValueError):
            auxiliary.checked_startup_failure(self.target, self.manifest)
        (self.run / "trace.log").unlink()
        with (self.run / "boot.log").open("a") as stream:
            stream.write("guest output")
        with self.assertRaises(ValueError):
            auxiliary.checked_startup_failure(self.target, self.manifest)

    def test_guest_progress_or_other_failure_refused(self):
        for key, value in (("exit_code", 2), ("stop_reason", "bounded-observation-ended"), ("elapsed_seconds", 10),
                           ("aess_command_count", 1), ("sep_os_alive_observed", True), ("panic_observed", True),
                           ("stock_data_protection_verifier_invoked", True), ("engine_binding", {}), ("root_pipe_delivered", False)):
            with self.subTest(key=key):
                old = self.receipt[key]
                self.receipt[key] = value
                self.write()
                with self.assertRaises(ValueError):
                    auxiliary.checked_startup_failure(self.target, self.manifest)
                self.receipt[key] = old

    def test_active_launch_or_second_retry_refused(self):
        for filename in (".data-v2-launch.lock", "data-v2-auxiliary-startup-rearm-intent.json"):
            path = self.target / filename
            path.write_text("exists")
            with self.assertRaises(ValueError):
                auxiliary.checked_startup_failure(self.target, self.manifest)
            path.unlink()
        self.manifest["auxiliary_bootstrap_v2"]["startup_failure_rearmed"] = {"reason": "already-used"}
        with self.assertRaises(ValueError):
            auxiliary.checked_startup_failure(self.target, self.manifest)

    def test_root_must_already_exist_and_remain_same_identity(self):
        self.manifest["root_provisioned"] = False
        with self.assertRaises(ValueError):
            auxiliary.checked_startup_failure(self.target, self.manifest)


if __name__ == "__main__":
    unittest.main()
