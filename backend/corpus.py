"""Local reference retrieval. Dataset annotations are examples, never legal verdicts."""
import hashlib
from contextlib import closing
from functools import lru_cache
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


def matching_excerpt(body, terms, size=1000):
    """Choose a contiguous original passage covering the most query terms."""
    starts = {0}
    for term in terms:
        position = -1
        for _ in range(20):
            position = body.find(term, position + 1)
            if position < 0:
                break
            starts.add(max(0, position - 180))
    start = max(sorted(starts), key=lambda offset: (
        sum(term in body[offset:offset + size] for term in terms),
        sum(min(body[offset:offset + size].count(term), 3) for term in terms),
        -offset,
    ))
    return start, body[start:start + size]


class Corpus:
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_DB)

    def status(self):
        manifest = self.path.with_name("manifest.json")
        if not self.path.exists() or not manifest.exists():
            return {"status": "not_indexed", "records": 0}
        return json.loads(manifest.read_text(encoding="utf-8"))

    def search(self, terms, limit=3, kinds=None, diverse=False):
        if not self.path.exists():
            return []
        terms = list(dict.fromkeys(t for t in terms if isinstance(t, str) and 3 <= len(t) <= 40))[:12]
        if not terms:
            return []
        candidates = {}
        with closing(sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            for term in terms:
                conditions = "r.split='Training' AND NOT EXISTS (SELECT 1 FROM records v WHERE v.split='Validation' AND v.content_hash=r.content_hash)"
                # ESCAPE disables FTS5's trigram LIKE index. Keep indexed LIKE
                # and verify the literal substring separately (including %/_).
                args = ['%' + term + '%', term]
                if kinds:
                    conditions += " AND r.kind IN (" + ",".join("?" for _ in kinds) + ")"
                    args.extend(kinds)
                # Drive the join from text hits, not every Training record.
                rows = db.execute(f"SELECT r.* FROM records_fts f CROSS JOIN records r ON r.id=f.rowid WHERE f.body LIKE ? AND instr(r.body, ?) > 0 AND {conditions} LIMIT 80", args).fetchall()
                for row in rows:
                    candidates[row["source_id"]] = dict(row)
        ranked = sorted(candidates.values(), key=lambda r: (sum(min(r["body"].count(t), 4) + 4 * (t in r["title"]) for t in terms), -len(r["body"])), reverse=True)
        if diverse:
            representatives, remaining, kinds_seen = [], [], set()
            for row in ranked:
                (remaining if row['kind'] in kinds_seen else representatives).append(row)
                kinds_seen.add(row['kind'])
            ranked = representatives + remaining
        result, seen = [], set()
        for row in ranked:
            if row["content_hash"] in seen:
                continue
            seen.add(row["content_hash"])
            # A contiguous original excerpt, never a generated summary.
            start, text = matching_excerpt(row['body'], terms)
            result.append({"source_id": row["source_id"], "kind": "dataset", "dataset_kind": row["kind"], "title": row["title"], "text": text,
                           "archive": row["archive"], "member": row["member"], "split": row["split"],
                           "excerpt_start": start, "content_hash": row["content_hash"], "metadata": json.loads(row["metadata"]),
                           "snapshot_id": row["content_hash"][:16], "official_url": "", "checked_at": "",
                           "version_applicable": False, "version_note": "제공된 데이터의 원문 발췌입니다. 현재 법률 또는 이 사건의 판단 근거로 검증된 자료가 아닙니다."})
            if len(result) >= limit:
                break
        return result


EMPLOYMENT_FORMS = ("근로(고용)계약서", "아르바이트계약서", "연봉계약서")


@lru_cache(maxsize=4)
def typical_clauses(detail_category="근로(고용)계약서", path=None):
    """How often each clause label appears in the AI Hub contracts of one form (Training split only)."""
    db_path = Path(path or DEFAULT_DB)
    if not db_path.exists():
        return {"status": "not_indexed", "contracts": 0, "clauses": []}
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)) as db:
        rows = db.execute("SELECT metadata FROM records WHERE kind='contract_label' AND split='Training' "
                          "AND json_extract(metadata,'$.category.detail_category')=?", (detail_category,)).fetchall()
    counts = {}
    for (metadata,) in rows:
        for label in set(json.loads(metadata).get("labels", [])):
            if label != "기타":
                counts[label] = counts.get(label, 0) + 1
    clauses = sorted(({"label": k, "share": round(v / len(rows), 2)} for k, v in counts.items()), key=lambda c: -c["share"])
    return {"status": "ready" if rows else "empty", "contracts": len(rows), "clauses": clauses[:40]}


def similar_clauses(terms, path=None, limit=3):
    """Excerpts from real employment contracts that contain the terms, for wording comparison."""
    db_path = Path(path or DEFAULT_DB)
    terms = [t for t in dict.fromkeys(terms) if isinstance(t, str) and 2 <= len(t) <= 30][:4]
    if not db_path.exists() or not terms:
        return []
    placeholders = ",".join("?" for _ in EMPLOYMENT_FORMS)
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(f"SELECT c.source_id, c.title, c.body, c.content_hash FROM records c JOIN records l ON l.member=c.member AND l.kind='contract_label' "
                          f"WHERE c.kind='contract' AND c.split='Training' AND json_extract(l.metadata,'$.category.detail_category') IN ({placeholders}) "
                          + " ".join("AND instr(c.body, ?) > 0" for _ in terms) + " LIMIT 40",
                          (*EMPLOYMENT_FORMS, *terms)).fetchall()
    result = []
    for row in rows[:limit]:
        start, text = matching_excerpt(row["body"], terms)
        result.append({"source_id": row["source_id"], "kind": "dataset", "dataset_kind": "contract", "title": row["title"], "text": text,
                       "excerpt_start": start, "snapshot_id": row["content_hash"][:16], "version_applicable": False,
                       "version_note": "AI Hub 계약서 데이터의 실제 문구 발췌입니다. 비교용이며 법적 기준이 아닙니다."})
    return result
