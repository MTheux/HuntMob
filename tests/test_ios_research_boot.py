import importlib.util
import plistlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('boot_ios_research', Path(__file__).resolve().parents[1]/'scripts/boot_ios_research.py')
boot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)


class ResearchBootTests(unittest.TestCase):
    def archive(self, root, build='18A5351d', traversal=False):
        archive = root/'fixture.ipsw'
        names = {k: ('../outside' if traversal else k) for k in
                 ['KernelCache', 'DeviceTree', 'RestoreRamDisk', 'RestoreTrustCache']}
        manifest = {'ProductVersion': '14.0', 'ProductBuildVersion': build,
                    'SupportedProductTypes': ['iPhone12,1'],
                    'BuildIdentities': [{'Info': {'DeviceClass': 'n104ap',
                    'Variant': 'Research Developer Erase Install (IPSW)'},
                    'Manifest': {k: {'Info': {'Path': v}} for k, v in names.items()}}]}
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('BuildManifest.plist', plistlib.dumps(manifest))
            for name in set(names.values()):
                output.writestr(name, b'fixture data')
            output.writestr('unselected', b'must not extract')
        return archive

    def test_wrong_build_is_rejected_without_creating_vm(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'vm'
            with self.assertRaisesRegex(ValueError, 'pinned'):
                boot.prepare(self.archive(root, build='unsupported'), target)
            self.assertFalse(target.exists())

    def test_unsafe_component_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'vm'
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                boot.prepare(self.archive(root, traversal=True), target)
            self.assertFalse(target.exists())
            self.assertFalse((root/'outside').exists())

    def test_only_selected_components_are_written_and_hashed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'vm';receipt=boot.prepare(self.archive(root), target)
            self.assertEqual(len(list(target.iterdir())), 4)
            self.assertFalse((target/'unselected').exists())
            for entry in receipt['files'].values():
                self.assertEqual(entry['sha256'], boot.digest(Path(entry['path'])))

    def test_existing_vm_contents_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'vm';target.mkdir()
            original=target/'KernelCache';original.write_bytes(b'existing data')
            with self.assertRaises(FileExistsError):
                boot.prepare(self.archive(root), target)
            self.assertEqual(original.read_bytes(), b'existing data')

    def test_research_disks_and_monitor_are_local_and_nvram_has_required_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            files={k:{'path':str(root/k)} for k in
                   ['KernelCache','DeviceTree','RestoreRamDisk','RestoreTrustCache']}
            args=boot.command(Path('/test/engine'),root,files)
            self.assertIn('-snapshot',args)
            self.assertIn('none',args)
            self.assertIn(f'unix:{root}/qmp.sock,server=on,wait=off',args)
            self.assertTrue(any(x.startswith('apple-nvram,id=nvram,') for x in args))
            self.assertEqual((root/'namespace-1.raw').stat().st_size,32*1024**3)


    def test_x86_companion_uses_its_private_usb_and_ticket(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            files={k:{'path':str(root/k)} for k in ['KernelCache','DeviceTree','RestoreRamDisk','RestoreTrustCache']}
            args=boot.command(Path('/test/engine'),root,files,restore=True,companion_profile='x86_64')
            machine=args[args.index('-M')+1]
            self.assertIn('ios-companion-x86_64/usb.sock',machine)
            self.assertIn('ios-companion-x86_64/root_ticket.der',machine)
            self.assertNotIn('-snapshot',args)

    def test_unknown_companion_cannot_create_disks(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(ValueError):
                boot.command(Path('/test/engine'),root,{},companion_profile='../other')
            self.assertEqual(list(root.iterdir()),[])

    def test_host_transfer_is_not_guest_restore_or_usable_ui(self):
        result=boot.restore_observations('Done sending filesystem 100%\nASR RESTORE PROGRESS: 4%')
        self.assertEqual(result['guest_asr_progress_percent'],4)
        self.assertFalse(result['full_restore_validated'])
        self.assertFalse(result['springboard_validated'])
        self.assertFalse(result['ipa_execution_validated'])

    def test_stage1_marker_is_not_full_restore(self):
        result=boot.restore_observations('ASR RESTORE PROGRESS: 100%\nDetected potentially-completed restore process.')
        self.assertTrue(result['restore_stage1_exit_observed'])
        self.assertFalse(result['full_restore_validated'])

    def test_recovery_preflight_requires_verified_companion_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(ValueError): boot.check_companion_ready(root)
            (root/'ready.json').write_text(json.dumps({'tools_build_complete':False,'ipsw_sha256':boot.IPSW_SHA}))
            with self.assertRaises(ValueError): boot.check_companion_ready(root)
            (root/'ready.json').write_text(json.dumps({'tools_build_complete':True,'ipsw_sha256':boot.IPSW_SHA}))
            boot.check_companion_ready(root)

    def test_single_thread_comparison_keeps_full_sep_cpu_count(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            files={k:{'path':str(root/k)} for k in ['KernelCache','DeviceTree','RestoreRamDisk','RestoreTrustCache']}
            args=boot.command(Path('/test/engine'),root,files,restore=True,sep=True,companion_profile='x86_64',tcg_thread='single')
            self.assertEqual(args[args.index('-accel')+1],'tcg,thread=single')
            self.assertEqual(args[args.index('-smp')+1],'7')
            self.assertEqual(args[args.index('-nic')+1],'none')
