"""Clause-type model server: the trained classifier behind one HTTP endpoint.

Runs as a Hugging Face Space (Gradio SDK, free CPU basic) so the app itself does not carry torch or the checkpoint.
Free accounts get CPU basic only for public Spaces, so the Space holds code only:
  - weights come from a private model repo (MODEL_REPO) with a read token (Space secret HF_TOKEN)
  - /classify requires the X-Api-Key header to match the Space secret API_KEY
The Space runs `python app.py`. DEMO_PAGE=1 mounts a Gradio test page at "/" (it bypasses the key: keep it off in public).
POST /classify {"rows": [{"text": "...", "title": "제5조(위약금)"}]} -> {"model": "v2", "labels": [["손해배상의 예정"]]}
Only clause types are returned; burden decisions stay in the app (backend/clause_labels.wording_supports).
"""
import hmac
import json
import os
from pathlib import Path
import threading

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from clause_labels import model_input

MODEL_DIR = Path(os.environ.get("MODEL_DIR", Path(__file__).parent / "model"))
MODEL_REPO = os.environ.get("MODEL_REPO", "").strip()
API_KEY = os.environ.get("API_KEY", "").strip()
# A public deployment (Space, or the booth Mac behind a tunnel) must not serve without a key.
ON_SPACE = bool(os.environ.get("SPACE_ID")) or os.environ.get("REQUIRE_API_KEY") == "1"
MAX_ROWS = 400
MAX_TEXT = 1000
torch.set_num_threads(int(os.environ.get("TORCH_THREADS", os.cpu_count() or 2)))


class Row(BaseModel):
    text: str = Field(max_length=MAX_TEXT * 4)
    title: str = Field(default="", max_length=MAX_TEXT)


class Request(BaseModel):
    rows: list[Row] = Field(max_length=MAX_ROWS)


class Classifier:
    def __init__(self, path):
        self.meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        self.labels = self.meta["labels"]
        self.thresholds = self.meta.get("thresholds") or [0.5] * len(self.labels)
        self.tokenizer = AutoTokenizer.from_pretrained(path)
        self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        self.model = AutoModelForSequenceClassification.from_pretrained(path).to(self.device).eval()
        self.lock = threading.Lock()  # one forward pass at a time; torch already uses every core

    def predict(self, rows, batch_size=32):
        texts = [model_input(r.text[:MAX_TEXT], r.title[:MAX_TEXT], self.meta.get("with_context", False)) for r in rows]
        out = []
        with self.lock, torch.inference_mode():
            for start in range(0, len(texts), batch_size):
                batch = self.tokenizer(texts[start:start + batch_size], truncation=True, max_length=self.meta["max_length"],
                                       padding=True, return_tensors="pt").to(self.device)
                for probs in torch.sigmoid(self.model(**batch).logits).cpu().tolist():
                    out.append([l for l, p, t in zip(self.labels, probs, self.thresholds) if p >= t])
        return out


def model_dir():
    if (MODEL_DIR / "meta.json").is_file():
        return MODEL_DIR
    if not MODEL_REPO:
        raise SystemExit(f"no model at {MODEL_DIR}; set MODEL_REPO (and the HF_TOKEN secret for a private repo)")
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(MODEL_REPO, token=os.environ.get("HF_TOKEN") or None))


classifier = Classifier(model_dir())
app = FastAPI(title="권리ON clause model", docs_url=None, redoc_url=None, openapi_url=None)


def check_key(given):
    if not API_KEY:
        if ON_SPACE:  # a public Space without a key would serve anyone
            raise HTTPException(503, "API_KEY secret is not set")
        return
    if not hmac.compare_digest((given or "").encode(), API_KEY.encode()):
        raise HTTPException(401, "invalid API key")


@app.get("/")
def root():
    return {"service": "권리ON clause model", "health": "/health"}


@app.get("/health")
def health():
    return {"ok": True, "model": classifier.meta.get("name"), "labels": len(classifier.labels), "device": classifier.device}


@app.post("/classify")
def classify(request: Request, x_api_key: str | None = Header(default=None)):
    check_key(x_api_key)
    if not request.rows:
        return {"model": classifier.meta.get("name"), "labels": []}
    try:
        labels = classifier.predict(request.rows)
    except Exception as error:  # never leak a stack trace to the caller
        raise HTTPException(500, "classification failed") from error
    return {"model": classifier.meta.get("name"), "labels": labels}


def demo_page():
    """A test page for the team: one line per sentence, "제목 || 문장" to give the article heading."""
    import gradio as gr

    def run(text):
        rows = []
        for line in (text or "").splitlines()[:MAX_ROWS]:
            title, _, body = line.rpartition("||") if "||" in line else ("", "", line)
            if body.strip():
                rows.append(Row(text=body.strip()[:MAX_TEXT], title=title.strip()[:MAX_TEXT]))
        return [{"text": r.text, "labels": labels} for r, labels in zip(rows, classifier.predict(rows))] if rows else []

    return gr.Interface(run, gr.Textbox(lines=8, label="문장 (한 줄에 하나, 선택: 조 제목 || 문장)"), gr.JSON(label="조항 유형"),
                        title="권리ON 조항 유형 분류", flagging_mode="never")


if __name__ == "__main__":
    import uvicorn
    server = app
    if os.environ.get("DEMO_PAGE") == "1":
        app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/"]
        server = __import__("gradio").mount_gradio_app(app, demo_page(), path="/")
    uvicorn.run(server, host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
