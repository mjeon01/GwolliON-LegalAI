"""Verified official law/case retrieval with bounded, credential-free disk caching."""
from datetime import date, datetime, timezone
import hashlib
from html import unescape
import json
import os
from pathlib import Path
import re
import time
import uuid

from scripts.check_law_api import (load_env, check_endpoint, fetch_json, sanitize,
                                   DEFAULT_SEARCH, DEFAULT_SERVICE, public_law_link)
from scripts.build_law_index import flatten

ROOT = Path(__file__).resolve().parents[1]


class EvidenceError(ValueError):
    pass


def rows(value):
    return [value] if isinstance(value, dict) else value if isinstance(value, list) else []


def iso_date(value):
    digits = re.sub(r"\D", "", str(value))
    if len(digits) != 8:
        raise EvidenceError("invalid_date")
    try:
        return date.fromisoformat(f"{digits[:4]}-{digits[4:6]}-{digits[6:]}").isoformat()
    except ValueError:
        raise EvidenceError("invalid_date") from None


def plain(value):
    text = str(value or "")
    text = re.sub(r"<\s*(?:br|/p|/div)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]*>", "", text)
    return unescape(text).strip()


class LegalAPI:
    def __init__(self, cache_dir=None, transport=None, settings=None, timeout=8):
        settings = load_env(ROOT / ".env") if settings is None else settings
        self.oc = os.environ.get("legal_api_key") or settings.get("legal_api_key") or os.environ.get("LAW_API_OC") or settings.get("LAW_API_OC", "")
        self.search_url = check_endpoint(settings.get("legal_api_search_url") or DEFAULT_SEARCH, "/DRF/lawSearch.do")
        self.service_url = check_endpoint(settings.get("legal_api_service_url") or DEFAULT_SERVICE, "/DRF/lawService.do")
        self.cache_dir = Path(cache_dir or ROOT / "var/evidence-cache")
        self.transport = transport or fetch_json
        self.timeout = timeout

    def request(self, detail, params):
        if not self.oc:
            raise EvidenceError("credential_missing")
        endpoint = self.service_url if detail else self.search_url
        params = {"type": "JSON", **params}
        key = hashlib.sha256(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()
        path = self.cache_dir / (key + ".json")
        try:
            cached = json.loads(path.read_text())
            encoded = json.dumps(cached["payload"], ensure_ascii=False, sort_keys=True).encode()
            if time.time() - cached["stored_at"] < 12 * 3600 and hashlib.sha256(encoded).hexdigest() == cached["hash"]:
                return cached["payload"], cached["checked_at"], "cache"
        except (OSError, ValueError, KeyError, TypeError):
            pass
        result = self.transport(endpoint, params, self.oc, self.timeout)
        if not result.get("ok"):
            raise EvidenceError(result.get("error_type", "api_error"))
        payload = sanitize(result["payload"], self.oc)
        # Some endpoints return an error object with HTTP 200.
        if any(isinstance(r, dict) and r.get("resultCode") not in (None, "00", "0") for r in payload.values()):
            raise EvidenceError("api_validation")
        checked_at = datetime.now(timezone.utc).isoformat()
        record = {"payload": payload, "checked_at": checked_at, "stored_at": time.time(), "hash": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        return payload, checked_at, "live"

    def law(self, title, event_date=None):
        target = min(event_date or date.today().isoformat(), date.today().isoformat())
        payload, _, _ = self.request(False, {"target": "eflaw", "query": title, "search": "1", "nw": "1,3", "efYd": "19000101~" + target.replace("-", ""), "sort": "efdes", "display": "100"})
        root = payload.get("LawSearch")
        if not isinstance(root, dict):
            raise EvidenceError("missing_law_search")
        candidates = [r for r in rows(root.get("law")) if r.get("법령명한글") == title and iso_date(r.get("시행일자")) <= target]
        if not candidates:
            raise EvidenceError("exact_law_version_not_found")
        selected = max(candidates, key=lambda r: (iso_date(r["시행일자"]), int(r["법령일련번호"])))
        mst, effective = str(selected["법령일련번호"]), iso_date(selected["시행일자"])
        if not mst.isdigit():
            raise EvidenceError("invalid_law_id")
        payload, checked, origin = self.request(True, {"target": "eflaw", "MST": mst, "efYd": effective.replace("-", "")})
        law = payload.get("법령", {})
        basic = law.get("기본정보", {})
        raw_id = str(selected.get("법령ID", ""))
        if not raw_id.isdigit() or len(raw_id) > 6:
            raise EvidenceError("invalid_law_id")
        law_id = raw_id.zfill(6)
        if basic.get("법령명_한글") != title or str(basic.get("법령ID", "")).zfill(6) != law_id or iso_date(basic.get("시행일자")) != effective:
            raise EvidenceError("law_version_mismatch")
        digest = hashlib.sha256(json.dumps(law, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        articles = []
        for article in rows(law.get("조문", {}).get("조문단위")):
            if article.get("조문여부") != "조문":
                continue
            number, branch = str(article["조문번호"]), str(article.get("조문가지번호", ""))
            text = "\n".join(flatten(article))
            if not text.strip():
                continue
            article_effective = iso_date(article.get("조문시행일자") or effective)
            articles.append({"source_id": f"law-{law_id}-{mst}-{article['조문키']}", "kind": "law", "law_title": title,
                             "title": f"{title} 제{number}조" + (f"의{branch}" if branch else "") + " " + str(article.get("조문제목", "")),
                             "article_number": number, "branch_number": branch, "text": text, "effective_date": effective,
                             "article_effective_date": article_effective, "checked_at": checked, "snapshot_id": digest[:16],
                             "official_url": f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={mst}&efYd={effective.replace('-', '')}",
                             "retrieval_method": origin, "version_applicable": article_effective <= target,
                             "version_note": f"{target}까지 시행된 법령 중 조회한 버전입니다. 부칙·적용례·개별 사실에 따른 적용 여부는 추가 확인이 필요합니다."})
        if not articles:
            raise EvidenceError("empty_law_articles")
        return articles

    def cases(self, target, query, event_date=None, limit=1, focus_terms=()):
        spec = {
            "prec": ("PrecSearch", "prec", "판례일련번호", "PrecService", "판례정보일련번호", "사건명", "선고일자", ("판시사항", "판결요지", "판례내용"), "판례상세링크", "precedent"),
            "expc": ("Expc", "expc", "법령해석례일련번호", "ExpcService", "법령해석례일련번호", "안건명", "해석일자", ("질의요지", "회답", "이유"), "법령해석례상세링크", "interpretation"),
            "decc": ("Decc", "decc", "행정심판재결례일련번호", "PrecService", "행정심판례일련번호", "사건명", "의결일자", ("재결요지", "주문", "이유"), "행정심판례상세링크", "decision"),
        }[target]
        search_root, row_key, id_key, detail_root, body_id, title_key, date_key, text_keys, link_key, kind = spec
        params = {"target": target, "query": query, "search": "2", "sort": "ddes", "display": "4"}
        cutoff = min(event_date or date.today().isoformat(), date.today().isoformat())
        params[{"prec": "prncYd", "expc": "explYd", "decc": "rslYd"}[target]] = "19000101~" + cutoff.replace("-", "")
        if target == "prec":
            params["org"] = "400201"  # Supreme Court JSON bodies; tax collections may be HTML-only.
        payload, _, _ = self.request(False, params)
        root = payload.get(search_root)
        if not isinstance(root, dict):
            raise EvidenceError("missing_case_search")
        result = []
        for row in rows(root.get(row_key))[:4]:
            identifier = str(row.get(id_key, ""))
            if not identifier.isdigit():
                continue
            payload, checked, origin = self.request(True, {"target": target, "ID": identifier})
            body = payload.get(detail_root)
            if not isinstance(body, dict):
                continue  # Explicitly skip HTML-only/unavailable bodies.
            if str(body.get(body_id)) != identifier or plain(body.get(title_key)) != plain(row.get(title_key)) or (row.get("사건번호") and body.get("사건번호") != row["사건번호"]):
                raise EvidenceError("case_identity_mismatch")
            decided = iso_date(body.get(date_key))
            listed_date = row.get({"prec": "선고일자", "expc": "회신일자", "decc": "의결일자"}[target])
            if listed_date and iso_date(listed_date) != decided:
                raise EvidenceError("case_date_mismatch")
            if decided > cutoff:
                continue  # No post-event decision silently used as contemporaneous authority.
            parts = {k: plain(body.get(k)) for k in text_keys}
            text = "\n\n".join(k + "\n" + v for k, v in parts.items() if v)
            if not text.strip() or not any(t in text for t in query.split() if len(t) >= 2):
                continue
            if focus_terms and not any(term in text for term in focus_terms):
                continue
            result.append({"source_id": f"{target}-{identifier}", "kind": kind, "title": plain(body.get(title_key)), "text": text,
                           "case_number": body.get("사건번호") or body.get("안건번호", ""), "court": body.get("법원명") or body.get("해석기관명") or body.get("재결청", ""),
                           "decision_date": decided, "checked_at": checked, "retrieval_method": origin,
                           "snapshot_id": hashlib.sha256(text.encode()).hexdigest()[:16], "official_url": public_law_link(str(row.get(link_key, ""))),
                           "version_applicable": False, "version_note": "관련 쟁점의 공식 원문입니다. 사건의 사실관계·적용 법령·후속 판단을 대조해야 하며, 검색 결과만으로 같은 결론을 적용하지 않습니다."})
            if len(result) >= limit:
                break
        return result
