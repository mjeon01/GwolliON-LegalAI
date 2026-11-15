"""Splits and multi-label metrics shared by the clause training and evaluation scripts."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "var/ml/clause"


def load_split(name, data=DATA):
    with open(Path(data) / f"{name}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def load_labels(data=DATA):
    return json.loads((Path(data) / "labels.json").read_text(encoding="utf-8"))


def binarize(rows, labels):
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in rows]
    for row, out in zip(rows, matrix):
        for label in row["labels"]:
            if label in index:
                out[index[label]] = 1
    return matrix


def prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn}


def metrics(gold, predicted, labels):
    """gold/predicted: lists of label lists. Micro over all (sentence, label) pairs, macro over labels with support."""
    per_label = {}
    for label in labels:
        tp = sum(label in g and label in p for g, p in zip(gold, predicted))
        fp = sum(label not in g and label in p for g, p in zip(gold, predicted))
        fn = sum(label in g and label not in p for g, p in zip(gold, predicted))
        per_label[label] = {**prf(tp, fp, fn), "support": tp + fn}
    micro = prf(*(sum(v[k] for v in per_label.values()) for k in ("tp", "fp", "fn")))
    supported = [v for v in per_label.values() if v["support"]]
    macro = {k: round(sum(v[k] for v in supported) / len(supported), 4) if supported else 0.0 for k in ("precision", "recall", "f1")}
    exact = sum(set(g) == set(p) for g, p in zip(gold, predicted)) / len(gold) if gold else 0.0
    return {"micro": micro, "macro": macro, "exact_match": round(exact, 4), "per_label": per_label, "sentences": len(gold)}


THRESHOLD_FLOOR = 0.5
THRESHOLD_MIN_SUPPORT = 5
THRESHOLD_POLICY = f"라벨별 dev F1 최대, 하한 {THRESHOLD_FLOOR}, dev 정답 {THRESHOLD_MIN_SUPPORT}건 미만 라벨은 0.5 고정"


def tune_thresholds(probabilities, gold, labels, grid=None):
    """Per-label threshold maximizing that label's dev F1 (ties keep 0.5).

    Thresholds never go below 0.5: pos_weight already pushes rare labels' probabilities up, and lowering the
    threshold on a small dev split as well doubled false alarms on test. Labels with too few dev positives
    keep 0.5 because their dev F1 is too noisy to tune on.
    """
    grid = grid or [round(0.05 * i, 2) for i in range(int(THRESHOLD_FLOOR * 20), 19)]
    thresholds = []
    for j, label in enumerate(labels):
        best, best_f1 = 0.5, -1.0
        if sum(label in g for g in gold) < THRESHOLD_MIN_SUPPORT:
            thresholds.append(best)
            continue
        for t in sorted(grid, key=lambda x: abs(x - 0.5)):
            tp = sum(p[j] >= t and label in g for p, g in zip(probabilities, gold))
            fp = sum(p[j] >= t and label not in g for p, g in zip(probabilities, gold))
            fn = sum(p[j] < t and label in g for p, g in zip(probabilities, gold))
            f1 = prf(tp, fp, fn)["f1"]
            if f1 > best_f1:
                best, best_f1 = t, f1
        thresholds.append(best)
    return thresholds
