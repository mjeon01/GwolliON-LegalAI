"""Trained clause-type classifier (AI Hub employment contracts). Optional: absent model -> None everywhere."""
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import re

from backend.clause_labels import INHERENT_RISK, REQUIRED, RISK_TYPES, model_input, wording_supports
from backend.knowledge import ROOT

DEFAULT_PATH = ROOT / "var/ml/clause/v2"
log = logging.getLogger(__name__)
# "제3조(임금)", "제 3 조", "3. 근로시간" — a short line that opens an article.
HEADING = re.compile(r"^(?:제\s*\d+\s*조|\d{1,2}\.\s*\S)")


class ClauseModel:
    """Loads a model saved by scripts/ml/train_clause.py (kind: tfidf or transformer)."""

    def __init__(self, path):
        self.path = Path(path)
        self.meta = json.loads((self.path / "meta.json").read_text(encoding="utf-8"))
        self.labels = self.meta["labels"]
        self.thresholds = self.meta.get("thresholds") or [0.5] * len(self.labels)
        if self.meta["kind"] == "tfidf":
            import joblib
            self.pipeline = joblib.load(self.path / "model.joblib")
        else:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self.torch = torch
            self.device = "mps" if torch.backends.mps.is_available() else "cpu"
            self.tokenizer = AutoTokenizer.from_pretrained(self.path)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.path).to(self.device).eval()

    def inputs(self, rows):
        return [model_input(r["text"], r.get("title", ""), self.meta.get("with_context", False)) for r in rows]

    def probabilities(self, rows, batch_size=32):
        texts = self.inputs(rows)
        if self.meta["kind"] == "tfidf":
            return self.pipeline.predict_proba(texts).tolist()
        out = []
        with self.torch.no_grad():
            for start in range(0, len(texts), batch_size):
                batch = self.tokenizer(texts[start:start + batch_size], truncation=True, max_length=self.meta["max_length"],
                                       padding=True, return_tensors="pt").to(self.device)
                out += self.torch.sigmoid(self.model(**batch).logits).cpu().tolist()
        return out

    def predict(self, rows):
        return [[label for label, p, t in zip(self.labels, probs, self.thresholds) if p >= t] for probs in self.probabilities(rows)]


def rows_from_blocks(blocks):
    """Blocks are lines; the latest article heading gives context to the lines under it."""
    rows, title = [], ""
    for block in blocks:
        text = " ".join(block["text"].split())
        if HEADING.match(text) and len(text) <= 40:
            title = text
        rows.append({"text": text, "title": title})
    return rows


class RemoteModelError(RuntimeError):
    pass


class RemoteClauseModel:
    """Asks a model server (model_server/, e.g. a private Hugging Face Space) for the clause types.

    Keeps the app light: torch and the 1.3 GB checkpoint live on the server. Any failure raises
    RemoteModelError and classify() falls back to rules only, so a sleeping or broken server never blocks analysis.
    """

    def __init__(self, url, token="", timeout=20.0, transport=None, key=""):
        self.url = url.rstrip("/")
        self.key = key  # X-Api-Key for a public Space; token is a Hugging Face token for a private one
        self.transport = transport  # tests only
        self.token = token
        self.timeout = timeout
        self.path = Path(self.url)
        self.meta = {"name": "remote", "kind": "remote"}

    def predict(self, rows):
        import httpx
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        if self.key:
            headers["X-Api-Key"] = self.key
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=5), follow_redirects=False,
                              transport=self.transport) as client:
                response = client.post(f"{self.url}/classify", headers=headers,
                                       json={"rows": [{"text": r["text"], "title": r.get("title", "")} for r in rows]})
            response.raise_for_status()
            body = response.json()
            labels = body["labels"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise RemoteModelError(f"clause model server failed: {type(error).__name__}") from error
        if not isinstance(labels, list) or len(labels) != len(rows) or not all(isinstance(l, list) for l in labels):
            raise RemoteModelError("clause model server returned a malformed answer")
        self.meta = {**self.meta, "name": str(body.get("model") or "remote")}
        return [[str(label) for label in row] for row in labels]


@lru_cache(maxsize=2)
def load(path=None):
    url = "" if path else os.environ.get("GWOLLION_CLAUSE_MODEL_URL", "").strip()
    if url:
        timeout = float(os.environ.get("GWOLLION_CLAUSE_MODEL_TIMEOUT", "20"))
        return RemoteClauseModel(url, os.environ.get("GWOLLION_CLAUSE_MODEL_TOKEN", "").strip(), timeout,
                                 key=os.environ.get("GWOLLION_CLAUSE_MODEL_KEY", "").strip())
    setting = path or os.environ.get("GWOLLION_CLAUSE_MODEL") or DEFAULT_PATH
    if str(setting).lower() == "off":
        return None
    path = Path(setting)
    if not (path / "meta.json").is_file():
        return None
    return ClauseModel(path)


def classify(blocks, contract_type="employment", model=None):
    """Clause types per block, burden candidates and missing required items; None if no model is installed."""
    if contract_type != "employment":
        return None
    model = model or load()
    if model is None or not blocks:
        return None
    try:
        predicted = model.predict(rows_from_blocks(blocks))
    except RemoteModelError as error:
        log.warning("%s; continuing with rules only", error)
        return None
    found = {label for labels in predicted for label in labels}
    return {"model": model.meta.get("name", model.path.name), "kind": model.meta["kind"],
            "blocks": [{"block_id": b["block_id"], "labels": labels,
                        "risk_candidates": [RISK_TYPES[label] for label in labels if label in RISK_TYPES
                                            and (label not in INHERENT_RISK or wording_supports(label, b["text"]))]}
                       for b, labels in zip(blocks, predicted)],
            "missing_required": [label for label in REQUIRED if label not in found],
            "note": "AI Hub 근로계약서로 학습한 조항 유형 분류 결과입니다. 위험 여부는 규칙·원문 확인을 거쳐 판단합니다."}
