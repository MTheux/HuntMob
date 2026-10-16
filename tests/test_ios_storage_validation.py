import unittest,tempfile,hashlib,json
from pathlib import Path
from unittest.mock import patch
from huntmob.ios_storage_validation import BACKINGS,validate_checkpoint

class StorageValidationTests(unittest.TestCase):
    def fixture(self,folder,plaintext=False):
        canary=b'1'*64;hashes={}
        for name in BACKINGS:
            content=b'padding'+(canary if plaintext and name=='namespace-1.raw' else b'ciphertext')
            (folder/name).write_bytes(content);hashes[name]=hashlib.sha256(content).hexdigest()
        (folder/'protected-data-proof.json').write_text(json.dumps({'version':1,'cohort_sha256':hashes}))
        (folder/'disk-boot-test.log').write_bytes(b'Class C probe roundtrip completed; synthetic canary='+canary)

    def test_plaintext_across_chunk_boundaries_rejects_storage(self):
        with tempfile.TemporaryDirectory() as directory,patch('huntmob.ios_storage_validation.CHUNK',17):
            folder=Path(directory);self.fixture(folder,True);r=validate_checkpoint(folder)
            self.assertTrue(r['plaintext_canary_found']);self.assertTrue(r['cohort_matches']);self.assertFalse(r['ready'])

    def test_canary_absence_never_claims_data_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder);r=validate_checkpoint(folder)
            self.assertEqual(r['state'],'not_proven');self.assertFalse(r['data_protection_validated'])

    def test_changed_disk_does_not_match_previous_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder);(folder/'namespace-1.raw').write_bytes(b'changed')
            self.assertFalse(validate_checkpoint(folder)['cohort_matches'])

    def test_missing_or_linked_backing_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder);(folder/'namespace-1.raw').unlink()
            with self.assertRaises(ValueError):validate_checkpoint(folder)
            (folder/'namespace-1.raw').symlink_to(folder/'namespace-2.raw')
            with self.assertRaises(ValueError):validate_checkpoint(folder)

    def test_earlier_backing_changed_during_later_scan_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            original_hash=hashlib.sha256;calls=0
            def hash_with_concurrent_mutation(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==2:
                    (folder/'namespace-1.raw').write_bytes(b'changed after first scan')
                return original_hash(*args,**kwargs)
            with patch('huntmob.ios_storage_validation.hashlib.sha256',side_effect=hash_with_concurrent_mutation):
                result=validate_checkpoint(folder)
            self.assertEqual(result['state'],'failed')
            self.assertFalse(result['cohort_matches'])
            self.assertFalse(result['evidence_stable'])
            self.assertFalse(result['backings'][0]['stable'])
            self.assertFalse(result['ready'])

    def test_receipt_changed_after_read_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            original_hash=hashlib.sha256;calls=0
            def hash_with_receipt_mutation(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==1:
                    (folder/'protected-data-proof.json').write_text('{}')
                return original_hash(*args,**kwargs)
            with patch('huntmob.ios_storage_validation.hashlib.sha256',side_effect=hash_with_receipt_mutation):
                result=validate_checkpoint(folder)
            self.assertEqual(result['state'],'failed')
            self.assertFalse(result['cohort_matches'])
            self.assertFalse(result['evidence_stable'])

    def test_backing_replaced_between_check_and_open_is_rejected(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            original_open=os.open
            def replacing_open(path,flags,*args,**kwargs):
                if Path(path).name=='namespace-1.raw':
                    Path(path).unlink()
                    Path(path).symlink_to(folder/'namespace-2.raw')
                return original_open(path,flags,*args,**kwargs)
            with patch('huntmob.ios_storage_validation.os.open',side_effect=replacing_open):
                with self.assertRaises(ValueError):validate_checkpoint(folder)

    def test_added_probe_log_during_scan_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            original_hash=hashlib.sha256;calls=0
            def hash_with_new_log(*args,**kwargs):
                nonlocal calls
                calls+=1
                if calls==1:
                    (folder/'disk-boot-late.log').write_bytes(b'late evidence')
                return original_hash(*args,**kwargs)
            with patch('huntmob.ios_storage_validation.hashlib.sha256',side_effect=hash_with_new_log):
                result=validate_checkpoint(folder)
            self.assertFalse(result['evidence_stable'])
            self.assertEqual(result['state'],'failed')

    def test_malformed_receipt_is_controlled_validation_error(self):
        for content in ('[]','null','{"version":1,"cohort_sha256":[]}', 'invalid json'):
            with self.subTest(content=content),tempfile.TemporaryDirectory() as directory:
                folder=Path(directory);self.fixture(folder)
                (folder/'protected-data-proof.json').write_text(content)
                with self.assertRaises(ValueError):validate_checkpoint(folder)

    def test_nonregular_receipt_and_oversize_log_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            proof=folder/'protected-data-proof.json';proof.unlink();proof.mkdir()
            with self.assertRaises(ValueError):validate_checkpoint(folder)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            (folder/'disk-boot-test.log').write_bytes(b'x'*(8*1024*1024+1))
            with self.assertRaises(ValueError):validate_checkpoint(folder)

    def test_longer_token_does_not_match_truncated_canary(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            (folder/'disk-boot-test.log').write_bytes(b'Class C probe roundtrip completed; synthetic canary='+b'1'*65)
            with self.assertRaises(ValueError):validate_checkpoint(folder)

    @unittest.skipUnless(hasattr(__import__('os'),'mkfifo'),'POSIX FIFO race test')
    def test_file_replaced_by_fifo_cannot_block_validation(self):
        import os
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            original_open=os.open
            def replacing_open(path,flags,*args,**kwargs):
                if Path(path).name=='namespace-1.raw':
                    Path(path).unlink();os.mkfifo(path)
                    self.assertTrue(flags & os.O_NONBLOCK)
                return original_open(path,flags,*args,**kwargs)
            with patch('huntmob.ios_storage_validation.os.open',side_effect=replacing_open):
                with self.assertRaises(ValueError):validate_checkpoint(folder)

    def test_boolean_receipt_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);self.fixture(folder)
            proof_path=folder/'protected-data-proof.json'
            proof=json.loads(proof_path.read_text());proof['version']=True
            proof_path.write_text(json.dumps(proof))
            with self.assertRaises(ValueError):validate_checkpoint(folder)
