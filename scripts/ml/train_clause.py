#!/usr/bin/env python3
"""Train the clause-type classifiers.

  baseline  char n-gram TF-IDF + one-vs-rest logistic regression (기존 모델)
  v1        klue/roberta-large fine-tuned on the sentence alone (1차 학습)
  v2        v1 + article heading context, rare-label pos_weight, dev-tuned per-label thresholds (2차 학습)

The checkpoint with the best dev micro-F1 is kept. The test split is never read here.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.clause_labels import model_input
from scripts.ml.common import DATA, THRESHOLD_POLICY, binarize, load_labels, load_split, metrics, tune_thresholds

BASE_MODEL = "klue/roberta-large"
# Train from the local Hugging Face cache; no network access or login is needed once the model is downloaded.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
CONFIGS = {
    "v1": {"with_context": False, "pos_weight": False, "tune_thresholds": False, "max_length": 128},
    "v2": {"with_context": True, "pos_weight": True, "tune_thresholds": True, "max_length": 160},
}


def save_meta(out, **meta):
    out.mkdir(parents=True, exist_ok=True)
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def train_baseline(data, out):
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.pipeline import make_pipeline

    labels, train, dev = load_labels(data), load_split("train", data), load_split("dev", data)
    started = time.monotonic()
    pipeline = make_pipeline(TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=2, sublinear_tf=True),
                             OneVsRestClassifier(LogisticRegression(C=4.0, max_iter=2000)))
    pipeline.fit([r["text"] for r in train], binarize(train, labels))
    seconds = time.monotonic() - started
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, out / "model.joblib")
    predicted = [[l for l, p in zip(labels, probs) if p >= 0.5] for probs in pipeline.predict_proba([r["text"] for r in dev])]
    dev_metrics = metrics([r["labels"] for r in dev], predicted, labels)
    save_meta(out, name="baseline", kind="tfidf", labels=labels, thresholds=[0.5] * len(labels), with_context=False,
              description="char 2-4gram TF-IDF + one-vs-rest logistic regression", train_seconds=round(seconds, 1),
              dev={"micro": dev_metrics["micro"], "macro": dev_metrics["macro"]}, trained_at=datetime.now(timezone.utc).isoformat())
    return dev_metrics


def train_transformer(name, data, out, epochs=3, batch_size=16, lr=2e-5, seed=13, limit=None):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    config = CONFIGS[name]
    random.seed(seed)
    torch.manual_seed(seed)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    labels, train, dev = load_labels(data), load_split("train", data), load_split("dev", data)
    if limit:
        train, dev = train[:limit], dev[:max(8, limit // 8)]
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(labels), problem_type="multi_label_classification",
        id2label=dict(enumerate(labels)), label2id={l: i for i, l in enumerate(labels)}).to(device)
    targets = torch.tensor(binarize(train, labels), dtype=torch.float)
    if config["pos_weight"]:
        positives = targets.sum(0).clamp(min=1)
        # sqrt of the negative/positive ratio, capped: rare clause types are not drowned out by common ones.
        weight = ((len(train) - positives) / positives).sqrt().clamp(1, 10)
    else:
        weight = torch.ones(len(labels))
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=weight.to(device))
    texts = [model_input(r["text"], r["title"], config["with_context"]) for r in train]
    dev_texts = [model_input(r["text"], r["title"], config["with_context"]) for r in dev]
    steps = math.ceil(len(train) / batch_size) * epochs
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    scheduler = get_linear_schedule_with_warmup(optimizer, int(steps * 0.1), steps)

    def dev_probabilities():
        model.eval()
        out_probs = []
        with torch.no_grad():
            for start in range(0, len(dev_texts), 64):
                batch = tokenizer(dev_texts[start:start + 64], truncation=True, max_length=config["max_length"], padding=True, return_tensors="pt").to(device)
                out_probs += torch.sigmoid(model(**batch).logits).cpu().tolist()
        model.train()
        return out_probs

    log, best, started = [], None, time.monotonic()
    model.train()
    for epoch in range(1, epochs + 1):
        order = list(range(len(train)))
        random.shuffle(order)
        total = 0.0
        for start in range(0, len(order), batch_size):
            ids = order[start:start + batch_size]
            batch = tokenizer([texts[i] for i in ids], truncation=True, max_length=config["max_length"], padding=True, return_tensors="pt").to(device)
            loss = loss_fn(model(**batch).logits, targets[ids].to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            total += loss.item() * len(ids)
        probs = dev_probabilities()
        gold = [r["labels"] for r in dev]
        thresholds = tune_thresholds(probs, gold, labels) if config["tune_thresholds"] else [0.5] * len(labels)
        predicted = [[l for l, p, t in zip(labels, ps, thresholds) if p >= t] for ps in probs]
        dev_metrics = metrics(gold, predicted, labels)
        entry = {"epoch": epoch, "train_loss": round(total / len(train), 4), "dev_micro_f1": dev_metrics["micro"]["f1"],
                 "dev_macro_f1": dev_metrics["macro"]["f1"], "elapsed_seconds": round(time.monotonic() - started, 1)}
        log.append(entry)
        print(json.dumps(entry, ensure_ascii=False), flush=True)
        if best is None or entry["dev_micro_f1"] > best["dev_micro_f1"]:
            best = {**entry, "thresholds": thresholds, "dev": {"micro": dev_metrics["micro"], "macro": dev_metrics["macro"]}}
            model.save_pretrained(out)
            tokenizer.save_pretrained(out)
    save_meta(out, name=name, kind="transformer", base_model=BASE_MODEL, labels=labels, thresholds=best["thresholds"],
              with_context=config["with_context"], max_length=config["max_length"], config=config,
              threshold_policy=THRESHOLD_POLICY if config["tune_thresholds"] else "0.5 고정",
              hyperparameters={"epochs": epochs, "batch_size": batch_size, "lr": lr, "seed": seed, "warmup": 0.1, "weight_decay": 0.01},
              best_epoch=best["epoch"], dev=best["dev"], log=log, train_seconds=round(time.monotonic() - started, 1),
              device=device, train_sentences=len(train), trained_at=datetime.now(timezone.utc).isoformat())
    return best


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", choices=["baseline", "v1", "v2"])
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--limit", type=int, help="smoke test on the first N training sentences")
    args = parser.parse_args()
    out = args.data / args.model
    result = train_baseline(args.data, out) if args.model == "baseline" else train_transformer(args.model, args.data, out, epochs=args.epochs, limit=args.limit)
    print(json.dumps({"micro": result["micro"] if "micro" in result else result["dev"]["micro"]}, ensure_ascii=False))
