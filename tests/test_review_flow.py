import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from mvp.analysis import extract, evaluate
from mvp.app import create_app
from mvp.chat import answer_question
from mvp.documents import draft
from mvp.review import semantic_review
from mvp.schemas import AnalyzeRequest, ChatRequest, DraftRequest, IncidentFacts
from mvp.store import Store, StaleRevision

ROOT = Path(__file__).resolve().parents[1]


def review(text, contract_type="employment", role=None, complete=True, reading=None):
    request = AnalyzeRequest(text=text, contract_type=contract_type, user_role=role, context={"document_complete": complete, "event_date": "2026-10-10"}, reading=reading)
    blocks, terms, metadata = extract(request)
    return evaluate(request, blocks, terms, metadata, "fixture", 1)


class ReviewTests(unittest.TestCase):
    def test_normal_complete_contract_is_clear_but_blank_form_is_not(self):
        good = review((ROOT / "samples/employment-basic.txt").read_text())
        missing = review((ROOT / "samples/employment-missing.txt").read_text())
        self.assertEqual(good["review"]["verdict"], "clear")
        self.assertEqual(good["review"]["findings"], [])
        self.assertEqual(missing["review"]["verdict"], "needs_information")

    def test_ordinary_deposit_return_is_not_a_warning(self):
        normal = review((ROOT / "samples/lease-basic.txt").read_text(), "lease")
        conditional = review((ROOT / "samples/lease-return.txt").read_text(), "lease")
        self.assertEqual(normal["review"]["verdict"], "clear")
        self.assertEqual(conditional["review"]["verdict"], "warning")
        finding = conditional["review"]["findings"][0]
        self.assertEqual(finding["issue_type"], "deposit_return")
        self.assertIn("통제", finding["why_unfavorable"])
        self.assertTrue(finding["source_ids"])
        self.assertIn("새 임차인", finding["evidence"][0]["quote"])

    def test_same_lease_is_reviewed_from_the_selected_party(self):
        text = (ROOT / "samples/lease-return.txt").read_text()
        result = review(text, "lease", "landlord")
        self.assertNotIn("deposit_return", [f["issue_type"] for f in result["review"]["findings"]])
        with self.assertRaises(ValueError):
            AnalyzeRequest(text=text, contract_type="lease", user_role="worker")

    def test_repair_registration_and_noncompete_burdens_have_original_evidence(self):
        text = (ROOT / "samples/lease-basic.txt").read_text() + "\n특약: 노후로 인한 모든 수리비는 임차인이 부담한다.\n특약: 임차인은 전입신고를 하지 않는다."
        result = review(text, "lease")
        self.assertTrue({"repair_burden", "registration_waiver"} <= {f["issue_type"] for f in result["review"]["findings"]})
        for finding in result["review"]["findings"]:
            for e in finding["evidence"]:
                b = next(b for b in result["blocks"] if b["block_id"] == e["block_id"])
                self.assertEqual(b["text"][e["start"]:e["end"]], e["quote"])
        work = review((ROOT / "samples/employment-basic.txt").read_text() + "\n퇴사 후 동종 업계에 취업을 금지한다.")
        self.assertIn("noncompete", [f["issue_type"] for f in work["review"]["findings"]])

    def test_negations_and_mixed_sentences_do_not_hide_a_separate_burden(self):
        text = (ROOT / "samples/employment-basic.txt").read_text() + "\n위약금은 정하지 않는다. 실수로 발생한 손해는 급여에서 공제한다."
        result = review(text)
        types = [f["issue_type"] for f in result["review"]["findings"]]
        self.assertNotIn("penalty", types)
        self.assertIn("wage_deduction", types)
        lease = review((ROOT / "samples/lease-basic.txt").read_text()+"\n전입신고를 금지하지 않는다. 모든 수리비를 임차인이 부담하지 않는다.", "lease")
        self.assertEqual(lease["review"]["findings"], [])

    def test_ocr_and_partial_document_cannot_get_a_clean_summary(self):
        text = (ROOT / "samples/employment-basic.txt").read_text()
        for args in ({"complete": False}, {"reading": {"methods": ["ocr"], "ocr_used": True}}):
            self.assertEqual(review(text, **args)["review"]["verdict"], "needs_information")

    def test_special_employment_form_is_not_clear_before_additional_validation(self):
        text = (ROOT / "samples/employment-basic.txt").read_text().replace("표준근로계약서", "단시간 근로계약서")
        result = review(text)
        self.assertEqual(result["review"]["verdict"], "needs_information")
        self.assertTrue(any("근로일별" in reason for reason in result["review"]["pending_reasons"]))

    def test_separately_paid_allowances_are_not_flagged_as_included(self):
        text = (ROOT / "samples/employment-basic.txt").read_text()+"\n연장근로수당은 월급에 포함하지 않고 별도로 지급한다."
        result = review(text)
        self.assertNotIn("included_allowance", [i["issue_type"] for i in result["issues"]])
        self.assertEqual(result["review"]["verdict"], "clear")

    def test_commercial_lease_cannot_be_declared_clear_under_housing_criteria(self):
        text = (ROOT / "samples/lease-basic.txt").read_text().replace("주택 임대차계약서", "상가 임대차계약서")
        result = review(text, "lease")
        self.assertEqual(result["review"]["verdict"], "needs_information")
        self.assertFalse(any(s.get("law_title") == "주택임대차보호법" for s in result["sources"]))

    def test_sale_advance_payment_warns_buyer_and_not_seller(self):
        text = "부동산 매매계약서\n목적물: 가상시 가상로 10\n매매대금: 3억원\n잔금 지급일: 2026-11-01\n소유권 이전: 잔금 전액 지급 후 소유권 이전 등기를 한다."
        buyer, seller = review(text, "sale", "buyer"), review(text, "sale", "seller")
        self.assertEqual(buyer["structured_contract"]["price"]["amount"], 300000000)
        self.assertIn("sale_advance", [f["issue_type"] for f in buyer["review"]["findings"]])
        self.assertNotIn("sale_advance", [f["issue_type"] for f in seller["review"]["findings"]])

    def test_real_estate_labels_without_values_are_not_complete_terms(self):
        lease = review("주택 임대차계약서\n보증금: 1000만원\n월세: 50만원\n임대차기간: 2026-10-10 ~ 2028-10-09\n목적물:\n보증금 반환 조건: 미정", "lease")
        sale = review("부동산 매매계약서\n매매대금: 3억원\n목적물:\n잔금 지급일:\n소유권 이전:", "sale")
        for result in (lease, sale):
            self.assertEqual(result["review"]["verdict"], "needs_information")
            address = next(t for t in result["terms"] if t["key"] == "address")
            self.assertEqual(address["status"], "not_found")

    def test_semantic_review_accepts_source_bound_burden_and_rejects_invention(self):
        blocks = [{"block_id": "B0001", "page": 1, "text": "특약: 계약 상대방은 임차인의 동의 없이 보증금 반환일을 변경할 수 있다."}]
        row = {"block_id": "B0001", "quote": blocks[0]["text"], "title": "반환일을 일방 변경", "why_unfavorable": "임차인이 돈을 받는 날짜를 계획하기 어렵습니다.", "scenario": "이사 전에 돈을 못 받을 수 있습니다.", "revision_suggestion": "반환일 변경은 양측 서면 합의로 한다."}
        with patch("mvp.review.generate", return_value=({"complete": True, "findings": [row, {**row, "quote": "없는 문구를 새로 만든 것"}]}, "fixture")):
            output = semantic_review(blocks, "lease", "tenant")
        self.assertEqual(len(output["findings"]), 1)
        self.assertFalse(output["complete"])
        self.assertEqual(output["rejected_candidates"], 1)

    def test_consultation_letter_uses_the_problem_clause_and_stated_goal(self):
        result = review((ROOT / "samples/lease-return.txt").read_text(), "lease")
        document = draft(result, "lawyer_request", IncidentFacts(summary="계약 종료가 다가와서 보증금 반환일을 서면으로 확인하고 싶습니다.", desired_outcome="특약 삭제 협의를 도와주세요."))
        self.assertIn("새 임차인", document["draft_text"])
        self.assertIn("특약 삭제 협의", document["draft_text"])
        self.assertTrue(any(f["origin"] == "user_reported" for f in document["facts_used"]))

    def test_complaint_does_not_turn_contract_sum_into_an_actual_loss(self):
        result = review((ROOT / "samples/lease-return.txt").read_text(), "lease")
        document = draft(result, "complaint", IncidentFacts(summary="계약 종료 전에 반환 계획을 물었지만 상대방이 답변하지 않고 있습니다."))
        self.assertNotIn("1억원", document["draft_text"])
        self.assertIn("현재 미확정", document["draft_text"])
        self.assertIn("실제로 지급하거나 잃은 금액", document["draft_text"])
        self.assertFalse(any(f["origin"] == "document" for f in document["facts_used"]))
        with self.assertRaises(ValueError):
            DraftRequest(analysis_revision=1, kind="complaint")

    def test_custom_chat_rejects_fabricated_sources(self):
        result = review((ROOT / "samples/lease-return.txt").read_text(), "lease")
        body = ChatRequest(analysis_revision=1, question="정확히 어떤 뜻이야?", finding_id="R001")
        with patch("mvp.chat.generate", return_value=({"answer": "이해를 돕는 답변입니다.", "evidence_ids": ["B9999"], "source_ids": []}, "fixture")):
            with self.assertRaises(ValueError):
                answer_question(result, body, [])

    def test_uncited_known_ids_do_not_become_ai_citations(self):
        result = review((ROOT / "samples/lease-return.txt").read_text(), "lease")
        body = ChatRequest(analysis_revision=1, question="무엇을 준비할까?")
        source_id = result["sources"][0]["source_id"]
        with patch("mvp.chat.generate", return_value=({"answer": "반환 요청과 지급 내역을 서면으로 정리하세요.", "evidence_ids": [], "source_ids": [source_id], "citations": []}, "fixture")):
            answer = answer_question(result, body, [])
        self.assertEqual(answer["source_ids"], [])
        self.assertEqual(answer["citations"], [])
        self.assertEqual(answer["uncited_source_ids"], [source_id])


class ConversationAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"db.sqlite3"
        self.client = TestClient(create_app(self.path))
        self.client.__enter__()
        sample = self.client.get("/api/samples/lease-return").json()
        response = self.client.post("/api/analyses", json={k: sample[k] for k in ("title", "text", "contract_type", "context")})
        self.id = response.json()["analysis_id"]
        for _ in range(100):
            result = self.client.get(f"/api/analyses/{self.id}").json()
            if result["status"] in {"completed", "awaiting_input"}:
                break
            time.sleep(.01)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_explanation_history_persists_and_new_revision_has_its_own_thread(self):
        payload = {"analysis_revision": 1, "question": "쉽게 설명해줘", "finding_id": "R001", "intent": "explain"}
        response = self.client.post(f"/api/analyses/{self.id}/chat", json=payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("새 임차인", response.json()["turn"]["answer"]["text"])
        self.assertEqual(len(Store(self.path).chat(self.id, 1)), 1)
        self.client.post(f"/api/analyses/{self.id}/answers", json={"analysis_revision": 1, "context": {"move_in": True}})
        self.assertEqual(self.client.get(f"/api/analyses/{self.id}/chat?analysis_revision=1").status_code, 409)
        self.assertEqual(self.client.get(f"/api/analyses/{self.id}/chat?analysis_revision=2").json()["turns"], [])

    def test_late_chat_cannot_resurrect_deleted_analysis(self):
        def delete_while_answering(*args):
            self.client.app.state.store.delete(self.id)
            return {"text": "late", "evidence": [], "source_ids": []}
        with patch("mvp.app.answer_question", side_effect=delete_while_answering):
            response = self.client.post(f"/api/analyses/{self.id}/chat", json={"analysis_revision": 1, "question": "어떤 뜻이야?"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.app.state.store.chat(self.id, 1), [])

    def test_custom_answer_uses_previous_conversation_and_saves_valid_evidence(self):
        self.client.post(f"/api/analyses/{self.id}/chat", json={"analysis_revision": 1, "question": "쉽게 설명해줘", "finding_id": "R001", "intent": "explain"})
        result = self.client.get(f"/api/analyses/{self.id}").json()
        block = result["review"]["findings"][0]["evidence"][0]["block_id"]
        with patch("mvp.chat.generate", return_value=({"answer": "새 임차인을 구할 때까지 반환을 기다릴 수 있다는 의미입니다.", "evidence_ids": [block], "source_ids": []}, "fixture")) as generate:
            response = self.client.post(f"/api/analyses/{self.id}/chat", json={"analysis_revision": 1, "question": "그럼 그동안 기다려야 하는 거야?", "finding_id": "R001"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("쉽게 설명해줘", generate.call_args.args[1])
        self.assertEqual(len(self.client.app.state.store.chat(self.id, 1)), 2)

    def test_standalone_complaint_uses_only_supplied_facts_and_is_not_saved(self):
        incident = {"summary": "10월 초 온라인 거래에서 물품을 보내겠다는 말을 듣고 돈을 보냈으나 아직 물품을 받지 못했습니다.", "loss": "실제로 이체한 35만원", "evidence": "입금 내역과 대화 캡처"}
        response = self.client.post("/api/drafts", json={"kind": "complaint", "incident": incident})
        self.assertEqual(response.status_code, 200)
        document = response.json()
        self.assertIn(incident["summary"], document["draft_text"])
        self.assertIn("35만원", document["draft_text"])
        self.assertIn("죄명", document["missing_fields"][-3])
        self.assertEqual(len(self.client.get("/api/analyses").json()), 1)

    def test_delete_removes_saved_conversation(self):
        self.client.post(f"/api/analyses/{self.id}/chat", json={"analysis_revision": 1, "question": "쉽게 설명해줘", "finding_id": "R001", "intent": "explain"})
        self.assertEqual(self.client.delete(f"/api/analyses/{self.id}").status_code, 204)
        self.assertEqual(self.client.app.state.store.chat(self.id, 1), [])


if __name__ == "__main__":
    unittest.main()
