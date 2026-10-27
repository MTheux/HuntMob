import tempfile
import unittest
from pathlib import Path

from scripts.prune_ios_vms import allocated_bytes, guard_targets, prune, scan, select_targets


def _vm_with_checkpoints(root, name, stamps):
    vm = root / name
    vm.mkdir()
    (vm / "namespace-1.raw").write_bytes(b"base")
    for stamp in stamps:
        (vm / ("checkpoint-phase-" + stamp)).mkdir()
    return vm


class ScanTests(unittest.TestCase):
    def test_scan_marks_newest_checkpoint_as_tip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vm = root / "virtual-sep-v1-abc"
            vm.mkdir()
            (vm / "namespace-1.raw").write_bytes(b"base")
            (vm / "checkpoint-before-first-20261015-120000").mkdir()
            (vm / "checkpoint-before-second-20261015-150000").mkdir()

            vms = scan(root)

            self.assertEqual([info.name for info in vms], ["virtual-sep-v1-abc"])
            tips = [c for c in vms[0].checkpoints if c.is_tip]
            self.assertEqual([c.name for c in tips], ["checkpoint-before-second-20261015-150000"])


class SelectSupersededTests(unittest.TestCase):
    def test_superseded_selects_non_tip_checkpoints_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _vm_with_checkpoints(root, "virtual-sep-v1-abc",
                                 ["20261015-120000", "20261015-150000", "20261015-180000"])

            vms = scan(root)
            targets = select_targets(vms, superseded=["virtual-sep-v1-abc"])

            names = sorted(p.name for p in targets)
            self.assertEqual(names, ["checkpoint-phase-20261015-120000",
                                     "checkpoint-phase-20261015-150000"])


class SelectWholeVmTests(unittest.TestCase):
    def test_whole_vm_with_chain_requires_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _vm_with_checkpoints(root, "virtual-sep-v1-abc", ["20261015-120000"])
            vms = scan(root)
            with self.assertRaises(ValueError):
                select_targets(vms, whole_vms=["virtual-sep-v1-abc"])

    def test_whole_vm_with_chain_allowed_with_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _vm_with_checkpoints(root, "virtual-sep-v1-abc", ["20261015-120000"])
            vms = scan(root)
            targets = select_targets(vms, whole_vms=["virtual-sep-v1-abc"], force=True)
            self.assertEqual([p.name for p in targets], ["virtual-sep-v1-abc"])


class SelectTracesTests(unittest.TestCase):
    def test_traces_before_selects_whole_old_trace_vms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "native-storage-trace-20261014-fresh").mkdir()
            (root / "native-storage-trace-20261015-map").mkdir()
            (root / "native-storage-trace-20261016-late").mkdir()
            (root / "virtual-sep-v1-abc").mkdir()

            vms = scan(root)
            targets = select_targets(vms, traces_before="2026-10-16")

            self.assertEqual(sorted(p.name for p in targets),
                             ["native-storage-trace-20261014-fresh",
                              "native-storage-trace-20261015-map"])


class AllocatedBytesTests(unittest.TestCase):
    def test_sparse_file_reports_allocated_not_logical_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sparse = root / "namespace-1.raw"
            with open(sparse, "wb") as handle:
                handle.truncate(32 * 1024 * 1024 * 1024)  # 32 GiB logical, ~0 allocated

            measured = allocated_bytes(root)

            self.assertEqual(measured, sparse.stat().st_blocks * 512)
            self.assertLess(measured, sparse.stat().st_size)


class GuardTests(unittest.TestCase):
    def test_refuses_target_outside_vm_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "ios-vms"
            root.mkdir()
            outside = Path(tmp) / "elsewhere"
            outside.mkdir()
            with self.assertRaises(ValueError):
                guard_targets([outside], root)

    def test_refuses_checkpoint_when_owning_vm_may_be_active(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vm = root / "virtual-sep-v1-abc"
            checkpoint = vm / "checkpoint-phase-20261015-120000"
            checkpoint.mkdir(parents=True)
            (vm / "qmp.sock").touch()  # owning VM looks active
            with self.assertRaises(ValueError):
                guard_targets([checkpoint], root)

    def test_allows_valid_inactive_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vm = root / "virtual-sep-v1-abc"
            checkpoint = vm / "checkpoint-phase-20261015-120000"
            checkpoint.mkdir(parents=True)
            guard_targets([checkpoint], root)  # must not raise


class PruneTests(unittest.TestCase):
    def _superseded_checkpoint(self, root):
        vm = root / "virtual-sep-v1-abc"
        checkpoint = vm / "checkpoint-phase-20261015-120000"
        checkpoint.mkdir(parents=True)
        (checkpoint / "namespace-1.raw").write_bytes(b"x" * 4096)
        return checkpoint

    def test_dry_run_does_not_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = self._superseded_checkpoint(root)

            result = prune([checkpoint], root, apply=False)

            self.assertTrue(checkpoint.exists())
            self.assertFalse(result.applied)
            self.assertEqual([p.name for p in result.targets], [checkpoint.name])

    def test_apply_removes_targets_and_measures_free_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = self._superseded_checkpoint(root)

            result = prune([checkpoint], root, apply=True)

            self.assertFalse(checkpoint.exists())
            self.assertTrue(result.applied)
            self.assertIsInstance(result.free_before, int)
            self.assertGreaterEqual(result.free_after, result.free_before)

    def test_apply_with_archive_writes_tarball_then_removes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = self._superseded_checkpoint(root)
            archive_dir = root / "archive"

            result = prune([checkpoint], root, apply=True, archive_dir=archive_dir)

            self.assertFalse(checkpoint.exists())
            tarball = archive_dir / (checkpoint.name + ".tar.gz")
            self.assertTrue(tarball.exists())
            self.assertEqual([p.name for p in result.archived], [tarball.name])

    def test_apply_refuses_active_vm_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            checkpoint = self._superseded_checkpoint(root)
            (checkpoint.parent / "qmp.sock").touch()

            with self.assertRaises(ValueError):
                prune([checkpoint], root, apply=True)
            self.assertTrue(checkpoint.exists())


if __name__ == "__main__":
    unittest.main()
