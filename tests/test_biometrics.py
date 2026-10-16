import unittest
from types import SimpleNamespace
from unittest.mock import patch
from huntmob.biometrics import control

class BiometricTests(unittest.TestCase):
    def worker(self):return SimpleNamespace(sdk=SimpleNamespace(adb='adb'),serial='emulator-5558',avd_name='owned')
    def result(self,text,code=0):return SimpleNamespace(stdout=text,returncode=code)
    def test_idle_history_is_not_a_pending_request(self):
        values=[self.result('feature:android.hardware.fingerprint'),self.result('History: FingerprintAuthenticationClient\nCurrent operation: null\n{"prints":[{"count":1}]}')]
        with patch('huntmob.biometrics._run',side_effect=values) as run:
            data=control(self.worker(),{'action':'biometric-touch','finger_id':1})
        self.assertFalse(data['ok']);self.assertEqual(run.call_count,2)
    def test_pending_enrollment_receives_native_touch_and_release(self):
        values=[self.result('feature:android.hardware.fingerprint'),self.result('Current operation: {[12] FingerprintEnrollClient}\n'),self.result('OK'),self.result('OK')]
        with patch('huntmob.biometrics._run',side_effect=values) as run:
            data=control(self.worker(),{'action':'biometric-touch','finger_id':2})
        self.assertTrue(data['dispatched']);self.assertEqual(data['biometrics']['pending'],'enrollment')
        self.assertEqual(run.call_args_list[-2].args[0][-3:],('finger','touch','2'))
        self.assertEqual(run.call_args_list[-1].args[0][-2:],('finger','remove'))
    def test_invalid_finger_and_missing_sensor_do_not_send_events(self):
        for feature,finger in [('feature:android.hardware.fingerprint',True),('',1)]:
            with patch('huntmob.biometrics._run',side_effect=[self.result(feature),self.result('Current operation: FingerprintAuthenticationClient')]) as run:
                if feature:
                    with self.assertRaises(ValueError):control(self.worker(),{'action':'biometric-touch','finger_id':finger})
                else:self.assertFalse(control(self.worker(),{'action':'biometric-touch','finger_id':finger})['ok'])
                self.assertEqual(run.call_count,2)
