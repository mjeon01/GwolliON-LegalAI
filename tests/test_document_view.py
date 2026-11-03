"""The review viewer must point at the right place in the actual document."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import fitz
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.knowledge import ROOT
from backend.pages import locate, snapshot
from backend.reading import ocr_available


def word(x, y, text):
    return [x, y, x + 0.1, y + 0.02, text]


def wait(client, id):
    for _ in range(200):
        value = client.get(f"/api/analyses/{id}").json()
        if value["status"] not in {"queued", "running"}:
            return value
        time.sleep(0.05)
    raise AssertionError("analysis did not finish")


class LocateTests(unittest.TestCase):
    def test_spacing_differences_still_match_exactly(self):
        words = [word(0.1, 0.1, "특약:"), word(0.2, 0.1, "위약"), word(0.3, 0.1, "금을"), word(0.4, 0.1, "낸다")]
        rects, match = locate("특약: 위약금을 낸다", words)
        self.assertEqual(match, "exact")
        self.assertEqual(len(rects), 1)
        self.assertAlmostEqual(rects[0][2], 0.5)

    def test_clause_across_two_lines_gets_one_rect_per_line(self):
        words = [word(0.1, 0.1, "퇴사하면"), word(0.1, 0.2, "위약금을"), word(0.2, 0.2, "낸다")]
        rects, _ = locate("퇴사하면 위약금을 낸다", words)
        self.assertEqual(len(rects), 2)

    def test_repeated_text_uses_the_requested_occurrence(self):
        words = [word(0.1, 0.1, "동일한"), word(0.2, 0.1, "문구"), word(0.1, 0.5, "동일한"), word(0.2, 0.5, "문구")]
        self.assertAlmostEqual(locate("동일한 문구", words, 1)[0][0][1], 0.5)

    def test_ocr_noise_is_marked_approximate_and_unrelated_text_is_not_matched(self):
        words = [word(0.1, 0.1, "잔금은"), word(0.2, 0.1, "먼저"), word(0.3, 0.1, "지금하고")]
        self.assertEqual(locate("잔금은 먼저 지급하고", words)[1], "approximate")
        self.assertEqual(locate("임차인의 전입신고를 금지한다", words), ([], None))


class DocumentApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        samples = patch("backend.app.SAMPLES_DIR", ROOT / "tests/fixtures/samples")
        samples.start()
        self.addCleanup(samples.stop)
        client = TestClient(create_app(Path(folder.name) / "view.sqlite3"))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.client = client

    def analyze(self, text, contract_type, **extra):
        body = {"title": "t", "text": text, "contract_type": contract_type, **extra}
        response = self.client.post("/api/analyses", json=body)
        self.assertEqual(response.status_code, 202)
        return wait(self.client, response.json()["analysis_id"])

    def test_pdf_upload_highlights_every_finding_on_its_page(self):
        name = ROOT / "tests/fixtures/samples/pdf/lease-burden.pdf"
        with name.open("rb") as handle:
            uploaded = self.client.post("/api/uploads", files={"file": ("lease.pdf", handle, "application/pdf")}).json()
        self.assertTrue(uploaded["document_id"])
        result = self.analyze(uploaded["text"], "lease", document_id=uploaded["document_id"])
        id = result["analysis_id"]
        document = self.client.get(f"/api/analyses/{id}/document").json()
        self.assertEqual(document["pages"][0]["page"], 1)
        findings = result["review"]["findings"]
        self.assertTrue(findings)
        for finding in findings:
            e = finding["evidence"][0]
            spot = document["highlights"][f"{e['block_id']}:{e['start']}:{e['end']}"]
            self.assertEqual(spot["match"], "exact")
            self.assertTrue(all(0 <= v <= 1 for rect in spot["rects"] for v in rect))
        image = self.client.get(f"/api/analyses/{id}/pages/1")
        self.assertEqual(image.headers["content-type"], "image/jpeg")
        self.assertTrue(image.content.startswith(b"\xff\xd8"))
        self.assertEqual(self.client.get(f"/api/analyses/{id}/pages/9").status_code, 404)

    def test_highlight_is_on_the_right_line_of_the_rendered_page(self):
        name = ROOT / "tests/fixtures/samples/pdf/employment-attention.pdf"
        document_id = self.client.post("/api/samples/employment-attention/document").json()["document_id"]
        text = (ROOT / "tests/fixtures/samples/employment-attention.txt").read_text()
        result = self.analyze(text, "employment", document_id=document_id)
        finding = next(f for f in result["review"]["findings"] if f["issue_type"] == "penalty")
        e = finding["evidence"][0]
        spot = self.client.get(f"/api/analyses/{result['analysis_id']}/document").json()["highlights"][f"{e['block_id']}:{e['start']}:{e['end']}"]
        with fitz.open(name) as pdf:
            found = pdf[0].search_for("위약금")[0]
            height = pdf[0].rect.height
        self.assertLess(spot["rects"][0][1], found.y1 / height)
        self.assertGreater(spot["rects"][0][3], found.y0 / height)

    def test_text_input_has_no_page_view_and_old_requests_still_work(self):
        result = self.analyze((ROOT / "tests/fixtures/samples/lease-burden.txt").read_text(), "lease")
        document = self.client.get(f"/api/analyses/{result['analysis_id']}/document").json()
        self.assertEqual(document, {"pages": [], "highlights": {}})
        self.assertEqual(self.client.get(f"/api/analyses/{result['analysis_id']}/pages/1").status_code, 404)

    def test_txt_upload_stores_no_pages(self):
        uploaded = self.client.post("/api/uploads", files={"file": ("a.txt", "계약 내용을 스무 글자가 넘도록 충분히 적은 문서입니다.".encode(), "text/plain")}).json()
        self.assertIsNone(uploaded["document_id"])

    def test_answers_keep_the_document_and_delete_removes_it(self):
        store_document = self.client.post("/api/samples/lease-burden/document").json()["document_id"]
        text = (ROOT / "tests/fixtures/samples/lease-burden.txt").read_text()
        first = self.analyze(text, "lease", document_id=store_document)
        second = self.analyze(text, "lease", document_id=store_document)
        id = first["analysis_id"]
        self.assertEqual(self.client.post(f"/api/analyses/{id}/answers", json={"analysis_revision": 1, "context": {"move_in": True}}).status_code, 200)
        self.assertEqual(len(self.client.get(f"/api/analyses/{id}/document").json()["pages"]), 1)
        self.assertEqual(self.client.delete(f"/api/analyses/{id}").status_code, 204)
        # Still used by another review.
        self.assertEqual(self.client.get(f"/api/analyses/{second['analysis_id']}/pages/1").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/analyses/{second['analysis_id']}").status_code, 204)
        self.assertEqual(self.client.app.state.store.document_pages(store_document), [])

    def test_unattached_pages_expire_but_attached_ones_stay(self):
        store = self.client.app.state.store
        pages = snapshot([((ROOT / "tests/fixtures/samples/pdf/sale-risk.pdf").read_bytes(), ".pdf")])
        orphan, kept = store.save_document(pages), store.save_document(pages)
        self.analyze((ROOT / "tests/fixtures/samples/sale-risk.txt").read_text(), "sale", document_id=kept)
        with store.connect() as db:
            db.execute("UPDATE document_pages SET created_at=datetime('now','-2 day')")
        store.save_document(pages)
        self.assertEqual(store.document_pages(orphan), [])
        self.assertTrue(store.document_pages(kept))

    def test_photo_metadata_and_rotation_are_applied_to_the_stored_copy(self):
        raw = (ROOT / "tests/fixtures/samples/images/sale-risk-1.png").read_bytes()
        upright = snapshot([(raw, ".png")])[0]
        turned = snapshot([(raw, ".png")], [90])[0]
        self.assertEqual((upright["height"], upright["width"]), (turned["width"], turned["height"]))
        self.assertIsNone(upright["words"])

    def test_unreadable_file_is_not_a_page_view(self):
        self.assertEqual(snapshot([(b"not an image", ".png")]), [])

    @unittest.skipUnless(ocr_available(), "Tesseract Korean data not installed")
    def test_photo_ocr_locates_the_clause(self):
        with (ROOT / "tests/fixtures/samples/images/sale-risk-1.png").open("rb") as handle:
            uploaded = self.client.post("/api/uploads", files={"files": ("a.png", handle, "image/png")}).json()
        pages = uploaded["reading"]["pages"]
        for page in pages:
            page["confirmed"] = True
        result = self.analyze(uploaded["text"], "sale", reading=uploaded["reading"], document_id=uploaded["document_id"])
        self.assertTrue(result["review"]["findings"])
        spots = self.client.get(f"/api/analyses/{result['analysis_id']}/document").json()["highlights"]
        e = result["review"]["findings"][0]["evidence"][0]
        self.assertIn(f"{e['block_id']}:{e['start']}:{e['end']}", spots)

    def test_failed_ocr_layout_does_not_block_the_review(self):
        document_id = self.client.app.state.store.save_document(snapshot([((ROOT / "tests/fixtures/samples/images/sale-risk-1.png").read_bytes(), ".png")]))
        with patch("backend.app.ocr_words", return_value=[]):
            result = self.analyze((ROOT / "tests/fixtures/samples/sale-risk.txt").read_text(), "sale", document_id=document_id)
        self.assertTrue(result["review"]["findings"])
        document = self.client.get(f"/api/analyses/{result['analysis_id']}/document").json()
        self.assertEqual(document["highlights"], {})
        self.assertEqual(len(document["pages"]), 1)
