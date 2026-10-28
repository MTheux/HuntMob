import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from huntmob import history, cli


def _seed(db):
    conn = history.connect(db)
    history.record_lab({'id': 'huntmob_a', 'engagement': 'AcmeApp', 'package_id': 'com.acme',
                        'created_at': '2026-01-01', 'state': 'saved'}, conn=conn)
    conn.commit()
    conn.close()


class CliHistoryTests(unittest.TestCase):
    def _run(self, db, argv):
        out = io.StringIO()
        with patch('huntmob.history.default_db_path', return_value=db), \
             patch.object(sys, 'argv', argv), redirect_stdout(out):
            code = cli.main()
        return code, out.getvalue()

    def test_cli_history_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'h.db'
            _seed(db)
            code, text = self._run(db, ['huntmob', 'history'])
            self.assertEqual(code, 0)
            self.assertIn('AcmeApp', text)

    def test_cli_search_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'h.db'
            _seed(db)
            code, text = self._run(db, ['huntmob', 'search', 'acme'])
            self.assertEqual(code, 0)
            data = json.loads(text)
            self.assertEqual([row['lab_id'] for row in data], ['huntmob_a'])


if __name__ == '__main__':
    unittest.main()
