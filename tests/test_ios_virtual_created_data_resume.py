"""Pure identity/layout guards; no VM, attachment, compiler, or Keychain use."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
SPEC = importlib.util.spec_from_file_location('created_data_resume', ROOT/'scripts/resume_ios_virtual_created_data.py')
resume = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resume)


class CreatedDataResumeGuards(unittest.TestCase):
    def manifest(self):
        return {'vm_uuid': resume.VM_UUID, 'root_provisioned': True,
                'old_cohort_cloned': False, 'ready': False,
                'virtual_staging': {'phase': 'data-checkpoint',
                  'helper_sha256': {'init_data_protection': resume.OLD_WRAPPER,
                                    'huntmob-prepare-userdata': resume.OLD_USERDATA},
                  'source_sha256': {'prepare_userdata_virtual_v1.c': resume.OLD_SOURCE,
                                    'virtual_v1_scope.h': resume.SCOPE_SHA},
                  'trustcache_sha256': resume.OLD_TC},
                'data_after_effaceable_helper': {'helper_sha256': resume.OLD_USERDATA},
                'effaceable_initialized_and_cold_verified': {'receipt_sha256': 'public-fixture'}}

    def container(self):
        return {'ContainerReference': 'disk10',
                'PhysicalStores': [{'DeviceIdentifier': 'disk9s1'}],
                'Volumes': [{'DeviceIdentifier': 'disk10s'+str(index), 'Roles': [role],
                             'Name': name, 'APFSVolumeUUID': uid,
                             'Encryption': encrypted, 'Locked': index == 2}
                            for index, (role, name, uid, encrypted) in resume.VOLUMES.items()]}

    def test_only_exact_predecessor_and_single_use(self):
        manifest = self.manifest()
        self.assertIs(resume.check_predecessor(manifest), manifest['virtual_staging'])
        for key in ('init_data_protection', 'huntmob-prepare-userdata'):
            changed = copy.deepcopy(manifest)
            changed['virtual_staging']['helper_sha256'][key] = '0'*64
            with self.assertRaises(ValueError): resume.check_predecessor(changed)
        for key in ('prepare_userdata_virtual_v1.c', 'virtual_v1_scope.h'):
            changed = copy.deepcopy(manifest)
            changed['virtual_staging']['source_sha256'][key] = '0'*64
            with self.assertRaises(ValueError): resume.check_predecessor(changed)
        manifest['created_data_resume'] = {'state': 'applying'}
        with self.assertRaises(ValueError): resume.check_predecessor(manifest)

    def test_wrong_phase_identity_and_tc_rejected(self):
        for key, value in (('vm_uuid', '00000000-0000-0000-0000-000000000000'),
                           ('root_provisioned', False), ('old_cohort_cloned', True),
                           ('ready', True), ('effaceable_initialized_and_cold_verified', {})):
            changed = self.manifest()
            changed[key] = value
            with self.assertRaises(ValueError): resume.check_predecessor(changed)
        for key, value in (('phase', 'restore-checkpoint'), ('trustcache_sha256', '0'*64)):
            changed = self.manifest()
            changed['virtual_staging'][key] = value
            with self.assertRaises(ValueError): resume.check_predecessor(changed)

    def test_exact_encrypted_locked_data_accepted(self):
        self.assertEqual(resume.checked_layout(self.container(), '/dev/disk9'), '/dev/disk10s1')

    def test_foreign_old_unencrypted_or_unlocked_data_rejected(self):
        for key, value in (('APFSVolumeUUID', '795B31FE-9808-48EF-9893-D1D19C087CEE'),
                           ('Name', 'Historical Data'), ('Roles', []), ('Encryption', False),
                           ('Locked', False), ('MountPoint', '/Volumes/Data'),
                           ('DeviceIdentifier', 'disk10s6')):
            changed = self.container()
            changed['Volumes'][1][key] = value
            with self.assertRaises(ValueError): resume.checked_layout(changed, '/dev/disk9')

    def test_every_stock_auxiliary_uuid_and_role_is_bound(self):
        for index in (0, 2, 3, 4):
            for key, value in (('APFSVolumeUUID', resume.DATA_UUID), ('Roles', ['Data']),
                               ('Encryption', True), ('MountPoint', '/Volumes/foreign')):
                changed = self.container()
                changed['Volumes'][index][key] = value
                with self.assertRaises(ValueError): resume.checked_layout(changed, '/dev/disk9')

    def test_no_extra_duplicate_or_foreign_physical_store(self):
        for stores in ([{'DeviceIdentifier': 'disk90s1'}],
                       [{'DeviceIdentifier': 'disk9s1'}, {'DeviceIdentifier': 'disk8s1'}], []):
            changed = self.container()
            changed['PhysicalStores'] = stores
            with self.assertRaises(ValueError): resume.checked_layout(changed, '/dev/disk9')
        changed = self.container()
        changed['Volumes'].append(copy.deepcopy(changed['Volumes'][1]))
        with self.assertRaises(ValueError): resume.checked_layout(changed, '/dev/disk9')
        changed = self.container()
        changed['Volumes'][2]['DeviceIdentifier'] = 'disk10s2'
        with self.assertRaises(ValueError): resume.checked_layout(changed, '/dev/disk9')
        for device in ('/dev/disk9s1', '/dev/rdisk9', '/dev/disk90/../disk9'):
            with self.assertRaises(ValueError): resume.checked_layout(self.container(), device)

    def test_missing_mountpoint_plan_does_not_create(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'mnt2'
            self.assertFalse(resume.check_mountpoint(path))
            self.assertFalse(path.exists())
            self.assertFalse(resume.check_mountpoint(path, create=True))
            self.assertTrue(path.is_dir())
            self.assertTrue(resume.check_mountpoint(path, create=True))

    def test_existing_mountpoint_must_be_empty_regular_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'mnt2'
            path.mkdir()
            (path/'owned').write_text('fixture')
            with self.assertRaises(ValueError): resume.check_mountpoint(path, create=True)
            (path/'owned').unlink()
            with mock.patch.object(resume.os.path, 'ismount', return_value=True):
                with self.assertRaises(ValueError): resume.check_mountpoint(path)
            path.rmdir()
            path.write_text('fixture')
            with self.assertRaises(ValueError): resume.check_mountpoint(path)

    def test_mountpoint_dangling_or_directory_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            path = parent/'mnt2'
            for destination in (parent/'missing', parent):
                path.symlink_to(destination)
                with self.assertRaises(ValueError): resume.check_mountpoint(path, create=True)
                path.unlink()


if __name__ == '__main__':
    unittest.main()
