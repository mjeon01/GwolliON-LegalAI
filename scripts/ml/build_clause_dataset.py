#!/usr/bin/env python3
"""Build the clause-type dataset from AI Hub employment contracts.

Training archive -> train/dev split by document; Validation archive -> locked test.
Test documents whose text also appears in Training are excluded.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.clause_labels import MIN_EXAMPLES, normalize_labels, normalize_text
from scripts.inspect_downloaded_data import json_members, read_json

FORMS = {"근로(고용)계약서", "아르바이트계약서", "연봉계약서"}
OUT = ROOT / "var/ml/clause"


def documents(split, data_root):
    for path in sorted((data_root / split / "02.라벨링데이터").glob("*고용계약*.zip")):
        with zipfile.ZipFile(path) as archive:
            for member in json_members(archive):
                document = read_json(archive, member)["document"]
                info = document["metadata"]["file_info"]
                if info["document_category"]["detail_category"] not in FORMS:
                    continue
                rows, title = [], ""
                for section in document.get("sections", []):
                    content = section.get("content") or {}
                    text = normalize_text(content.get("description", ""))
                    if not text:
                        continue
                    if (section.get("format") or {}).get("is_article_title"):
                        title = text
                    rows.append({"text": text, "title": title, "labels": normalize_labels(content.get("content_labels"))})
                if rows:
                    body = "\n".join(r["text"] for r in rows)
                    yield {"doc_id": info["document_name"], "form": info["document_category"]["detail_category"],
                           "hash": hashlib.sha256(body.encode()).hexdigest(), "rows": rows}


def build(data_root, out=OUT, seed=13, dev_share=0.1, min_examples=MIN_EXAMPLES):
    training = list(documents("Training", data_root))
    validation = list(documents("Validation", data_root))
    # Identical documents stay together so dev never sees a copy of a train document.
    groups = sorted({d["hash"] for d in training})
    random.Random(seed).shuffle(groups)
    dev_hashes = set(groups[:max(1, round(len(groups) * dev_share))])
    train_docs = [d for d in training if d["hash"] not in dev_hashes]
    dev_docs = [d for d in training if d["hash"] in dev_hashes]
    seen = {d["hash"] for d in training}
    test_docs = [d for d in validation if d["hash"] not in seen]

    counts = Counter(label for d in train_docs for r in d["rows"] for label in r["labels"])
    labels = sorted(label for label, n in counts.items() if n >= min_examples)
    keep = set(labels)

    def records(docs):
        return [{"doc_id": d["doc_id"], "form": d["form"], "text": r["text"], "title": r["title"],
                 "labels": [label for label in r["labels"] if label in keep]} for d in docs for r in d["rows"]]

    splits = {"train": records(train_docs), "dev": records(dev_docs), "test": records(test_docs)}
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in splits.items():
        with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    card = {"source": "AI Hub 계약법률문서 (인사_고용_노무/고용계약), 근로(고용)·아르바이트·연봉계약서",
            "documents": {"train": len(train_docs), "dev": len(dev_docs), "test": len(test_docs),
                          "test_excluded_as_training_duplicate": len(validation) - len(test_docs)},
            "sentences": {k: len(v) for k, v in splits.items()},
            "sentences_without_type": {k: sum(not r["labels"] for r in v) for k, v in splits.items()},
            "labels": {label: {k: sum(label in r["labels"] for r in v) for k, v in splits.items()} for label in labels},
            "dropped_rare_labels": {label: n for label, n in counts.items() if n < min_examples},
            "seed": seed}
    (out / "data_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return card


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data/계약법률문서")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    card = build(args.data, args.out)
    print(json.dumps({k: card[k] for k in ("documents", "sentences", "sentences_without_type")}, ensure_ascii=False))
    print(len(card["labels"]), "labels")
