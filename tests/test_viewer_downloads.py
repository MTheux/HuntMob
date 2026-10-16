import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from huntmob import viewer_downloads as v
class ViewerDownloadTests(unittest.TestCase):
 def test_no_arbitrary_paths_or_files(self):
  for name in ['../../secret','manifest.json','unknown.exe','huntmob-viewer-0.1.0-macos-arm64.zip/../secret']:
   with self.assertRaises(ValueError):v.artifact(name)
 def test_missing_build_is_not_a_fake_download(self):
  with tempfile.TemporaryDirectory() as d,patch.object(v,'ROOT',Path(d)):
   self.assertEqual(v.catalog()['artifacts'],[])
 def test_size_or_symlink_mismatch_rejected(self):
  with tempfile.TemporaryDirectory() as d,patch.object(v,'ROOT',Path(d)):
   p=Path(d);name='huntmob-viewer-0.1.0-macos-arm64.zip';(p/name).write_bytes(b'app')
   (p/'manifest.json').write_text(json.dumps({'artifacts':[{'filename':name,'size':2}]}))
   self.assertEqual(v.catalog()['artifacts'],[])
   (p/'manifest.json').write_text(json.dumps({'artifacts':[{'filename':name,'size':3}]}))
   self.assertEqual(v.artifact(name),p/name)

class ViewerRangeTests(unittest.TestCase):
 def test_partial_and_resume_ranges(self):
  self.assertEqual(v.byte_range('bytes=10-19',100),(10,19,True))
  self.assertEqual(v.byte_range('bytes=90-',100),(90,99,True))
  self.assertEqual(v.byte_range('bytes=-5',100),(95,99,True))
 def test_invalid_ranges_rejected(self):
  for value in ['bytes=200-','bytes=20-10','bytes=-0','bytes=1-2,4-5','garbage']:
   with self.assertRaises(ValueError):v.byte_range(value,100)
