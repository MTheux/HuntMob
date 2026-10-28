import tempfile
import unittest
from pathlib import Path

from huntmob.web_assets import web_revision


class WebRevisionTests(unittest.TestCase):
    def test_web_revision_changes_when_web_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp)
            (web / 'a.js').write_text('one')
            first = web_revision(web)
            (web / 'a.js').write_text('two')
            self.assertNotEqual(first, web_revision(web))

    def test_web_revision_stable_for_identical_content(self):
        with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
            for base in (t1, t2):
                (Path(base) / 'a.js').write_text('same')
                (Path(base) / 'b.css').write_text('x')
            self.assertEqual(web_revision(Path(t1)), web_revision(Path(t2)))

    def test_web_revision_tracks_renames(self):
        with tempfile.TemporaryDirectory() as tmp:
            web = Path(tmp)
            (web / 'a.js').write_text('same')
            first = web_revision(web)
            (web / 'a.js').rename(web / 'b.js')
            self.assertNotEqual(first, web_revision(web))


if __name__ == '__main__':
    unittest.main()
