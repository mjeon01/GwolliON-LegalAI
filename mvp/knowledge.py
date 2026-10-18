"""Versioned official article lookup; user documents never enter this index."""
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Knowledge:
    def __init__(self, path=None, supplemental=()):
        path = Path(path or ROOT / "resources/law-index.json")
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"articles": []}
        self.articles = self.data["articles"]
        replacements = {a["law_title"] for a in supplemental if a.get("kind") == "law" and a.get("retrieval_method") in {"live", "cache"}}
        self.articles = [a for a in self.articles if a["law_title"] not in replacements] + [a for a in supplemental if a.get("kind") == "law"]

    def lookup(self, law, number, event_date=None):
        target = event_date or date.today().isoformat()
        candidates = [a for a in self.articles if a["law_title"] == law and a["article_number"] == str(number) and not a["branch_number"]]
        applicable = [a for a in candidates if a["effective_date"] <= target]
        source = max(applicable or candidates, key=lambda a: a["effective_date"]).copy() if candidates else None
        if source:
            source["version_applicable"] = source.get("article_effective_date", source["effective_date"]) <= target
            source["version_note"] = source.get("version_note") or (
                "저장된 법령 버전의 시행일 이후 시점입니다. 개별 적용 조건은 추가 확인이 필요합니다."
                if source["version_applicable"] else
                "사건일이 저장된 법령 버전보다 앞섭니다. 당시 시행 법령을 추가 조회해야 합니다."
            )
        return source

    def search(self, query, limit=5):
        words = [w for w in query.split() if len(w) > 1]
        ranked = sorted(self.articles, key=lambda a: sum(a["text"].count(w) + 4 * a["title"].count(w) for w in words), reverse=True)
        return [a for a in ranked[:limit] if any(w in a["text"] or w in a["title"] for w in words)]
