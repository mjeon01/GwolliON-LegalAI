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
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DEFAULT_SERVICE = "https://www.law.go.kr/DRF/lawService.do"
MAX_RESPONSE = 16 * 1024 * 1024


def load_env(path: Path) -> dict[str, str]:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key.strip()] = value
    return values


def sanitize(value: object, secret: str) -> object:
    if isinstance(value, dict):
        return {k: sanitize(v, secret) for k, v in value.items() if str(k).lower() != "oc"}
    if isinstance(value, list):
        return [sanitize(v, secret) for v in value]
    if isinstance(value, str):
        value = value.replace(secret, "[REDACTED]") if secret else value
        return re.sub(r"(?i)([?&]OC=)[^&\s\"'<>]+", r"\1[REDACTED]", value)
    return value


def check_endpoint(url: str, expected_path: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in {"www.law.go.kr", "law.go.kr"}
        or parts.path != expected_path
        or parts.username or parts.password or parts.port not in (None, 443)
        or parts.query or parts.fragment
    ):
        raise ValueError("URL은 공식 law.go.kr HTTPS endpoint이며 쿼리가 없어야 합니다.")
    return url


class OfficialRedirectsOnly(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname not in {"www.law.go.kr", "law.go.kr"}:
            raise ValueError("공식 HTTPS 호스트 밖으로 향하는 redirect를 거부했습니다.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_law_link(link: str) -> str:
    parts = urlsplit(link)
    host = parts.hostname or "www.law.go.kr"
    if host not in {"www.law.go.kr", "law.go.kr"}:
        return ""
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if k.lower() != "oc"])
    return urlunsplit(("https", host, parts.path, query, ""))


def fetch_json(endpoint: str, params: dict[str, str], oc: str, timeout: int) -> dict:
    authenticated_url = endpoint + "?" + urlencode({"OC": oc, **params})
    req = Request(authenticated_url, headers={"User-Agent": "GwolliON-LegalAI/0.1", "Accept": "application/json"})
    try:
        with build_opener(OfficialRedirectsOnly()).open(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE + 1)
            metadata = {"http_status": response.status, "content_type": response.headers.get("Content-Type", ""), "bytes": len(raw)}
        if len(raw) > MAX_RESPONSE:
            return {"ok": False, "error_type": "response_too_large", **metadata}
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            return {"ok": False, "error_type": "unexpected_json_shape", **metadata}
        if "result" in payload and "msg" in payload and "LawSearch" not in payload and "법령" not in payload:
            return {"ok": False, "error_type": "api_validation", "api_response": sanitize(payload, oc), **metadata}
        return {"ok": True, "payload": payload, **metadata}
    except HTTPError as exc:
        return {"ok": False, "error_type": "http_error", "http_status": exc.code}
    except URLError as exc:
        return {"ok": False, "error_type": "network_error", "reason_type": type(exc.reason).__name__}
    except TimeoutError:
        return {"ok": False, "error_type": "timeout"}
    except (ValueError, UnicodeError):
        return {"ok": False, "error_type": "non_json_or_unsafe_redirect"}


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
