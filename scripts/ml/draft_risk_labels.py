#!/usr/bin/env python3
"""Draft clause-level worker-burden labels for human review.

Writes var/ml/risk/review.csv. Fill the gold_risk column (risk ids separated by "," or "none"),
then run scripts/ml/evaluate_risk.py. Drafts come from the systems being evaluated: review them,
do not copy them, or the evaluation measures nothing.
"""
import argparse
import csv
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.clause_labels import INHERENT_RISK, RISK_LABELS, RISK_TYPES
from backend.clause_model import ClauseModel, rows_from_blocks
from backend.extraction import blocks_from_text
from scripts.ml.common import DATA, load_split
from scripts.ml.risk import combined, rule_hits

OUT = ROOT / "var/ml/risk"
FIELDS = ["id", "source", "doc", "title", "text", "model_types", "model_types_v1", "rule_hits", "draft_risk", "gold_risk", "note"]
GUIDE = """# 위험 조항 검수 기준

`review.csv`의 `gold_risk` 열만 채웁니다. 근로자 입장에서 그 문장(조항)만 보고 판단합니다.

| id | 표시할 때 |
| --- | --- |
| penalty | 퇴사·불이행 시 위약금·손해배상액을 미리 정함 (실제 손해 배상 원칙만 적은 문장은 none) |
| included_allowance | 연장·야간·휴일 수당을 임금에 포함하거나 별도 지급하지 않는다고 함 |
| wage_deduction | 손해·벌금 등을 임금에서 공제·차감함 |
| leave_waiver | 연차·휴가를 포기하게 하거나 부여하지 않음 |
| noncompete | 퇴직 후 경업·겸직·동종업계 취업을 제한함 |
| unpaid_trial | 수습·교육 기간을 무급으로 하거나 임금을 정하지 않음 |
| unilateral_change | 사용자가 근무지·업무·근로조건을 일방적으로 바꿀 수 있음 |
| none | 위 어느 것도 아님 (제목·서명·일반 조항 포함) |

- 여러 개면 쉼표로 구분: `penalty,wage_deduction`
- 판단이 어려우면 비워두고 `note`에 이유를 적습니다. 빈 행은 평가에서 제외됩니다.
- `draft_risk`는 평가 대상 시스템의 출력입니다. 그대로 복사하지 말고 문장을 읽고 판단하세요.
"""


def best_model(data):
    for name in ("v2", "v1", "baseline"):
        if (Path(data) / name / "meta.json").is_file():
            return ClauseModel(Path(data) / name)
    raise SystemExit("학습된 조항 분류 모델이 없습니다. scripts/ml/train_clause.py를 먼저 실행하세요.")


def collect(data, seed=13, extra_negatives=30, split="test"):
    """Sample contracts plus AI Hub sentences of the split. The dev set leaves the samples out: they are already
    in the test review, and the burden filter was written while reading that review, so dev is the unseen check."""
    rows = []
    files = sorted((ROOT / "samples").glob("employment-*.txt")) + sorted((ROOT / "tests/fixtures/samples").glob("employment-*.txt"))
    for path in files if split == "test" else []:
        for row in rows_from_blocks(blocks_from_text(path.read_text(encoding="utf-8"))):
            if len(row["text"]) >= 12:
                rows.append({"source": path.parent.name, "doc": path.stem, **row})
    pool = load_split(split, data)
    related = [r for r in pool if any(label in INHERENT_RISK or label == "수습 기간" for label in r["labels"])]
    others = [r for r in pool if r not in related and len(r["text"]) >= 12]
    random.Random(seed).shuffle(others)
    for r in related + others[:extra_negatives]:
        rows.append({"source": f"aihub_{split}", "doc": r["doc_id"], "title": r["title"], "text": r["text"]})
    return rows


def draft(data=DATA, out=OUT, split="test"):
    model = best_model(data)
    rows = collect(data, split=split)
    types = model.predict(rows)
    # v1 types are kept alongside so one human review scores both "v1 + rules" and "default model + rules".
    v1_path = Path(data) / "v1"
    v1_types = ClauseModel(v1_path).predict(rows) if model.meta.get("name") != "v1" and (v1_path / "meta.json").is_file() else types
    out.mkdir(parents=True, exist_ok=True)
    path = out / "review.csv"
    if path.exists() and any(r.get("gold_risk") for r in csv.DictReader(open(path, encoding="utf-8-sig"))):
        raise SystemExit(f"{path}에 검수한 값이 있습니다. 덮어쓰지 않습니다. 파일을 옮긴 뒤 다시 실행하세요.")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: opens correctly in Excel
        writer = csv.DictWriter(f, FIELDS)
        writer.writeheader()
        for i, (row, labels, labels_v1) in enumerate(zip(rows, types, v1_types), 1):
            writer.writerow({"id": f"R{i:03d}", "source": row["source"], "doc": row["doc"], "title": row["title"], "text": row["text"],
                             "model_types": ",".join(labels), "model_types_v1": ",".join(labels_v1), "rule_hits": ",".join(rule_hits(row["text"])),
                             "draft_risk": ",".join(combined(row["text"], labels)) or "none", "gold_risk": "", "note": ""})
    (out / "README.md").write_text(GUIDE, encoding="utf-8")
    return path, len(rows), model.meta.get("name")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--split", choices=["test", "dev"], default="test",
                        help="dev: a fresh review set of AI Hub dev sentences, written to var/ml/risk-dev")
    args = parser.parse_args()
    path, count, name = draft(args.data, OUT if args.split == "test" else ROOT / "var/ml/risk-dev", args.split)
    print(f"{count} clauses -> {path.relative_to(ROOT)} (model: {name}); labels: {', '.join(RISK_LABELS)}, none")
