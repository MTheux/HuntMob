import unittest
from huntmob.ios_identity import simulator_identity


class IdentityTests(unittest.TestCase):
    def test_simulator_identity_does_not_authorize_physical_provisioning(self):
        value='b34d90f1-05c4-4a26-8449-5df7dc029834'
        result=simulator_identity({'udid':value})
        self.assertEqual(result['value'],value)
        self.assertTrue(result['available'])
        self.assertFalse(result['apple_physical_device_provisioning_supported'])
        self.assertEqual(result['backend_allowlist_acceptance'],'not-validated')
        self.assertTrue(result['survives_worker_restart'])
        self.assertEqual(result['app_identifier_matches_simulator_uuid'],'not-validated')

    def test_unknown_or_arbitrary_identity_is_not_exported(self):
        for record in [None,{}, {'udid':'private arbitrary data'}, {'udid':17}]:
            result=simulator_identity(record)
            self.assertFalse(result['available'])
            self.assertIsNone(result['value'])
            self.assertFalse(result['survives_worker_restart'])
            self.assertNotIn('private arbitrary',str(result))
