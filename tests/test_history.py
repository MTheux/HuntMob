import json
import tempfile
import unittest
from pathlib import Path

from huntmob import history


def _lab(lab_id, engagement, package, created='2026-01-01T00:00:00', state='saved'):
    return {'id': lab_id, 'engagement': engagement, 'package_id': package,
            'created_at': created, 'state': state}


class HistoryIndexTests(unittest.TestCase):
    def test_connect_creates_schema_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'history.db'
            history.connect(db).close()
            conn = history.connect(db)  # segunda vez não pode falhar
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            self.assertIn('labs', names)
            self.assertIn('evidence', names)

    def test_record_lab_then_list_engagements(self):
        conn = history.connect(':memory:')
        history.record_lab(_lab('huntmob_a', 'AcmeApp', 'com.acme'), conn=conn)
        engagements = history.list_engagements(conn=conn)
        self.assertIn('AcmeApp', [row['engagement'] for row in engagements])
        conn.close()

    def test_record_lab_is_reentrant_upsert(self):
        conn = history.connect(':memory:')
        history.record_lab(_lab('huntmob_a', 'AcmeApp', 'com.acme', state='saved'), conn=conn)
        history.record_lab(_lab('huntmob_a', 'AcmeApp', 'com.acme', state='closed'), conn=conn)
        rows = list(conn.execute('SELECT status FROM labs WHERE lab_id=?', ('huntmob_a',)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'closed')
        conn.close()

    def test_record_evidence_linked_to_lab(self):
        conn = history.connect(':memory:')
        history.record_lab(_lab('huntmob_a', 'AcmeApp', 'com.acme'), conn=conn)
        history.record_evidence('huntmob_a', 'screenshot', '/ev/a.png', label='tela inicial', conn=conn)
        rows = [tuple(r) for r in conn.execute('SELECT lab_id, kind, path, label FROM evidence')]
        self.assertEqual(rows, [('huntmob_a', 'screenshot', '/ev/a.png', 'tela inicial')])
        conn.close()

    def test_search_matches_engagement_and_package(self):
        conn = history.connect(':memory:')
        history.record_lab(_lab('huntmob_a', 'AcmeApp', 'com.acme'), conn=conn)
        history.record_lab(_lab('huntmob_b', 'OutroCliente', 'org.other'), conn=conn)
        by_eng = [row['lab_id'] for row in history.search('acme', conn=conn)]
        by_pkg = [row['lab_id'] for row in history.search('org.other', conn=conn)]
        self.assertEqual(by_eng, ['huntmob_a'])
        self.assertEqual(by_pkg, ['huntmob_b'])
        conn.close()

    def test_backfill_is_reentrant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for lab_id, eng in (('huntmob_x', 'A'), ('huntmob_y', 'B')):
                (root / f'{lab_id}.json').write_text(json.dumps(_lab(lab_id, eng, 'com.x')))
            conn = history.connect(':memory:')
            self.assertEqual(history.backfill(conn=conn, root=root), 2)
            history.backfill(conn=conn, root=root)  # reentrante
            count = list(conn.execute('SELECT COUNT(*) FROM labs'))[0][0]
            self.assertEqual(count, 2)
            conn.close()


class SaveHookTests(unittest.TestCase):
    def test_save_feeds_history_index(self):
        from unittest.mock import patch
        from huntmob import lab_sessions
        with tempfile.TemporaryDirectory() as tmp:
            seen = []
            with patch.object(lab_sessions, 'root', return_value=Path(tmp)), \
                 patch('huntmob.history.record_lab', side_effect=lambda rec: seen.append(rec)):
                lab_sessions.save(_lab('huntmob_a', 'AcmeApp', 'com.acme'))
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0]['id'], 'huntmob_a')

    def test_save_writes_index_under_root_not_real_home(self):
        from unittest.mock import patch
        from huntmob import lab_sessions, history
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(lab_sessions, 'root', return_value=root):
                lab_sessions.save(_lab('huntmob_z', 'ZCo', 'com.z'))
                conn = history.connect()  # default deve derivar de root()
                rows = history.search('ZCo', conn=conn)
                conn.close()
            self.assertEqual([r['lab_id'] for r in rows], ['huntmob_z'])
            self.assertTrue((root / 'history.db').exists())

    def test_save_is_best_effort_when_index_fails(self):
        from unittest.mock import patch
        from huntmob import lab_sessions
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            def boom(_rec):
                raise RuntimeError('índice indisponível')
            with patch.object(lab_sessions, 'root', return_value=root), \
                 patch('huntmob.history.record_lab', side_effect=boom):
                lab_sessions.save(_lab('huntmob_a', 'AcmeApp', 'com.acme'))  # não pode propagar
            self.assertTrue((root / 'huntmob_a.json').is_file())  # lab salvo mesmo assim


if __name__ == '__main__':
    unittest.main()
