import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mvp.analysis import extract, evaluate
from mvp.corpus import Corpus
from mvp.extraction import blocks_from_text
from mvp.knowledge import Knowledge
from mvp.legal_api import LegalAPI, EvidenceError
from mvp.retrieval import plan, retrieve, validate_citations
from mvp.review import semantic_review, role_reversal, RULES, rule_matches, priority_blocks, clean_revision, unsupported_contract_claim, unsafe_revision
from mvp.schemas import AnalyzeRequest
from scripts.build_reference_index import build


class OfficialEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def api(self, transport):
        return LegalAPI(self.directory / "cache", transport=transport, settings={"legal_api_key": "fixture-secret"})

    def law_fixture(self, body_date="20200101"):
        search = {"LawSearch": {"law": [{"법령명한글": "근로기준법", "법령ID": "001872", "법령일련번호": "100", "시행일자": "20200101"}, {"법령명한글": "근로기준법", "법령ID": "001872", "법령일련번호": "200", "시행일자": "20260101"}]}}
        body = {"법령": {"기본정보": {"법령명_한글": "근로기준법", "법령ID": "001872", "시행일자": body_date}, "조문": {"조문단위": {"조문여부": "조문", "조문번호": "20", "조문키": "0020001", "조문내용": "사용자는 근로계약 불이행에 대한 위약금을 예정하는 계약을 체결하지 못한다."}}}}
        return search, body

    def test_historical_version_is_selected_and_cache_has_no_credential(self):
        search, body = self.law_fixture()
        calls = []
        def transport(endpoint, params, *args):
            calls.append(params)
            return {"ok": True, "payload": body if "MST" in params else search}
        api = self.api(transport)
        source = api.law("근로기준법", "2021-01-01")[0]
        self.assertEqual(calls[-1]["MST"], "100")
        self.assertEqual(source["effective_date"], "2020-01-01")
        self.assertIn("20210101", calls[0]["efYd"])
        api.law("근로기준법", "2021-01-01")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("fixture-secret", "".join(p.read_text() for p in (self.directory / "cache").glob("*.json")))

    def test_mismatched_version_and_http_200_api_error_are_rejected(self):
        search, body = self.law_fixture("20220101")
        api = self.api(lambda endpoint, params, *args: {"ok": True, "payload": body if "MST" in params else search})
        with self.assertRaisesRegex(EvidenceError, "law_version_mismatch"):
            api.law("근로기준법", "2021-01-01")
        api = LegalAPI(self.directory / "other", settings={"legal_api_key": "fixture-secret"}, transport=lambda *args: {"ok": True, "payload": {"Expc": {"resultCode": "99", "resultMsg": "denied"}}})
        with self.assertRaisesRegex(EvidenceError, "api_validation"):
            api.cases("expc", "보증금")

    def test_precedent_body_identity_and_date_are_verified(self):
        search = {"PrecSearch": {"prec": {"판례일련번호": "123", "사건명": "보증금반환", "사건번호": "2020다123", "선고일자": "2020.01.01", "판례상세링크": "/LSW/precInfoP.do?precSeq=123&OC=fixture-secret"}}}
        body = {"PrecService": {"판례정보일련번호": "123", "사건명": "보증금반환", "사건번호": "2020다123", "선고일자": "20200101", "법원명": "대법원", "판결요지": "임대차보증금 반환과 목적물 인도는 동시이행 관계다."}}
        calls = []
        def transport(endpoint, params, *args):
            calls.append(params)
            return {"ok": True, "payload": body if "ID" in params else search}
        source = self.api(transport).cases("prec", "임대차보증금 반환", "2021-01-01")[0]
        self.assertEqual(source["kind"], "precedent")
        self.assertIn("20210101", calls[0]["prncYd"])
        self.assertNotIn("OC", source["official_url"])
        body["PrecService"]["사건번호"] = "other"
        with self.assertRaisesRegex(EvidenceError, "case_identity_mismatch"):
            LegalAPI(self.directory / "mismatch", transport=transport, settings={"legal_api_key": "fixture-secret"}).cases("prec", "임대차보증금 반환")

    def test_live_failure_uses_explicit_fallback_and_prevents_clear(self):
        text = (Path(__file__).resolve().parents[1] / "samples/employment-basic.txt").read_text()
        request = AnalyzeRequest(text=text, evidence_mode="live", context={"document_complete": True})
        with patch("mvp.retrieval.LegalAPI", side_effect=EvidenceError("credential_missing")):
            blocks, terms, metadata = extract(request)
            result = evaluate(request, blocks, terms, metadata, "fixture", 1)
        self.assertTrue(result["grounding"]["failures"])
        self.assertEqual(result["review"]["verdict"], "needs_information")
        self.assertTrue(result["sources"])

    def test_queries_never_contain_contract_or_personal_facts(self):
        request = AnalyzeRequest(text="근로계약서 홍길동 연락처 010-1234-5678\n퇴사하면 위약금 300만원을 지급한다.")
        result = plan(request, blocks_from_text(request.text))
        self.assertEqual(result["public_query"], "근로계약 위약금")
        self.assertNotIn("홍길동", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("010-", json.dumps(result))

    def test_administrative_cases_use_the_public_administrative_topic(self):
        request = AnalyzeRequest(text="상가 임대차 계약\n홍길동의 영업정지 처분 시 임차인이 책임을 부담한다.", contract_type="lease")
        result = plan(request, blocks_from_text(request.text))
        self.assertEqual(result["case_queries"]["decc"], "영업정지")
        self.assertNotIn("홍길동", json.dumps(result, ensure_ascii=False))

    def test_live_selected_law_replaces_local_newer_version(self):
        historical = {"kind": "law", "law_title": "근로기준법", "article_number": "20", "branch_number": "", "effective_date": "2020-01-01", "source_id": "historical", "text": "검증된 과거 조문", "retrieval_method": "live"}
        self.assertEqual(Knowledge(supplemental=[historical]).lookup("근로기준법", 20, "2021-01-01")["source_id"], "historical")
        self.assertIsNone(Knowledge(supplemental=[historical]).lookup("근로기준법", 17, "2021-01-01"))


class GroundedReviewTests(unittest.TestCase):
    def test_wrong_party_and_fabricated_source_quote_are_excluded(self):
        text = "임대인은 임차인의 동의 없이 보증금 반환 예정일을 변경할 수 있다."
        blocks = blocks_from_text(text)
        source = {"source_id": "law-test", "kind": "law", "title": "확인된 근거", "text": "임대차는 임차인이 보증금을 반환받을 때까지 존속하는 것으로 본다.", "version_applicable": True}
        row = {"block_id": "B0001", "quote": text, "title": "반환일 변경", "why_unfavorable": "이사를 계획한 날짜에 보증금을 받지 못할 수 있습니다.", "scenario": "상대방이 날짜를 미루면 반환이 늦어질 수 있습니다.", "revision_suggestion": "반환일은 상호 합의로 변경한다.", "burdened_party": "tenant", "obligation_party": "landlord", "obligation_quote": text, "basis_type": "legal_comparison", "citations": [{"source_id": "law-test", "quote": source["text"]}], "applicability_questions": ["계약 종료일이 언제인가요?"]}
        wrong_party = {**row, "burdened_party": "landlord"}
        with patch("mvp.review.generate", side_effect=[({"complete": True, "findings": [row]}, "fixture"), ({"complete": True, "findings": [row, wrong_party, {**row, "citations": [{"source_id": "law-test", "quote": "원문에 없는 법률 문구"}]}]}, "fixture")]):
            result = semantic_review(blocks, "lease", "tenant", {"sources": [source]})
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["rejected_candidates"], 2)
        self.assertFalse(result["complete"])

    def test_dataset_only_cannot_support_legal_comparison(self):
        supplied = [{"source_id": "dataset", "kind": "dataset", "title": "예시", "text": "위약금 조항에 관한 설명 예시입니다.", "version_applicable": False}]
        self.assertIsNone(validate_citations([{"source_id": "unknown", "quote": supplied[0]["text"]}], supplied))
        self.assertIsNone(validate_citations([{"source_id": "dataset", "quote": "예시를 바꾸어 쓴 가짜 원문"}], supplied))
        self.assertEqual(validate_citations([{"source_id": "dataset", "quote": supplied[0]["text"]}], supplied)[0]["kind"], "dataset")
        text = "임대인은 임차인의 동의 없이 보증금 반환일을 변경할 수 있다."
        row = {"block_id": "B0001", "quote": text, "title": "반환일의 일방 변경", "why_unfavorable": "반환 날짜를 계획하기 어렵습니다.", "scenario": "반환일이 늦어질 수 있습니다.", "revision_suggestion": "반환일 변경은 서면 합의로 한다.", "burdened_party": "tenant", "obligation_party": "landlord", "obligation_quote": text, "basis_type": "legal_comparison", "citations": [{"source_id": "dataset", "quote": supplied[0]["text"]}], "applicability_questions": []}
        with patch("mvp.review.generate", return_value=({"complete": True, "findings": [row]}, "fixture")):
            result = semantic_review(blocks_from_text(text), "lease", "tenant", {"sources": supplied})
        self.assertEqual(result["findings"], [])
        self.assertFalse(result["complete"])

    def test_return_recipient_is_allowed_but_return_duty_flip_is_not(self):
        self.assertFalse(role_reversal("임차인은 보증금을 반환받을 날짜를 서면으로 확인하세요.", "lease", "tenant"))
        self.assertTrue(role_reversal("임차인은 보증금을 반환해야 합니다.", "lease", "tenant"))
        self.assertTrue(role_reversal("임차인은 새 세입자를 구해야 합니다.", "lease", "tenant"))

    def test_sentence_boundaries_preserve_decimal_amounts(self):
        rule = next(r for r in RULES if r[0] == "wage_deduction")
        self.assertTrue(rule_matches("실수로 발생한 손해액 1.5만원은 급여에서 공제한다.", rule[3], rule[0]))
        self.assertTrue(rule_matches("손해를 공제하지 않는다.실수로 발생한 손해는 급여에서 공제한다.", rule[3], rule[0]))

    def test_payday_and_document_provision_are_not_prohibition_or_exemption(self):
        blocks = blocks_from_text("임금지급일 : 매월 25일\n사업주는 서면제공을 완료한다.\n임차인의 전입신고를 금지한다.")
        self.assertEqual([b["block_id"] for b in priority_blocks(blocks)], ["B0003"])

    def test_actual_repeated_rewrite_drops_duplicate_and_unfinished_tail(self):
        text = "임대인은 임차인의 동의 없이 보증금 반환 예정일을 변경할 수 없다. 변경 사유와 시기는 서면으로 합의한다. 변경 사유와 시기는 서면으로 합의한다. 변경 시기"
        self.assertEqual(clean_revision(text), "임대인은 임차인의 동의 없이 보증금 반환 예정일을 변경할 수 없다. 변경 사유와 시기는 서면으로 합의한다.")
        self.assertIn("1.5만원", clean_revision("공제 금액 1.5만원의 사유와 증빙을 확인한다."))

    def test_separate_negotiation_does_not_invent_an_explicit_duty(self):
        row = {"quote": "특약: 반환 지연에 관한 사항은 별도 협의한다.", "why_unfavorable": "협의 의무가 명시되어 있어 임차인의 부담이 될 수 있습니다."}
        self.assertIsNotNone(unsupported_contract_claim(row))
        row["why_unfavorable"] = "반환일이 정해져 있지 않아 보증금을 받을 시점을 계획하기 어렵습니다."
        self.assertIsNone(unsupported_contract_claim(row))

    def test_observed_rewrite_cannot_give_landlord_a_new_unilateral_power(self):
        self.assertIsNotNone(unsafe_revision("보증금 반환 시기는 임대인이 결정하며, 반환 지연 시 임대인이 협의를 주도합니다.", "lease", "tenant"))
        self.assertIsNone(unsafe_revision("임대차 종료 시 목적물 인도와 보증금 반환을 함께 이행하며, 반환일 변경은 상호 서면 합의로 정한다.", "lease", "tenant"))
        self.assertIsNotNone(unsafe_revision("임차인은 보증금을 반환해야 합니다.", "lease", "tenant"))

    def test_revision_requires_clause_text_instead_of_an_example_label(self):
        self.assertIsNotNone(unsafe_revision("반환일 변경은 서면 합의로 한다. 예: '반환일 변경은 서면 합의로 한다.'", "lease", "tenant"))

    def test_failed_replacement_does_not_turn_an_unresolved_risk_into_clear(self):
        text = "임대인은 임차인의 동의 없이 보증금 반환 예정일을 변경할 수 있다."
        row = {"block_id": "B0001", "quote": text, "title": "반환일 변경", "why_unfavorable": "반환이 늦어져 이사 계획에 부담이 생길 수 있습니다.", "scenario": "예정된 이사일에 보증금을 받지 못할 수 있습니다.", "revision_suggestion": "보증금 반환 시기는 임대인이 결정한다."}
        with patch("mvp.review.generate", side_effect=[({"complete": True, "findings": [row]}, "fixture"), ({"complete": True, "findings": []}, "fixture")]):
            result = semantic_review(blocks_from_text(text), "lease", "tenant")
        self.assertEqual(result["findings"], [])
        self.assertFalse(result["complete"])
        self.assertIn("revision_candidate_unresolved", result["rejection_reasons"])

    def test_invented_power_is_rechecked_once_and_never_shown(self):
        text = "계약 해지 기간 : 2026년 10월 10일부터 2027년 10월 09일까지"
        row = {"block_id": "B0001", "quote": text, "title": "계약기간의 일방 변경", "why_unfavorable": "사업주에게 변경 권한이 있어 계획을 세우기 어렵습니다.", "scenario": "사업주가 기간을 변경할 수 있습니다.", "revision_suggestion": "상호 합의로 정한다."}
        with patch("mvp.review.generate", side_effect=[({"complete": True, "findings": [row]}, "fixture"), ({"complete": True, "findings": []}, "fixture")]) as generator:
            result = semantic_review(blocks_from_text(text), "employment", "worker")
        self.assertEqual(generator.call_count, 2)
        self.assertEqual(result["findings"], [])
        self.assertTrue(result["complete"])
        self.assertEqual(result["correction_passes"], 1)
        with patch("mvp.review.generate", return_value=({"complete": True, "findings": [row]}, "fixture")) as generator:
            result = semantic_review(blocks_from_text(text), "employment", "worker")
        self.assertEqual(generator.call_count, 2)
        self.assertEqual(result["findings"], [])
        self.assertFalse(result["complete"])

    def test_no_semantic_candidates_is_a_completed_screen_without_model_call(self):
        with patch("mvp.review.generate") as generator:
            result = semantic_review(blocks_from_text("근로계약기간 : 2026년 10월 10일부터 2027년 10월 09일까지\n임금지급일 : 매월 25일"), "employment", "worker")
        generator.assert_not_called()
        self.assertEqual(result["method"], "candidate_screen")
        self.assertTrue(result["complete"])
        self.assertEqual(result["findings"], [])

    def test_validation_and_exact_training_duplicates_are_never_retrieved(self):
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for split, entries in {"Training": ["고유한 위약금 관련 참고 사례", "중복된 위약금 관련 참고 사례"], "Validation": ["검증 전용 위약금 관련 참고 사례", "중복된 위약금 관련 참고 사례"]}.items():
                path = directory / "data" / split / "판결문.zip"
                path.parent.mkdir(parents=True)
                with zipfile.ZipFile(path, "w") as archive:
                    for index, text in enumerate(entries):
                        archive.writestr(f"{index}.json", json.dumps({"doc_id": str(index), "sentences": [text]}))
            target = directory / "index.sqlite3"
            manifest = build(directory / "data", target)
            found = Corpus(target).search(["위약금"], limit=10)
            self.assertEqual(manifest["records"], 4)
            self.assertEqual(manifest["exact_text_hash_overlap"], 1)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["split"], "Training")
            self.assertIn("고유한", found[0]["text"])


if __name__ == "__main__":
    unittest.main()
