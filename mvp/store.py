import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from mvp.knowledge import ROOT


class StaleRevision(Exception):
    pass


class Store:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / "var/mvp/analyses.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, status TEXT NOT NULL, request TEXT NOT NULL, result TEXT, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS chats (analysis_id TEXT NOT NULL, revision INTEGER NOT NULL, turn INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (analysis_id, revision, turn))")
            db.execute("UPDATE analyses SET status='failed', error='서버가 재시작되어 분석이 중단됐습니다. 새 분석을 실행해주세요.' WHERE status IN ('queued','running')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, id, request):
        with self.connect() as db:
            db.execute("INSERT INTO analyses(id,revision,status,request) VALUES (?,1,'queued',?)", (id, json.dumps(request, ensure_ascii=False)))

    def get(self, id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM analyses WHERE id=?", (id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["request"] = json.loads(item["request"])
        item["result"] = json.loads(item["result"]) if item["result"] else None
        return item

    def list(self):
        with self.connect() as db:
            rows = db.execute("SELECT id,revision,status,created_at,request FROM analyses ORDER BY created_at DESC, rowid DESC LIMIT 50").fetchall()
        return [{"analysis_id": r["id"], "analysis_revision": r["revision"], "status": r["status"], "created_at": r["created_at"], "title": json.loads(r["request"])["title"]} for r in rows]

    def start(self, id):
        with self.connect() as db:
            return db.execute("UPDATE analyses SET status='running' WHERE id=? AND status='queued'", (id,)).rowcount == 1

    def finish(self, id, result=None, error=None):
        with self.connect() as db:
            db.execute("UPDATE analyses SET status=?,result=?,error=? WHERE id=? AND status='running'", (result["status"] if result else "failed", json.dumps(result, ensure_ascii=False) if result else None, error, id))

    def revise(self, id, revision, request, result):
        with self.connect() as db:
            count = db.execute("UPDATE analyses SET revision=?,status=?,request=?,result=? WHERE id=? AND revision=? AND status IN ('completed','awaiting_input')",
                               (revision + 1, result["status"], json.dumps(request, ensure_ascii=False), json.dumps(result, ensure_ascii=False), id, revision)).rowcount
            if count != 1:
                raise StaleRevision()

    def delete(self, id):
        with self.connect() as db:
            db.execute("DELETE FROM chats WHERE analysis_id=?", (id,))
            return db.execute("DELETE FROM analyses WHERE id=?", (id,)).rowcount == 1

    def chat(self, id, revision):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM chats WHERE analysis_id=? AND revision=? ORDER BY turn", (id, revision)).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def append_chat(self, id, revision, previous_count, turn):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT revision,status FROM analyses WHERE id=?", (id,)).fetchone()
            count = db.execute("SELECT COUNT(*) FROM chats WHERE analysis_id=? AND revision=?", (id, revision)).fetchone()[0]
            if not current or current["revision"] != revision or current["status"] not in {"completed", "awaiting_input"} or count != previous_count:
                raise StaleRevision()
            db.execute("INSERT INTO chats VALUES (?,?,?,?)", (id, revision, count+1, json.dumps(turn, ensure_ascii=False)))
