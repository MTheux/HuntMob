"""Pure auxiliary-bootstrap layout guards; never mounts, formats or boots."""
import importlib.util
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('aux_bootstrap_under_test',ROOT/'scripts/install_auxiliary_bootstrap_vm.py')
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class AuxiliaryBootstrapGuards(unittest.TestCase):
    def test_helper_refresh_requires_prior_reviewed_stage_and_is_single_use(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            for action,previous,current in (
                    ('refresh-timeouts','restore_helper_refresh','restore_helper_diagnostics'),
                    ('refresh-registration','restore_helper_diagnostics','restore_helper_registration')):
                for extra in ({}, {previous:{'reviewed':True},current:{'applied':True}}):
                    manifest={'auxiliary_bootstrap':{'state':'restored-original'},**extra}
                    with mock.patch.object(bootstrap.stage,'run') as run:
                        with self.assertRaisesRegex(ValueError,'single-use'):
                            bootstrap.prepare_binary(target,manifest,action)
                        run.assert_not_called()

    def test_timeout_refresh_rejects_replaced_previous_binary_before_compiling(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)
            (target/'auxiliary-bootstrap-build').mkdir()
            original=target/'auxiliary-bootstrap-build/original-init_data_protection'
            original.write_bytes(b'original-public-fixture')
            (target/'virtual-helper-restore-refresh').mkdir()
            prior=target/'virtual-helper-restore-refresh/init_data_protection'
            prior.write_bytes(b'changed-public-fixture')
            original_sha=bootstrap.stage.digest(original)
            manifest={'auxiliary_bootstrap':{'state':'restored-original','original_wrapper_sha256':original_sha},
                      'virtual_staging':{'helper_sha256':{'init_data_protection':'expected-different-hash'}},
                      'restore_helper_refresh':{'wrapper_sha256':'expected-different-hash',
                                                'original_wrapper_sha256':original_sha}}
            with mock.patch.object(bootstrap.stage,'run') as run:
                with self.assertRaisesRegex(ValueError,'Preceding reviewed'):
                    bootstrap.prepare_binary(target,manifest,'refresh-timeouts')
                run.assert_not_called()

    def test_authorization_only_resigns_existing_binary_and_exact_entitlement(self):
        with tempfile.TemporaryDirectory(prefix='huntmob-authorize-guard-') as directory:
            target=Path(directory)
            build=target/'auxiliary-bootstrap-build'
            build.mkdir()
            original=build/'init_data_protection'
            original.write_bytes(b'public-owned-compiled-fixture')
            source=build/'init_auxiliary_virtual_v1.c'
            source.write_bytes(b'public-owned-source-fixture')
            sha=bootstrap.stage.digest(original)
            manifest={'virtual_staging':{'helper_sha256':{'init_data_protection':sha}},
                      'auxiliary_bootstrap':{'state':'installed','bootstrap_wrapper_sha256':sha,
                      'source_sha256':{source.name:bootstrap.stage.digest(source)}}}
            def fake_codesign(arguments, **kwargs):
                self.assertEqual(arguments[0],'codesign')
                data=plistlib.dumps({'com.apple.private.apfs.xart':True}) if '-d' in arguments else b''
                return SimpleNamespace(stdout=data,stderr=b'')
            with mock.patch.object(bootstrap.stage,'run',side_effect=fake_codesign):
                binary,_=bootstrap.prepare_binary(target,manifest,'authorize-bootstrap')
            self.assertEqual(binary.read_bytes(),original.read_bytes())
            self.assertEqual(bootstrap.stage.digest(original),sha)
            self.assertEqual(plistlib.loads((binary.parent/'parent-xart-entitlement.plist').read_bytes()),
                             {'com.apple.private.apfs.xart':True})

    def volume(self,index,name,role):
        return {'Name':name,'Roles':[role],'DeviceIdentifier':'disk10s'+str(index),
                'APFSVolumeUUID':'test-guid-'+str(index),'Encryption':False}

    def layout(self):
        system=self.volume(1,'Stock','System')
        reserve=self.volume(2,'HuntMobEmptyDataSlot','Data')
        return {'ContainerReference':'disk10','Volumes':[system,reserve]},reserve

    def test_bootstrap_accepts_only_original_two_slots(self):
        container,reserve=self.layout()
        self.assertEqual(bootstrap.checked_layout(container,reserve,False),'/dev/disk10s1')
        container['Volumes'].append(self.volume(3,'xART','xART'))
        with self.assertRaises(ValueError):bootstrap.checked_layout(container,reserve,False)

    def test_foreign_placeholder_and_mounted_data_rejected(self):
        container,reserve=self.layout()
        with self.assertRaises(ValueError):
            bootstrap.checked_layout(container,{**reserve,'APFSVolumeUUID':'foreign'},False)
        container['Volumes'][1]['MountPoint']='/Volumes/Unexpected'
        with self.assertRaises(ValueError):bootstrap.checked_layout(container,reserve,False)

    def test_restore_requires_auxiliaries_and_no_data(self):
        container,reserve=self.layout()
        container['Volumes']=container['Volumes'][:1]+[
            self.volume(3,'xART','xART'),self.volume(4,'Hardware','Hardware'),self.volume(5,'Preboot','Preboot')]
        self.assertEqual(bootstrap.checked_layout(container,reserve,True),'/dev/disk10s1')
        container['Volumes'].append(reserve)
        with self.assertRaises(ValueError):bootstrap.checked_layout(container,reserve,True)

    def test_slot_or_role_substitution_rejected(self):
        container,reserve=self.layout()
        container['Volumes']=container['Volumes'][:1]+[
            self.volume(3,'xART','xART'),self.volume(4,'Hardware','Hardware'),self.volume(5,'Preboot','Preboot')]
        container['Volumes'][1]['Roles']=['Data']
        with self.assertRaises(ValueError):bootstrap.checked_layout(container,reserve,True)
        container['Volumes'][1]['Roles']=['xART']
        container['Volumes'][1]['DeviceIdentifier']='disk10s2'
        with self.assertRaises(ValueError):bootstrap.checked_layout(container,reserve,True)


if __name__=='__main__':unittest.main()
