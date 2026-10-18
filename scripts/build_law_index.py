#!/usr/bin/env python3
"""Compile verified local law snapshots into a credential-free, public article index."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def flatten(node):
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for item in node for text in flatten(item)]
    if isinstance(node, dict):
        return [text for key, value in node.items() if key in {"조문내용", "항내용", "호내용", "목내용", "항", "호", "목"} for text in flatten(value)]
    return []


def main():
    articles = []
    for report_path in sorted((ROOT / "var/law-api").rglob("check_report.json")):
        report = json.loads(report_path.read_text())
        body_path = report_path.with_name("law_body.json")
        if report.get("status") != "verified" or not body_path.exists():
            continue
        raw = body_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != report.get("content_hash"):
            raise ValueError("Snapshot hash mismatch; run check_law_api.py again.")
        law = json.loads(raw)["법령"]
        for article in law["조문"]["조문단위"]:
            if article.get("조문여부") != "조문":
                continue
            number, branch = article["조문번호"], article.get("조문가지번호", "")
            label = f"제{number}조" + (f"의{branch}" if branch else "")
            effective = str(report["effective_date"])
            articles.append({
                "source_id": f"law-{report['law_id']}-{report['master_id']}-{article['조문키']}",
                "law_title": report["law_title"], "title": f"{report['law_title']} {label} {article.get('조문제목', '')}".strip(),
                "article_number": str(number), "branch_number": str(branch),
                "text": "\n".join(flatten(article)),
                "effective_date": f"{effective[:4]}-{effective[4:6]}-{effective[6:]}",
                "checked_at": report["checked_at"], "snapshot_id": report["content_hash"][:16],
                "official_url": f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={report['master_id']}&efYd={effective}",
            })
    if not articles:
        raise ValueError("No verified law snapshots found.")
    target = ROOT / "resources/law-index.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps({"schema_version": "1.0", "articles": articles}, ensure_ascii=False, indent=2) + "\n")
    print(f"Compiled {len(articles)} official article entries into {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
