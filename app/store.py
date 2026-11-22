import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.errors import InputError
from app.manifest import canonical, sha256


class Archive:
    def __init__(self, path):
        self.path = Path(path)

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("""CREATE TABLE IF NOT EXISTS runs (
            digest TEXT PRIMARY KEY, payload TEXT NOT NULL
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS volumes (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision INTEGER NOT NULL,
            scope TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
            parent TEXT, created_at TEXT NOT NULL,
            UNIQUE(run_id, revision)
        )""")
        return connection

    def find(self, digest):
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT payload FROM runs WHERE digest = ?", (digest,)).fetchone()
        return json.loads(row[0]) if row else None

    def get(self, digest):
        result = self.find(digest)
        if result is None:
            raise InputError("RUN_NOT_FOUND", "找不到该归档", 404)
        return result

    def save(self, record):
        with closing(self.connect()) as connection, connection:
            inserted = connection.execute(
                "INSERT INTO runs VALUES (?, ?) ON CONFLICT(digest) DO NOTHING",
                (record["id"], canonical(record)),
            ).rowcount
            payload = connection.execute("SELECT payload FROM runs WHERE digest = ?", (record["id"],)).fetchone()[0]
        return json.loads(payload), not inserted

    # 签核卷：同一运行按轮次只新增一条，重跑沿用既有轮次而不复制。

    def latest_volume(self, run_id):
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM volumes WHERE run_id = ? ORDER BY revision DESC LIMIT 1", (run_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def volume(self, run_id, volume_id):
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT payload FROM volumes WHERE run_id = ? AND id = ?", (run_id, volume_id)
            ).fetchone()
        if row is None:
            raise InputError("REVISION_NOT_FOUND", "找不到该签核版本", 404)
        return json.loads(row[0])

    def volumes(self, run_id):
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT payload FROM volumes WHERE run_id = ? ORDER BY revision", (run_id,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def record_volume(self, run_id, scope, status, payload):
        """重跑同一批时延续原签核（含恢复出的最新轮次），不新增重复记录。"""
        scope_key = canonical(sorted(scope))
        with closing(self.connect()) as connection:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT payload FROM volumes WHERE run_id = ? AND scope = ? AND status = ? "
                    "ORDER BY revision DESC LIMIT 1", (run_id, scope_key, status),
                ).fetchone()
                result = ({**json.loads(row[0]), "reused": True} if row is not None
                          else self._insert_volume(connection, run_id, scope, status, payload, None))
                connection.execute("COMMIT")
                return result
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def _insert_volume(self, connection, run_id, scope, status, payload, parent, restored_from=None):
        """在既有写事务内追加一条签核轮次，原轮次与原始依据保持不动。"""
        scope_key = canonical(sorted(scope))
        row = connection.execute(
            "SELECT revision, id FROM volumes WHERE run_id = ? ORDER BY revision DESC LIMIT 1", (run_id,)
        ).fetchone()
        revision = (row[0] if row else 0) + 1
        previous = parent if parent is not None else (row[1] if row else None)
        identifier = sha256([run_id, revision, scope_key, status, restored_from])[:20]
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record = {
            "id": identifier, "run_id": run_id, "revision": revision, "scope": list(scope),
            "status": status, "parent": previous, "created_at": created,
            "restored_from": restored_from, **payload,
        }
        connection.execute(
            "INSERT INTO volumes (id, run_id, revision, scope, status, payload, parent, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (identifier, run_id, revision, scope_key, status, canonical(record), previous, created),
        )
        return {**record, "reused": False}

    def restore_volume(self, run_id, volume_id):
        """签核中断后恢复旧版：以新轮次重新落旧版内容，旧记录保留。"""
        old = self.volume(run_id, volume_id)
        payload = {key: value for key, value in old.items() if key not in {
            "id", "run_id", "revision", "parent", "created_at", "restored_from", "reused"}}
        with closing(self.connect()) as connection:
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            try:
                latest = connection.execute(
                    "SELECT id FROM volumes WHERE run_id = ? ORDER BY revision DESC LIMIT 1", (run_id,)
                ).fetchone()
                result = self._insert_volume(connection, run_id, old["scope"], old["status"], payload,
                                             latest[0] if latest else None, restored_from=old["id"])
                connection.execute("COMMIT")
                return result
            except Exception:
                connection.execute("ROLLBACK")
                raise
