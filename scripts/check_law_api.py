#!/usr/bin/env python3
"""Verify law.go.kr list/detail access without printing OC or authenticated URLs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.config import load_env
from backend.law_client import (DEFAULT_SEARCH, DEFAULT_SERVICE, check_endpoint,
                                fetch_json, public_law_link, sanitize)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="근로기준법")
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "var/law-api")
    args = parser.parse_args()
    settings = load_env(ROOT / ".env")
    oc = os.environ.get("legal_api_key") or settings.get("legal_api_key") or os.environ.get("LAW_API_OC") or settings.get("LAW_API_OC", "")
    if not oc.strip():
        print(".env의 legal_api_key 또는 LAW_API_OC가 비어 있습니다.", file=sys.stderr)
        return 2
    try:
        search_url = check_endpoint(os.environ.get("legal_api_search_url") or settings.get("legal_api_search_url") or DEFAULT_SEARCH, "/DRF/lawSearch.do")
        service_url = check_endpoint(os.environ.get("legal_api_service_url") or settings.get("legal_api_service_url") or DEFAULT_SERVICE, "/DRF/lawService.do")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checked_at = datetime.now(timezone.utc).isoformat()
    report = {
        "checked_at": checked_at, "query": args.query, "target": "eflaw",
        "search_endpoint": search_url, "service_endpoint": service_url,
        "credential_configured": True, "status": "failed", "checks": {},
        "official_guides": [
            "https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdListGuide",
            "https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsEfYdInfoGuide",
        ],
    }
    search = fetch_json(search_url, {"target": "eflaw", "type": "JSON", "query": args.query, "nw": "3", "display": "100", "page": "1"}, oc, args.timeout)
    report["checks"]["search"] = {k: v for k, v in search.items() if k != "payload"}
    if search["ok"]:
        payload = search["payload"]
        if not isinstance(payload.get("LawSearch"), dict):
            report["checks"]["search"].update(ok=False, error_type="missing_LawSearch", root_keys=list(payload))
        else:
            (args.output_dir / "search.json").write_text(json.dumps(sanitize(payload, oc), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            root = payload["LawSearch"]
            rows = root.get("law", [])
            rows = [rows] if isinstance(rows, dict) else rows
            rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
            report["checks"]["search"]["total_count"] = root.get("totalCnt")
            report["candidates"] = [{k: r.get(k) for k in ("법령명한글", "법령ID", "법령일련번호", "시행일자", "법령구분명")} for r in rows]
            exact = [r for r in rows if r.get("법령명한글") == args.query]
            if len(exact) != 1:
                report["checks"]["selection"] = {"ok": False, "exact_count": len(exact), "reason": "exact_title_required"}
            else:
                selected = exact[0]
                mst = str(selected.get("법령일련번호", ""))
                ef_date = str(selected.get("시행일자", ""))
                if not mst.isdigit() or not re.fullmatch(r"\d{8}", ef_date):
                    report["checks"]["selection"] = {"ok": False, "reason": "missing_version_identifier"}
                else:
                    report["checks"]["selection"] = {"ok": True}
                    detail = fetch_json(service_url, {"target": "eflaw", "type": "JSON", "MST": mst, "efYd": ef_date}, oc, args.timeout)
                    report["checks"]["detail"] = {k: v for k, v in detail.items() if k != "payload"}
                    if detail["ok"]:
                        document = detail["payload"].get("법령")
                        if not isinstance(document, dict):
                            report["checks"]["detail"].update(ok=False, error_type="missing_law_body", root_keys=list(detail["payload"]))
                        else:
                            basic = document.get("기본정보", {})
                            title = basic.get("법령명_한글") if isinstance(basic, dict) else None
                            body_law_id = str(basic.get("법령ID", "")) if isinstance(basic, dict) else ""
                            body_effective_date = str(basic.get("시행일자", "")) if isinstance(basic, dict) else ""
                            articles = document.get("조문", {}).get("조문단위", []) if isinstance(document.get("조문"), dict) else []
                            articles = [articles] if isinstance(articles, dict) else articles
                            if title != args.query or body_law_id.zfill(6) != str(selected.get("법령ID", "")).zfill(6) or body_effective_date != ef_date or not isinstance(articles, list) or not articles:
                                report["checks"]["detail"].update(ok=False, error_type="title_version_or_articles_mismatch")
                            else:
                                safe_payload = sanitize(detail["payload"], oc)
                                serialized = json.dumps(safe_payload, ensure_ascii=False, indent=2) + "\n"
                                (args.output_dir / "law_body.json").write_text(serialized, encoding="utf-8")
                                report.update(status="verified", law_title=title, law_id=selected.get("법령ID"), master_id=mst, effective_date=ef_date, article_unit_count=len(articles), article_count=sum(a.get("조문여부") == "조문" for a in articles if isinstance(a, dict)), content_hash=hashlib.sha256(serialized.encode()).hexdigest(), official_url=public_law_link(str(selected.get("법령상세링크", ""))))
    safe_report = sanitize(report, oc)
    (args.output_dir / "check_report.json").write_text(json.dumps(safe_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(safe_report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
