"""Local reference retrieval. Dataset annotations are examples, never legal verdicts."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "var/corpus/reference.sqlite3"


def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def normalize_record(obj, archive):
    """Retain original text; ignore executable-looking instruction fields in QA."""
    document = obj.get("document")
    metadata = {}
    if isinstance(document, dict):
        if "sub_documents" in document:
            title = str(document.get("title") or "계약서 원문")
            body = "\n".join(str(c["text"]) for s in document["sub_documents"]
                             for c in s.get("contents", []) if isinstance(c, dict) and c.get("text"))
            kind = "contract"
            metadata = {"doc_type": document.get("doc_type")}
        else:
            info = document.get("metadata", {}).get("file_info", {})
            title = str(info.get("document_name") or "계약서 항목 라벨")
            sections = document.get("sections", [])
            body = "\n".join(str(s.get("content", {}).get("description", "")) for s in sections)
            kind = "contract_label"
            metadata = {"category": info.get("document_category"),
                        "labels": sorted({str(t) for s in sections for t in s.get("content", {}).get("content_labels", [])})}
    else:
        info = obj.get("info", obj)
        task = obj.get("taskinfo")
        title = str(info.get("statute_name") or info.get("title") or info.get("casenames") or info.get("doc_id") or "법률 참고 자료")
        metadata = {k: info.get(k) for k in ("doc_id", "announce_date", "decision_date", "response_date", "effective_date", "normalized_court", "casetype", "response_institute") if info.get(k)}
        if isinstance(task, dict):
            # These are recorded examples, not instructions for our model.
            body = "\n".join(strings(task.get("sentences")) + strings(task.get("input")) + strings(task.get("output")))
            kind = "qa_example" if "질의응답" in archive else "summary_example"
        else:
            body = "\n".join(strings(obj.get("sentences")))
            kind = next((kind for word, kind in (("판결문", "precedent_reference"), ("유권해석", "interpretation_reference"), ("심결례", "decision_reference"), ("법령", "law_reference")) if word in archive), "reference")
    return kind, title, body, metadata


class Corpus:
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_DB)

    def status(self):
        manifest = self.path.with_name("manifest.json")
        if not self.path.exists() or not manifest.exists():
            return {"status": "not_indexed", "records": 0}
        return json.loads(manifest.read_text(encoding="utf-8"))

    def search(self, terms, limit=3, kinds=None):
        if not self.path.exists():
            return []
        terms = list(dict.fromkeys(t for t in terms if isinstance(t, str) and 3 <= len(t) <= 40))[:6]
        if not terms:
            return []
        candidates = {}
        with closing(sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            for term in terms:
                conditions = "r.split='Training' AND NOT EXISTS (SELECT 1 FROM records v WHERE v.split='Validation' AND v.content_hash=r.content_hash)"
                args = ["%" + term.replace("%", "\\%").replace("_", "\\_") + "%"]
                if kinds:
                    conditions += " AND r.kind IN (" + ",".join("?" for _ in kinds) + ")"
                    args.extend(kinds)
                rows = db.execute(f"SELECT r.* FROM records_fts f JOIN records r ON r.id=f.rowid WHERE f.body LIKE ? ESCAPE '\\' AND {conditions} LIMIT 80", args).fetchall()
                for row in rows:
                    candidates[row["source_id"]] = dict(row)
        ranked = sorted(candidates.values(), key=lambda r: (sum(min(r["body"].count(t), 4) + 4 * (t in r["title"]) for t in terms), -len(r["body"])), reverse=True)
        result, seen = [], set()
        for row in ranked:
            if row["content_hash"] in seen:
                continue
            seen.add(row["content_hash"])
            # A contiguous original excerpt, never a generated summary.
            position = min((row["body"].find(t) for t in terms if t in row["body"]), default=0)
            start = max(0, position - 180)
            text = row["body"][start:start + 900]
            result.append({"source_id": row["source_id"], "kind": "dataset", "dataset_kind": row["kind"], "title": row["title"], "text": text,
                           "archive": row["archive"], "member": row["member"], "split": row["split"],
                           "excerpt_start": start, "content_hash": row["content_hash"], "metadata": json.loads(row["metadata"]),
                           "snapshot_id": row["content_hash"][:16], "official_url": "", "checked_at": "",
                           "version_applicable": False, "version_note": "제공된 데이터의 원문 발췌입니다. 현재 법률 또는 이 사건의 판단 근거로 검증된 자료가 아닙니다."})
            if len(result) >= limit:
                break
        return result
