"""The contracts offered to users must trigger exactly what their cards promise."""
import json
from pathlib import Path
import re
import tempfile
import time
import unittest

import fitz
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.knowledge import ROOT
from backend.reading import ocr_available

SAMPLES = json.loads((ROOT / "samples/manifest.json").read_text())


def unmarked(quote):
    return re.sub(r"^[-\d.)\s]+", "", quote)


class SampleCatalogTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.client = TestClient(create_app(Path(folder.name) / "samples.sqlite3"))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def review(self, sample, text, **extra):
        body = {"title": sample["title"], "text": text, "contract_type": sample["contract_type"], "context": sample["context"], **extra}
        id = self.client.post("/api/analyses", json=body).json()["analysis_id"]
        for _ in range(200):
            value = self.client.get(f"/api/analyses/{id}").json()
            if value["status"] not in {"queued", "running"}:
                return value
            time.sleep(0.05)
        raise AssertionError("analysis did not finish")

    def check(self, sample, result):
        self.assertCountEqual([f["issue_type"] for f in result["review"]["findings"]], sample["expected"]["finding_types"])
        issues = {i["issue_type"] for i in result["issues"]}
        self.assertTrue(set(sample["expected"].get("issue_types", [])) <= issues, issues)
        terms = {t["key"]: t for t in result["terms"]}
        self.assertEqual(terms["period"]["status"], "found")
        if "wage_status" in sample["expected"]:
            self.assertEqual(terms["wage"]["status"], sample["expected"]["wage_status"])
        if "wage" in sample["expected"]:
            self.assertEqual(terms["wage"]["candidates"][0]["normalized_value"]["amount"], sample["expected"]["wage"])
        if "deposit" in sample["expected"]:
            self.assertEqual(terms["deposit"]["candidates"][0]["normalized_value"]["amount"], sample["expected"]["deposit"])

    def test_catalog_is_four_employment_and_one_real_estate(self):
        kinds = [s["contract_type"] for s in SAMPLES]
        self.assertEqual((kinds.count("employment"), kinds.count("lease")), (4, 1))
        self.assertEqual(sum(not s["expected"]["finding_types"] for s in SAMPLES), 1)

    def test_contracts_do_not_read_like_test_data(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample["id"]):
                text = (ROOT / f"samples/{sample['id']}.txt").read_text()
                self.assertIsNone(re.search(r"가상|합성|샘플|테스트|시연|SAMPLE", text))

    def test_text_review_matches_each_card(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample["id"]):
                self.check(sample, self.review(sample, (ROOT / f"samples/{sample['id']}.txt").read_text()))

    def test_uploaded_pdf_marks_every_finding_on_the_page(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample["id"]), (ROOT / f"samples/pdf/{sample['id']}.pdf").open("rb") as handle:
                uploaded = self.client.post("/api/uploads", files={"file": ("c.pdf", handle, "application/pdf")}).json()
                result = self.review(sample, uploaded["text"], document_id=uploaded["document_id"])
                self.check(sample, result)
                self.assert_marked(result)

    @unittest.skipUnless(ocr_available(), "Tesseract Korean data not installed")
    def test_uploaded_png_marks_every_finding_on_the_page(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample["id"]), (ROOT / f"samples/images/{sample['id']}.png").open("rb") as handle:
                uploaded = self.client.post("/api/uploads", files={"files": ("c.png", handle, "image/png")}).json()
                for page in uploaded["reading"]["pages"]:
                    page["confirmed"] = True
                result = self.review(sample, uploaded["text"], reading=uploaded["reading"], document_id=uploaded["document_id"])
                self.assertCountEqual([f["issue_type"] for f in result["review"]["findings"]], sample["expected"]["finding_types"])
                self.assert_marked(result)

    def assert_marked(self, result):
        spots = self.client.get(f"/api/analyses/{result['analysis_id']}/document").json()["highlights"]
        for finding in result["review"]["findings"]:
            e = finding["evidence"][0]
            self.assertIn(f"{e['block_id']}:{e['start']}:{e['end']}", spots)


class DocumentDraftTests(unittest.TestCase):
    review = SampleCatalogTests.review

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.client = TestClient(create_app(Path(folder.name) / "drafts.sqlite3"))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        sample = next(s for s in SAMPLES if s["id"] == "employment-cafe")
        self.result = self.review(sample, (ROOT / "samples/employment-cafe.txt").read_text())
        self.base = f"/api/analyses/{self.result['analysis_id']}/drafts"

    def make(self, **body):
        response = self.client.post(self.base, json={"analysis_revision": self.result["analysis_revision"], **body})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_revision_request_pairs_current_and_proposed_wording(self):
        text = self.make(kind="revision_request", incident={"writer": "김서연", "counterparty": "카페 모래내길"}, written_on="2026-11-10", reply_by="2026-11-20")["draft_text"]
        self.assertIn("수신: 카페 모래내길", text)
        self.assertIn("2026년 11월 20일까지", text)
        for finding in self.result["review"]["findings"]:
            self.assertIn(unmarked(finding["evidence"][0]["quote"]), text)
            self.assertIn(finding["revision_suggestion"], text)

    def test_only_selected_clauses_are_included(self):
        first, second, *_ = self.result["review"]["findings"]
        for kind in ("revision_request", "request", "summary", "lawyer_request"):
            with self.subTest(kind=kind):
                text = self.make(kind=kind, finding_ids=[first["finding_id"]])["draft_text"]
                self.assertIn(unmarked(first["evidence"][0]["quote"]), text)
                self.assertNotIn(unmarked(second["evidence"][0]["quote"]), text)

    def test_documents_hold_values_not_form_lines_or_internal_notes(self):
        for kind in ("summary", "request", "revision_request", "lawyer_request"):
            with self.subTest(kind=kind):
                document = self.make(kind=kind)
                self.assertNotRegex(document["draft_text"], r"검토 메모|작성 메모|\n- 근로시간: 4\.")
                self.assertTrue(document["review_note"])
        self.assertIn("- 지급일: 매월 25일", self.make(kind="summary")["draft_text"])

    def test_quotes_drop_list_markers(self):
        text = self.make(kind="revision_request")["draft_text"]
        self.assertIn("현재 문구: “수습기간 1개월은", text)
        self.assertNotIn("“- ", text)

    def test_pdf_export_keeps_korean_text_across_pages(self):
        text = "계약 수정 요청서\n\n1. 수정을 요청하는 조항\n" + "\n".join(f"- 근로자의 실수로 발생한 손해 {n}번 항목 & <확인>" for n in range(120))
        response = self.client.post("/api/documents/pdf", json={"title": "요청서", "text": text})
        self.assertEqual(response.headers["content-type"], "application/pdf")
        with fitz.open(stream=response.content, filetype="pdf") as pdf:
            self.assertGreater(len(pdf), 1)
            extracted = "".join(page.get_text() for page in pdf)
        self.assertIn("계약 수정 요청서", extracted)
        self.assertIn("119번 항목 & <확인>", extracted)
