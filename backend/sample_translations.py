"""Translations of the bundled samples, generated ahead of time so they read without a model at runtime."""
from functools import lru_cache
import json
import re

from backend.auto_translation import apply_translations
from backend.knowledge import ROOT

CATALOG = ROOT / "resources/sample-translations.json"


@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.is_file() else {}


def sample_translation(result, language):
    """Return the stored translation when every contract line is a sample line, otherwise None."""
    data = catalog()
    lines = [b["text"] for b in result["blocks"] if re.search(r"[가-힣]", b["text"])]
    if not lines or not set(lines) <= set(data.get("lines", ())):
        return None
    return {**apply_translations(result, language, data.get(language, {})), "bundled": True}
