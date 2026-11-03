#!/usr/bin/env python3
"""Fill resources/sample-translations.json using the local Ollama model. Safe to re-run: only missing lines are sent."""
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.analysis import evaluate, extract
from backend.auto_translation import read_path, review_strings, translate_texts
from backend.schemas import AnalyzeRequest
from backend.sample_translations import CATALOG

ROLES = {"employment": ("worker", "employer"), "lease": ("tenant", "landlord"), "sale": ("buyer", "seller")}
CHUNK = 20
korean = re.compile(r"[가-힣]")


def sample_strings():
    """Contract lines and review strings of every sample, from each party's side."""
    lines, review = set(), set()
    for sample in json.loads((ROOT / "samples/manifest.json").read_text(encoding="utf-8")):
        text = (ROOT / f"samples/{sample['id']}.txt").read_text(encoding="utf-8")
        for role in ROLES[sample["contract_type"]]:
            request = AnalyzeRequest(title=sample["title"], text=text, contract_type=sample["contract_type"],
                                     user_role=role, engine="rules", context=sample["context"])
            result = evaluate(request, *extract(request), "sample", 1)
            lines |= {b["text"] for b in result["blocks"] if korean.search(b["text"])}
            review |= {s for s in (read_path(result, p) for p in review_strings(result)) if korean.search(s)}
    return sorted(lines), sorted(review)


def save(data):
    CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def main():
    lines, review = sample_strings()
    data = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.is_file() else {}
    data["lines"] = lines
    wanted = [*lines, *review]
    for language in ("zh", "es"):
        table = {k: v for k, v in data.get(language, {}).items() if k in wanted}
        data[language] = table
        missing = [s for s in wanted if s not in table]
        for start in range(0, len(missing), CHUNK):
            table.update(translate_texts(missing[start:start + CHUNK], language))
            save(data)
            print(language, f"{min(start + CHUNK, len(missing))}/{len(missing)}", f"translated={len(table)}/{len(wanted)}", flush=True)
        save(data)
        left = [s for s in lines if s not in table]
        print(language, "contract lines still in Korean:", len(left), flush=True)


if __name__ == "__main__":
    main()
