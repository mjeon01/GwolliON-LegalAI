#!/usr/bin/env python3
"""Re-tune per-label thresholds of a saved transformer checkpoint on dev, without retraining.

Uses the current policy in scripts/ml/common.py (tune_thresholds). Only dev is read; test stays locked.
The previous thresholds and dev scores are kept in meta.json under "previous".
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.clause_model import ClauseModel
from scripts.ml.common import DATA, THRESHOLD_POLICY, load_split, metrics, tune_thresholds

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", nargs="?", default="v2")
    parser.add_argument("--data", type=Path, default=DATA)
    args = parser.parse_args()
    path = args.data / args.model
    model = ClauseModel(path)
    if model.meta["kind"] != "transformer":
        sys.exit(f"{args.model} is not a transformer checkpoint")
    dev = load_split("dev", args.data)
    gold = [r["labels"] for r in dev]
    probs = model.probabilities(dev)
    thresholds = tune_thresholds(probs, gold, model.labels)
    predicted = [[l for l, p, t in zip(model.labels, ps, thresholds) if p >= t] for ps in probs]
    dev_metrics = metrics(gold, predicted, model.labels)

    meta = model.meta
    meta.setdefault("previous", []).append({"thresholds": meta["thresholds"], "dev": meta["dev"],
                                            "threshold_policy": meta.get("threshold_policy", "라벨별 dev F1 최대, 0.10-0.90")})
    meta.update(thresholds=thresholds, dev={"micro": dev_metrics["micro"], "macro": dev_metrics["macro"]},
                threshold_policy=THRESHOLD_POLICY, retuned_at=datetime.now(timezone.utc).isoformat())
    (path / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    before = meta["previous"][-1]["dev"]["micro"]
    print(json.dumps({"before": before, "after": dev_metrics["micro"], "macro_after": dev_metrics["macro"]}, ensure_ascii=False))
    changed = [(l, t) for l, t in zip(model.labels, thresholds) if t != 0.5]
    print("thresholds != 0.5:", ", ".join(f"{l}={t}" for l, t in changed) or "none")
