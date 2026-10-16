import hashlib
import json
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stage_ios_virtual_data_v2_post_keybag as post


def afu_log():
    identity = "HuntMob: post-keybag Data UUID CPROTECT and existing-bag identity matched"
    return "\n".join([identity, "HuntMob: post-keybag stock-init-start",
        "HuntMob: post-keybag stock-init-exit=0 signal=0", identity,
        "HuntMob: post-keybag Class C unlocked-since-boot before=1",
        "HuntMob: post-keybag Class C unlocked-since-boot after=1",
        "HuntMob: post-keybag Class C access_errno=0 metadata_valid=1 read_complete=1 digest_match=1",
        "HuntMob: post-keybag Class C result=afu-read-match", post.STOP_MARKER])


class PostKeybagTests(unittest.TestCase):
    def test_actual_afu_digest_match_only_marks_read_validated(self):
        value = post.classify_result(afu_log())
        self.assertTrue(value["read_validated"])
        self.assertFalse(value["native_ready"])
        self.assertFalse(value["ready"])

    def test_failed_incomplete_repeated_or_out_of_order_stock_init_refused(self):
        good = afu_log()
        bad = [good.replace("stock-init-exit=0 signal=0", "stock-init-exit=1 signal=0"),
               good + "\nHuntMob: post-keybag stock-init-exit=1 signal=0",
               good + "\nHuntMob: post-keybag stock-init-start",
               good.replace("HuntMob: post-keybag stock-init-start\n", "").replace(
                   "stock-init-exit=0 signal=0", "stock-init-exit=0 signal=0\nHuntMob: post-keybag stock-init-start"),
               good.replace(post.STOP_MARKER, ""), good + "\nHuntMob: ClassD initialization status=0"]
        for log in bad:
            with self.subTest(log=log), self.assertRaises(ValueError):
                post.classify_result(log)

    def test_false_afu_or_digest_and_metadata_failure_refused(self):
        for old, new in (("before=1", "before=0"), ("after=1", "after=0"), ("metadata_valid=1", "metadata_valid=0"),
                         ("read_complete=1", "read_complete=0"), ("digest_match=1", "digest_match=0"), ("access_errno=0", "access_errno=1")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                post.classify_result(afu_log().replace(old, new))

    def test_bfu_denial_and_unlock_transition_remain_unvalidated(self):
        bfu = afu_log().replace("before=1", "before=0").replace("after=1", "after=0").replace(
            "access_errno=0 metadata_valid=1 read_complete=1 digest_match=1", "access_errno=1 metadata_valid=0 read_complete=0 digest_match=0").replace(
            "result=afu-read-match", "result=bfu-denied")
        result = post.classify_result(bfu)
        self.assertFalse(result["read_validated"])
        self.assertTrue(result["bfu_expected_denial_observed"])
        changed = afu_log().replace("after=1", "after=0").replace("result=afu-read-match", "result=unlock-state-changed-unvalidated")
        self.assertFalse(post.classify_result(changed)["read_validated"])

    def test_raw_tc_keeps_all_existing_entries_and_adds_only_shim(self):
        identity = uuid.uuid5(uuid.UUID(post.VM_UUID), "HuntMob.VirtualSEP.v1.TrustCache").bytes
        entries = [bytes.fromhex("1" * 40) + b"\x02\x00", bytes.fromhex("2" * 40) + b"\x02\x00"]
        old = struct.pack("<I", 1) + identity + struct.pack("<I", len(entries)) + b"".join(entries)
        updated = post.add_only_shim_tc(old, "3" * 40, post.VM_UUID)
        self.assertEqual(updated[:20], old[:20])
        self.assertEqual(struct.unpack_from("<I", updated, 20)[0], 3)
        self.assertEqual({updated[n:n + 22] for n in range(24, len(updated), 22)}, set(entries + [bytes.fromhex("3" * 40) + b"\x02\x00"]))
        for corrupted in (old[:-1], old[:4] + b"x" * 16 + old[20:], old[:20] + struct.pack("<I", 3) + old[24:]):
            with self.assertRaises(ValueError):
                post.add_only_shim_tc(corrupted, "3" * 40, post.VM_UUID)
        with self.assertRaises(ValueError):
            post.add_only_shim_tc(old, "1" * 40, post.VM_UUID)

    def test_source_pins_match_reviewed_files(self):
        for name, sha in post.PINS.items():
            self.assertEqual(hashlib.sha256((post.stage.PROVISIONING / name).read_bytes()).hexdigest(), sha, name)

    def test_wrong_readback_hash_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "artifact"
            source.write_bytes(b"wrong-readback")
            with self.assertRaises(ValueError):
                post.verify_hash(source, "0" * 64)
            link = Path(directory) / "alias"
            link.symlink_to(source)
            with self.assertRaises(ValueError):
                post.verify_hash(link, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_normal_daemon_cache_must_not_gain_program_override(self):
        cache = {"LaunchDaemons": {"/System/Library/LaunchDaemons/com.apple.mobile.keybagd.plist": {
            "Label": "com.apple.mobile.keybagd", "ProgramArguments": ["/usr/libexec/keybagd", "-t", "15"]}}}
        post.checked_cache(cache)
        cache["LaunchDaemons"]["/System/Library/LaunchDaemons/com.apple.mobile.keybagd.plist"]["Program"] = "/other"
        with self.assertRaises(ValueError):
            post.checked_cache(cache)

    def test_wrong_failed_baseline_receipt_blocks_before_any_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            manifest = {"vm_uuid": post.VM_UUID, "engine_binding": {}, "cold_read_v2": {
                "data_uuid": post.DATA_UUID, "state": "launch-requested", "observation": str(target / post.BASELINE)}}
            with mock.patch.object(post.contract, "read_metadata", return_value={}), \
                 mock.patch.object(post.stage, "digest", return_value="wrong-receipt"):
                with self.assertRaises(ValueError):
                    post.baseline_evidence(target, manifest)

    def test_default_cli_remains_a_noop_without_a_real_cohort(self):
        result = subprocess.run([sys.executable, post.__file__, "--vm-uuid", post.VM_UUID], check=True, capture_output=True)
        value = json.loads(result.stdout)
        self.assertTrue(value["read_only"])
        self.assertFalse(value["root_accessed"])
        self.assertFalse(value["host_data_mounted"])


if __name__ == "__main__":
    unittest.main()
