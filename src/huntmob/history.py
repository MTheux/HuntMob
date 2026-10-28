"""Índice SQLite ADITIVO de engajamentos/evidências.

O estado vivo dos labs continua nos JSON de ``lab_sessions`` (~/.huntmob/labs);
este módulo mantém um índice derivado e consultável (histórico + busca) em
``~/.huntmob/history.db``. É reconstruível a qualquer momento pelo ``backfill``,
então o JSON é a verdade e o índice é descartável. Stdlib apenas (sqlite3).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def default_db_path() -> Path:
    # Deriva de lab_sessions.root() para que o índice fique ao lado dos labs e,
    # em testes que fazem patch de root(), seja redirecionado junto (sem tocar o
    # ~/.huntmob real).
    from . import lab_sessions
    return lab_sessions.root() / 'history.db'


_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS labs (
        lab_id TEXT PRIMARY KEY,
        engagement TEXT NOT NULL DEFAULT '',
        package_id TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT '',
        record_path TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lab_id TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT '',
        path TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT ''
    )""",
)


def connect(db_path=None) -> sqlite3.Connection:
    """Abre (criando o schema idempotente) a conexão do índice."""
    if db_path is None:
        db_path = default_db_path()
    if db_path != ':memory:':
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    if str(db_path) != ':memory:':
        conn.execute('PRAGMA journal_mode=WAL')
    for statement in _SCHEMA:
        conn.execute(statement)
    conn.commit()
    return conn


def _with_conn(conn, operation):
    """Executa ``operation`` numa conexão própria quando nenhuma é passada."""
    if conn is not None:
        return operation(conn)
    owned = connect()
    try:
        result = operation(owned)
        owned.commit()
        return result
    finally:
        owned.close()


def record_lab(record, conn=None):
    """Upsert de um lab no índice a partir do seu record JSON."""
    def op(c):
        c.execute(
            """INSERT INTO labs (lab_id, engagement, package_id, created_at, status, record_path)
               VALUES (:lab_id, :engagement, :package_id, :created_at, :status, :record_path)
               ON CONFLICT(lab_id) DO UPDATE SET
                 engagement=excluded.engagement, package_id=excluded.package_id,
                 created_at=excluded.created_at, status=excluded.status,
                 record_path=CASE WHEN excluded.record_path != '' THEN excluded.record_path ELSE labs.record_path END""",
            {
                'lab_id': record.get('id', ''),
                'engagement': record.get('engagement', '') or '',
                'package_id': record.get('package_id', '') or '',
                'created_at': record.get('created_at', '') or '',
                'status': record.get('state', '') or '',
                'record_path': record.get('record_path', '') or '',
            },
        )
        if conn is None:
            c.commit()
    return _with_conn(conn, op)


def record_evidence(lab_id, kind, path, label='', created_at='', conn=None):
    def op(c):
        c.execute(
            'INSERT INTO evidence (lab_id, kind, path, label, created_at) VALUES (?,?,?,?,?)',
            (lab_id, kind, path, label, created_at),
        )
        if conn is None:
            c.commit()
    return _with_conn(conn, op)


def list_engagements(conn=None):
    """Engajamentos distintos com contagem de labs e o último created_at."""
    def op(c):
        rows = c.execute(
            """SELECT engagement, COUNT(*) AS labs, MAX(created_at) AS last_created_at
               FROM labs GROUP BY engagement ORDER BY last_created_at DESC"""
        ).fetchall()
        return [dict(row) for row in rows]
    return _with_conn(conn, op)


def search(query, conn=None):
    """Labs cujo engagement ou package_id casa com ``query`` (LIKE, case-insensitive)."""
    def op(c):
        like = f'%{query}%'
        rows = c.execute(
            """SELECT lab_id, engagement, package_id, created_at, status FROM labs
               WHERE engagement LIKE ? COLLATE NOCASE OR package_id LIKE ? COLLATE NOCASE
               ORDER BY created_at DESC""",
            (like, like),
        ).fetchall()
        return [dict(row) for row in rows]
    return _with_conn(conn, op)


def backfill(conn=None, root=None):
    """Varre os JSON de labs e faz upsert de cada um. Reentrante. Devolve a contagem."""
    if root is None:
        from . import lab_sessions
        root = lab_sessions.root()
    root = Path(root)

    def op(c):
        import json
        count = 0
        for path in sorted(root.glob('huntmob_*.json')):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError, TypeError):
                continue
            if not record.get('id'):
                continue
            record = {**record, 'record_path': str(path)}
            record_lab(record, conn=c)
            count += 1
        if conn is None:
            c.commit()
        return count
    return _with_conn(conn, op)
