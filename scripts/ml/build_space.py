#!/usr/bin/env python3
"""Assemble the Hugging Face Space for the clause model server.

  python3 scripts/ml/build_space.py            # -> var/space (code) + var/space-model (weights)
  python3 scripts/ml/build_space.py --model v1

var/space goes to a public Gradio Space (free CPU basic needs a public Space); var/space-model goes to a
*private* model repo the Space downloads with its HF_TOKEN secret. Weights are hard-linked, not copied.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.ml.common import DATA

SERVER = ROOT / "model_server"
OUT = ROOT / "var/space"
MODEL_OUT = ROOT / "var/space-model"
MODEL_FILES = ["config.json", "meta.json", "model.safetensors", "special_tokens_map.json", "tokenizer.json",
               "tokenizer_config.json", "vocab.txt"]


def link_or_copy(source, target):
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def build(model="v2", out=OUT, data=DATA, model_out=MODEL_OUT):
    source = Path(data) / model
    meta = json.loads((source / "meta.json").read_text(encoding="utf-8"))
    if meta.get("kind") != "transformer":
        raise SystemExit(f"{model}는 transformer 체크포인트가 아닙니다.")
    missing = [name for name in MODEL_FILES if not (source / name).is_file()]
    if missing:
        raise SystemExit(f"{source}에 파일이 없습니다: {', '.join(missing)}")
    for folder in (out, model_out):
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
    for path in SERVER.iterdir():
        if path.is_file():
            shutil.copy2(path, out / path.name)
    # The server reads the same model_input() the model was trained with.
    shutil.copy2(ROOT / "backend/clause_labels.py", out / "clause_labels.py")
    for name in MODEL_FILES:
        link_or_copy(source / name, model_out / name)
    (model_out / "README.md").write_text(
        "---\nlicense: other\n---\n\n권리ON 조항 유형 분류 체크포인트. AI Hub 데이터로 학습했으므로 **비공개**로 둡니다.\n", encoding="utf-8")
    return out, meta


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="v2")
    args = parser.parse_args()
    out, meta = build(args.model)
    print(f"{out.relative_to(ROOT)} (code) + {MODEL_OUT.relative_to(ROOT)} (model {meta.get('name')}, {len(meta['labels'])} labels)")
    print("hf upload <user>/<model-repo> var/space-model . --repo-type model   # private repo")
    print("hf upload <user>/<space> var/space . --repo-type space")
