import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_observer as observer
import ios_virtual_data_v2_contract as contract


class DataV2ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name)
        self.run = self.target / "data-v2-observation-test"
        self.run.mkdir()
        self.manifest = {"vm_uuid": "new-uuid", "data_profile_sha256": "profilehash", "engine_binding": {"binary_sha256": "engine"}}
        self.record = {"schema": "huntmob.virtual-sep-data-effaceable.v2", "state": "launch-requested",
                       "vm_uuid": "new-uuid", "profile": contract.PROFILE, "observation": str(self.run)}
        self.manifest["effaceable_ramdisk_v2"] = self.record
        self.receipt = {"schema": "huntmob.virtual-sep-data-observation.v2", **self.manifest,
                        "effaceable_ramdisk_requested": True, "checkpoint_observed": True, "panic_observed": False,
                        "qmp_quit_accepted": True, "exit_code": 0}
        self.lines = ["HuntMob: trusted effaceable root device-is-md0=1", "HuntMob: preloaded NVMe online exit=0 signal=0",
                      "HuntMob: trusted effaceable before status=0 count=1 formatted=0", "HuntMob: trusted effaceable stock format status=0",
                      "HuntMob: trusted effaceable after status=0 count=1 formatted=1",
                      "HuntMob: provisioning checkpoint ready; trusted effaceable formatted=1"]
        self.write()

    def write(self, lines=None, trace=None):
        (self.run / "boot.log").write_text("\n".join(self.lines if lines is None else lines))
        (self.run / "trace.log").write_text("pci_nvme_apple_ans_submit sqid=1 cid=7 opcode=0x01 nsid=6 slba=0" if trace is None else trace)
        for name in ("boot.log", "trace.log"):
            self.receipt[name + "_sha256"] = hashlib.sha256((self.run / name).read_bytes()).hexdigest()
        (self.run / "observation.json").write_text(json.dumps(self.receipt))

    def test_actual_fresh_format_contract_accepted(self):
        result = observer.validate_formatted_ramdisk(self.target, self.manifest)
        self.assertEqual(result["observation"], str(self.run))
        self.assertEqual(len(result["receipt_sha256"]), 64)

    def test_formatter_return_zero_without_query_transition_rejected(self):
        self.write([line for line in self.lines if "after status=" not in line])
        with self.assertRaises(ValueError):
            observer.validate_formatted_ramdisk(self.target, self.manifest)

    def test_wrong_identity_engine_failed_shutdown_or_missing_real_write_rejected(self):
        for key, value in (("vm_uuid", "old"), ("engine_binding", {"binary_sha256": "different"}),
                           ("qmp_quit_accepted", False), ("panic_observed", True), ("exit_code", 1)):
            with self.subTest(key=key):
                old = self.receipt[key]
                self.receipt[key] = value
                self.write()
                with self.assertRaises(ValueError):
                    observer.validate_formatted_ramdisk(self.target, self.manifest)
                self.receipt[key] = old
        self.write(trace="pci_nvme_apple_ans_submit sqid=1 cid=7 opcode=0x02 nsid=6")
        with self.assertRaises(ValueError):
            observer.validate_formatted_ramdisk(self.target, self.manifest)

    def test_replayed_other_cohort_observation_refused(self):
        self.record["observation"] = str(self.target.parent / "data-v2-observation-old")
        with self.assertRaises(ValueError):
            observer.validate_formatted_ramdisk(self.target, self.manifest)

    def test_data_initialization_in_formatter_rejected(self):
        for line in ("HuntMob: ClassD initialization status=0", "HuntMob virtual v1: fresh MKBCreateSystem returned zero"):
            self.write(self.lines + [line])
            with self.assertRaises(ValueError):
                observer.validate_formatted_ramdisk(self.target, self.manifest)

    def test_log_changed_after_receipt_rejected(self):
        for name in ("boot.log", "trace.log"):
            self.write()
            with (self.run / name).open("a") as stream:
                stream.write("\nchanged-after-receipt")
            with self.assertRaises(ValueError):
                observer.validate_formatted_ramdisk(self.target, self.manifest)


if __name__ == "__main__":
    unittest.main()
