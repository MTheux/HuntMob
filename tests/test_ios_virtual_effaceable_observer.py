"""Predecessor guards for the query-only native diagnostic; no firmware runs."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import boot_ios_virtual_profile as boot
import stage_ios_virtual_effaceable_ramdisk as ramdisk
SPEC = importlib.util.spec_from_file_location('effaceable_observer', ROOT/'scripts/observe_ios_virtual_effaceable.py')
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class EffaceableObserverGuards(unittest.TestCase):
    def manifest(self):
        return {'virtual_staging': {'phase': 'data-checkpoint',
                'helper_sha256': {'init_data_protection': observer.OLD_WRAPPER,
                                  'huntmob-prepare-userdata': observer.OLD_USERDATA},
                'trustcache_sha256': observer.OLD_TC}}

    def test_only_exact_predecessor_accepted(self):
        manifest = self.manifest()
        self.assertIs(observer.check_predecessor(manifest), manifest['virtual_staging'])
        for key in ('init_data_protection', 'huntmob-prepare-userdata'):
            changed = copy.deepcopy(manifest)
            changed['virtual_staging']['helper_sha256'][key] = '0'*64
            with self.assertRaises(ValueError): observer.check_predecessor(changed)
        manifest['virtual_staging']['trustcache_sha256'] = '0'*64
        with self.assertRaises(ValueError): observer.check_predecessor(manifest)

    def test_restore_phase_and_repeat_rejected(self):
        manifest = self.manifest()
        manifest['virtual_staging']['phase'] = 'restore-checkpoint'
        with self.assertRaises(ValueError): observer.check_predecessor(manifest)
        manifest = self.manifest()
        manifest['effaceable_query_observer'] = {'ready': False}
        with self.assertRaises(ValueError): observer.check_predecessor(manifest)

    def test_resume_requires_cold_checkpoint_and_exact_observer(self):
        manifest = self.manifest()
        manifest['virtual_staging']['helper_sha256']['huntmob-prepare-userdata'] = observer.OBSERVER_USERDATA
        manifest['virtual_staging']['trustcache_sha256'] = observer.OBSERVER_TC
        with self.assertRaises(ValueError): observer.check_predecessor(manifest, resume=True)
        manifest['effaceable_initialized_and_cold_verified'] = {'receipt_sha256': 'public-fixture'}
        self.assertIs(observer.check_predecessor(manifest, resume=True), manifest['virtual_staging'])
        manifest['data_after_effaceable_helper'] = {'ready': False}
        with self.assertRaises(ValueError): observer.check_predecessor(manifest, resume=True)

    def test_initializer_rejects_repeat_nonempty_namespace_and_changed_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'namespace-6.raw').write_bytes(bytes(4096))
            build = root/'effaceable-ramdisk-v1'
            build.mkdir()
            (build/'RestoreRamDisk.raw').write_bytes(b'public ramdisk fixture')
            (build/'RestoreTrustCache').write_bytes(b'public trustcache fixture')
            record = {'state': 'prepared', 'fresh_ns6_zero_verified': True,
                      'secure_root_policy_changed': False, 'sep_restore_or_erase_requested': False,
                      'ramdisk_path': str(build/'RestoreRamDisk.raw'),
                      'ramdisk_sha256': boot.digest(build/'RestoreRamDisk.raw'),
                      'trustcache_path': str(build/'RestoreTrustCache'),
                      'trustcache_sha256': boot.digest(build/'RestoreTrustCache')}
            manifest = {'effaceable_ramdisk': record}
            self.assertEqual(set(boot.effaceable_ramdisk_inputs(root, manifest)),
                             {'RestoreRamDisk', 'RestoreTrustCache'})
            record['state'] = 'launch-requested'
            with self.assertRaises(ValueError): boot.effaceable_ramdisk_inputs(root, manifest)
            record['state'] = 'prepared'
            (root/'namespace-6.raw').write_bytes(b'X'+bytes(4095))
            with self.assertRaises(ValueError): boot.effaceable_ramdisk_inputs(root, manifest)
            (root/'namespace-6.raw').write_bytes(bytes(4096))
            (build/'RestoreRamDisk.raw').write_bytes(b'changed')
            with self.assertRaises(ValueError): boot.effaceable_ramdisk_inputs(root, manifest)

    def test_scope_retry_cannot_repeat_format_or_ignore_backend_write(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'namespace-6.raw').write_bytes(bytes(4096))
            observation = root/'observation-public-fixture'
            observation.mkdir()
            log = observation/'boot.log'
            trace = observation/'trace.log'
            log.write_text('HuntMob: trusted effaceable RAMdisk scope rejected\n')
            trace.write_text('')
            (observation/'observation.json').write_text(json.dumps({
                'effaceable_ramdisk_requested': True, 'panic_observed': False}))
            manifest = {'virtual_staging': {'phase': 'data-checkpoint'},
                        'effaceable_query_observer': {'observe_only': True},
                        'backings': {'namespace-6.raw': ramdisk.stage.profile.fingerprint(root/'namespace-6.raw')},
                        'effaceable_ramdisk': {'state': 'launch-requested',
                          'source_sha256': '89b79af9ba20580d1674f158e1361a04aed3fdbffed385c94911ad0f69daf24b',
                          'observation': str(observation)}}
            ramdisk.require_fresh(root, manifest, scope_diagnostics=True)
            trace.write_text('pci_nvme_apple_ans_submit sqid=1 cid=17 opcode=0x01 nsid=6\n')
            with self.assertRaises(ValueError): ramdisk.require_fresh(root, manifest, scope_diagnostics=True)
            trace.write_text('')
            log.write_text('HuntMob: trusted effaceable RAMdisk scope rejected\nHuntMob: trusted effaceable stock format status=0\n')
            with self.assertRaises(ValueError): ramdisk.require_fresh(root, manifest, scope_diagnostics=True)


if __name__ == '__main__': unittest.main()
