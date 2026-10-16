import importlib.util
import tempfile
import subprocess
import sys
import time
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'ios_engine_build', Path(__file__).resolve().parents[1] / 'scripts/build_ios_research_engine.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class DiagnosticEngineBuildTests(unittest.TestCase):
    def test_disabled_or_commented_protection_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            header = source / 'include/hw/arm/apple-silicon/boot.h'
            header.parent.mkdir(parents=True)
            for content in ('/* #define ENABLE_DATA_ENCRYPTION */',
                            '// #define ENABLE_DATA_ENCRYPTION',
                            '#define ENABLE_DATA_ENCRYPTION 0'):
                header.write_text(content)
                with self.assertRaisesRegex(ValueError, 'enabled'):
                    build.require_data_protection(source)
            header.write_text('/* comment */\n#define ENABLE_DATA_ENCRYPTION\n')
            with self.assertRaisesRegex(ValueError, 'pinned source'):
                build.require_data_protection(source)

    def test_inactive_or_redefined_macro_cannot_claim_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            header = source / 'include/hw/arm/apple-silicon/boot.h'
            header.parent.mkdir(parents=True)
            for content in ('#if 0\n#define ENABLE_DATA_ENCRYPTION\n#endif\n',
                            '#define ENABLE_DATA_ENCRYPTION\n#undef ENABLE_DATA_ENCRYPTION\n'):
                header.write_text(content)
                with self.assertRaisesRegex(ValueError, 'pinned source'):
                    build.require_data_protection(source)

    @unittest.skipUnless(hasattr(__import__('os'), 'killpg'), 'POSIX process groups')
    def test_timeout_terminates_descendant_compilers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'child-survived'
            child = 'import time,pathlib; time.sleep(1); pathlib.Path(' + repr(str(marker)) + ').write_text("alive")'
            parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(child) + ']); time.sleep(10)'
            with self.assertRaises(subprocess.TimeoutExpired):
                build.run([sys.executable, '-c', parent], root, root / 'log', .25)
            time.sleep(1.1)
            self.assertFalse(marker.exists())

    def test_rom_or_boot_patch_cannot_enter_diagnostics_recipe(self):
        with tempfile.TemporaryDirectory() as directory:
            patch = Path(directory) / 'patch'
            for name in ('include/hw/arm/apple-silicon/boot.h', 'roms/sep.bin', '../outside'):
                patch.write_text(f'diff --git a/{name} b/{name}\n')
                with self.assertRaisesRegex(ValueError, 'outside'):
                    build.check_patches([patch])

    def test_existing_output_is_not_deleted_or_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'existing'
            output.mkdir()
            original = output / 'owned.raw'
            original.write_bytes(b'existing lab')
            with self.assertRaises(FileExistsError):
                build.reserve_output(output)
            self.assertEqual(original.read_bytes(), b'existing lab')

    def test_symlink_patch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = Path(directory) / 'original'
            original.write_text('diff --git a/hw/nvme/ctrl.c b/hw/nvme/ctrl.c\n')
            symlink = Path(directory) / 'link'
            symlink.symlink_to(original)
            with self.assertRaisesRegex(ValueError, 'Invalid'):
                build.check_patches([symlink])


if __name__ == '__main__':
    unittest.main()
