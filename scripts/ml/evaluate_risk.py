#!/usr/bin/env python3
"""Score worker-burden detection against the reviewed var/ml/risk/review.csv.

Compares (a) the review rules alone with (b) default clause model + rules and, when the CSV has\nmodel_types_v1, (c) v1 + rules, at clause level.
Rows with an empty gold_risk are excluded and counted.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.clause_labels import RISK_LABELS
from scripts.ml.common import metrics
from scripts.ml.risk import combined, rule_hits

OUT = ROOT / "var/ml/risk"


def parse(value):
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    unknown = [v for v in items if v not in RISK_LABELS and v != "none"]
    if unknown:
        raise ValueError(f"알 수 없는 위험 id: {unknown}")
    return [v for v in items if v != "none"]


def score(rows, extra_models=None):
    """extra_models: {name: ClauseModel}; their clause types are predicted here and scored as "<name>_and_rules"."""
    reviewed = [r for r in rows if (r.get("gold_risk") or "").strip()]
    gold = [parse(r["gold_risk"]) for r in reviewed]
    systems = {"rules": [rule_hits(r["text"]) for r in reviewed],
               "model_and_rules": [combined(r["text"], [t for t in r["model_types"].split(",") if t]) for r in reviewed]}
    if reviewed and "model_types_v1" in reviewed[0]:
        systems["v1_and_rules"] = [combined(r["text"], [t for t in r["model_types_v1"].split(",") if t]) for r in reviewed]
    for name, model in (extra_models or {}).items():
        types = model.predict([{"text": r["text"], "title": r.get("title", "")} for r in reviewed])
        systems[f"{name}_and_rules"] = [combined(r["text"], labels) for r, labels in zip(reviewed, types)]
    normal = [i for i, g in enumerate(gold) if not g]
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "reviewed": len(reviewed), "skipped_unreviewed": len(rows) - len(reviewed),
              "risky_clauses": len(reviewed) - len(normal), "normal_clauses": len(normal), "systems": {}}
    report["by_source"] = {}
    for source in sorted({r.get("source", "") for r in reviewed} - {""}):
        index = [i for i, r in enumerate(reviewed) if r.get("source") == source]
        normal_here = [i for i in index if not gold[i]]
        report["by_source"][source] = {"reviewed": len(index), "risky_clauses": len(index) - len(normal_here), "systems": {
            name: {"micro": metrics([gold[i] for i in index], [predicted[i] for i in index], RISK_LABELS)["micro"],
                   "false_alarm_rate": round(sum(bool(predicted[i]) for i in normal_here) / len(normal_here), 4) if normal_here else 0.0}
            for name, predicted in systems.items()}}
    for name, predicted in systems.items():
        result = metrics(gold, predicted, RISK_LABELS)
        result["false_alarm_rate"] = round(sum(bool(predicted[i]) for i in normal) / len(normal), 4) if normal else 0.0
        result["clause_detection"] = metrics([["risk"] if g else [] for g in gold], [["risk"] if p else [] for p in predicted], ["risk"])["micro"]
        report["systems"][name] = result
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=OUT / "review.csv")
    parser.add_argument("--with-model", nargs="*", default=[], metavar="NAME",
                        help="also score these saved clause models (e.g. baseline) from var/ml/clause/NAME")
    args = parser.parse_args()
    rows = list(csv.DictReader(open(args.csv, encoding="utf-8-sig")))
    from backend.clause_model import ClauseModel
    from scripts.ml.common import DATA
    report = score(rows, {name: ClauseModel(DATA / name) for name in args.with_model})
    (args.csv.parent / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"reviewed {report['reviewed']} (skipped {report['skipped_unreviewed']})")
    for name, r in report["systems"].items():
        print(f"{name:16} P {r['micro']['precision']:.3f} R {r['micro']['recall']:.3f} F1 {r['micro']['f1']:.3f} false-alarm {r['false_alarm_rate']:.3f}")
    for source, part in report["by_source"].items():
        print(f"[{source}] reviewed {part['reviewed']}, risky {part['risky_clauses']}")
        for name, r in part["systems"].items():
            print(f"  {name:16} P {r['micro']['precision']:.3f} R {r['micro']['recall']:.3f} F1 {r['micro']['f1']:.3f} false-alarm {r['false_alarm_rate']:.3f}")
