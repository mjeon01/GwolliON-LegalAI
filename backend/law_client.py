"""Shared official-law HTTP helpers and structured article text extraction."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

DEFAULT_SEARCH = "https://www.law.go.kr/DRF/lawSearch.do"
DEFAULT_SERVICE = "https://www.law.go.kr/DRF/lawService.do"
MAX_RESPONSE = 16 * 1024 * 1024


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


def flatten(node):
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for item in node for text in flatten(item)]
    if isinstance(node, dict):
        return [text for key, value in node.items() if key in {"조문내용", "항내용", "호내용", "목내용", "항", "호", "목"} for text in flatten(value)]
    return []
