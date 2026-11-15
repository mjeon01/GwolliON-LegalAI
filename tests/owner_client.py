"""A TestClient that keeps the owner tokens it is issued, as the browser does."""
import re

from fastapi.testclient import TestClient

PATH = re.compile(r"/api/(?:analyses|agent/sessions)/([0-9a-f-]{36})")


class OwnerClient(TestClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tokens = {}

    def request(self, method, url, *args, **kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        match = PATH.search(str(url))
        if match and match.group(1) in self.tokens:
            headers.setdefault("x-gwollion-token", self.tokens[match.group(1)])
        if str(url).rstrip("/").endswith("/api/analyses") and method.upper() == "GET":
            headers.setdefault("x-gwollion-tokens", ",".join(f"{k}:{v}" for k, v in self.tokens.items()))
        response = super().request(method, url, *args, headers=headers, **kwargs)
        if response.content and response.headers.get("content-type", "").startswith("application/json"):
            body = response.json()
            if isinstance(body, dict) and body.get("access_token"):
                self.tokens[body.get("session_id") or body["analysis_id"]] = body["access_token"]
        return response
