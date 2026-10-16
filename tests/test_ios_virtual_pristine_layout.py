import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('virtual_pristine', SCRIPTS / 'restore_ios_virtual_pristine.py')
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)
UUID = '52c79047-1d89-4a97-bf6b-cc2d6b9d742c'


class PristineLayoutTests(unittest.TestCase):
    def make_disk(self, stream, vm_id=UUID):
        size = 32 * 1024**3
        stream.truncate(size)
        for offset, value in layout.gpt(size, vm_id).items():
            os.pwrite(stream.fileno(), value, offset)
        return size

    def test_primary_and_backup_crc_partition_one_exact_geometry(self):
        with tempfile.TemporaryFile() as stream:
            size = self.make_disk(stream)
            layout.verify_gpt(stream.fileno(), size)
            self.assertEqual(os.pread(stream.fileno(), 8, 4096), b'EFI PART')
            self.assertEqual(os.pread(stream.fileno(), 4096, 6 * 4096), bytes(4096))

    def test_backup_header_corruption_refused(self):
        with tempfile.TemporaryFile() as stream:
            size = self.make_disk(stream)
            os.pwrite(stream.fileno(), b'\xff', size - 4096 + 32)
            with self.assertRaisesRegex(ValueError, 'CRC mismatch'):
                layout.verify_gpt(stream.fileno(), size)

    def test_extra_partition_corrupts_entry_crc(self):
        with tempfile.TemporaryFile() as stream:
            size = self.make_disk(stream)
            os.pwrite(stream.fileno(), b'\xff', 2 * 4096 + 128)
            with self.assertRaisesRegex(ValueError, 'CRC mismatch'):
                layout.verify_gpt(stream.fileno(), size)

    def test_vm_identity_changes_public_partition_guid(self):
        first = layout.gpt(32 * 1024**3, UUID)
        other = layout.gpt(32 * 1024**3, '5db4d5b9-52da-4424-b3b8-52c224196550')
        self.assertNotEqual(first[8192][16:32], other[8192][16:32])


if __name__ == '__main__':
    unittest.main()
