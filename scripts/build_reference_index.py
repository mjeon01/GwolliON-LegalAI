#!/usr/bin/env python3
"""Index every JSON member locally and keep Validation out of runtime retrieval."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mvp.corpus import DEFAULT_DB, normalize_record
from scripts.inspect_downloaded_data import json_members, read_json


def build(data_root, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".building.sqlite3")
    temporary.unlink(missing_ok=True)
    counts, archives, errors = Counter(), [], []
    with closing(sqlite3.connect(temporary)) as db:
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("CREATE TABLE records(id INTEGER PRIMARY KEY, source_id TEXT UNIQUE, split TEXT, kind TEXT, title TEXT, body TEXT, metadata TEXT, archive TEXT, member TEXT, content_hash TEXT)")
        for path in sorted(data_root.rglob("*.zip")):
            archive_name = str(path.relative_to(data_root))
            split = "Validation" if "Validation" in path.parts else "Training" if "Training" in path.parts else "Unknown"
            processed = 0
            with zipfile.ZipFile(path) as archive:
                for item in json_members(archive):
                    try:
                        obj = read_json(archive, item)  # Reading all entries also checks their CRC.
                        kind, title, body, metadata = normalize_record(obj, archive_name)
                        digest = hashlib.sha256(body.encode()).hexdigest()
                        source_id = "data-" + hashlib.sha256((archive_name + "\0" + item.filename).encode()).hexdigest()[:24]
                        db.execute("INSERT INTO records(source_id,split,kind,title,body,metadata,archive,member,content_hash) VALUES(?,?,?,?,?,?,?,?,?)", (source_id, split, kind, title, body, json.dumps(metadata, ensure_ascii=False), archive_name, item.filename, digest))
                        counts[f"{split}/{kind}"] += 1
                        counts["empty_text"] += not bool(body.strip())
                        processed += 1
                    except (ValueError, KeyError, UnicodeError, zipfile.BadZipFile, TypeError) as exc:
                        errors.append({"archive": archive_name, "member": item.filename, "error_type": type(exc).__name__})
            db.commit()
            archives.append({"archive": archive_name, "records": processed})
            print(json.dumps({"archives_completed": len(archives), "records": sum(a["records"] for a in archives)}, ensure_ascii=False), flush=True)
        db.execute("CREATE INDEX records_split_kind ON records(split,kind)")
        db.execute("CREATE INDEX records_hash ON records(content_hash,split)")
        # Trigram LIKE search supports Korean substrings without language-specific tokenization.
        db.execute("CREATE VIRTUAL TABLE records_fts USING fts5(title,body,content='records',content_rowid='id',tokenize='trigram',detail='none')")
        db.execute("INSERT INTO records_fts(records_fts) VALUES('rebuild')")
        overlap = db.execute("SELECT COUNT(DISTINCT a.content_hash) FROM records a JOIN records b ON a.content_hash=b.content_hash WHERE a.split='Training' AND b.split='Validation' AND a.body<>''").fetchone()[0]
        db.commit()
        manifest = {"status": "ready" if not errors else "partial", "built_at": datetime.now(timezone.utc).isoformat(),
                    "records": sum(a["records"] for a in archives), "archives": archives, "counts": dict(counts), "errors": errors,
                    "exact_text_hash_overlap": overlap, "runtime_split": "Training", "evaluation_split": "Validation",
                    "limitations": ["항목 라벨은 불리함·위법의 정답이 아님", "검증 데이터의 동일 원문 해시를 보고하며 유사 양식 중복은 별도 검수 필요", "자료의 법령·판례는 최신성 및 출처 재확인 전 참고 자료"]}
    if errors:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"{len(errors)} JSON entries failed; previous index preserved")
    temporary.replace(target)
    target.with_name("manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    report = build(args.data_dir, args.output)
    print(json.dumps({k: report[k] for k in ("status", "records", "counts", "exact_text_hash_overlap")}, ensure_ascii=False))
