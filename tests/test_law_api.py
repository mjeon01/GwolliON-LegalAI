import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts import check_law_api as client


class LawAPITests(unittest.TestCase):
    def test_http_200_validation_response_is_failure_and_redacted(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = json.dumps({"result": "validation failed", "msg": "OC=test-secret"}).encode()
        opener = MagicMock()
        opener.open.return_value = response
        with patch.object(client, "build_opener", return_value=opener):
            result = client.fetch_json(client.DEFAULT_SEARCH, {"target": "eflaw"}, "test-secret", 5)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "api_validation")
        self.assertNotIn("test-secret", json.dumps(result))

    def test_rejects_credential_forwarding_to_other_endpoint(self):
        for url in ("http://www.law.go.kr/DRF/lawSearch.do", "https://example.com/DRF/lawSearch.do", client.DEFAULT_SEARCH + "?OC=anything"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.check_endpoint(url, "/DRF/lawSearch.do")
        self.assertEqual(client.check_endpoint(client.DEFAULT_SEARCH, "/DRF/lawSearch.do"), client.DEFAULT_SEARCH)

    def test_public_link_strips_oc_and_uses_https(self):
        url = client.public_law_link("/DRF/lawService.do?OC=encoded%2Bsecret&target=eflaw&MST=123")
        self.assertNotIn("OC=", url)
        self.assertNotIn("secret", url)
        self.assertTrue(url.startswith("https://www.law.go.kr/"))
        self.assertIn("MST=123", url)

    def run_fixture(self, body_date="20260101", search_payload=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / ".env").write_text("legal_api_key=test-secret\n")
            search = search_payload or {"LawSearch": {"totalCnt": "2", "law": [
                {"법령명한글": "근로기준법 시행령", "법령ID": "003058", "법령일련번호": "222", "시행일자": "20250101"},
                {"법령명한글": "근로기준법", "법령ID": "001872", "법령일련번호": "111", "시행일자": "20260101"},
            ]}}
            body = {"법령": {"기본정보": {"법령명_한글": "근로기준법", "법령ID": "001872", "시행일자": body_date}, "조문": {"조문단위": [{"조문번호": "1", "조문여부": "조문", "조문내용": "fixture"}]}}}
            with patch.object(client, "ROOT", root), patch.dict(client.os.environ, {"legal_api_key": "test-secret", "legal_api_search_url": client.DEFAULT_SEARCH, "legal_api_service_url": client.DEFAULT_SERVICE}), patch.object(client, "fetch_json", side_effect=[{"ok": True, "payload": search}, {"ok": True, "payload": body}]) as fetch, patch("sys.argv", ["check_law_api.py", "--output-dir", str(root / "result")]), contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = client.main()
                calls = fetch.call_args_list
            report = json.loads((root / "result/check_report.json").read_text())
            return code, report, calls, (root / "result/law_body.json").exists(), stdout.getvalue()

    def test_exact_title_is_selected_and_version_is_pinned(self):
        code, report, calls, has_body, stdout = self.run_fixture()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(calls[1].args[1]["MST"], "111")
        self.assertEqual(calls[1].args[1]["efYd"], "20260101")
        self.assertTrue(has_body)
        self.assertNotIn("test-secret", stdout)

    def test_mismatching_body_version_is_not_saved_as_verified(self):
        code, report, _, has_body, _ = self.run_fixture(body_date="20240101")
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"]["detail"]["error_type"], "title_version_or_articles_mismatch")
        self.assertFalse(has_body)

    def test_unknown_search_schema_does_not_pass(self):
        code, report, calls, has_body, _ = self.run_fixture(search_payload={"unexpected": []})
        self.assertEqual(code, 1)
        self.assertEqual(report["checks"]["search"]["error_type"], "missing_LawSearch")
        self.assertEqual(len(calls), 1)
        self.assertFalse(has_body)


if __name__ == "__main__":
    unittest.main()
