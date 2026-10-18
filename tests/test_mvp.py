import json
from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter, PdfReader

from mvp.analysis import extract, evaluate
from mvp.app import create_app
from mvp.documents import draft, translate
from mvp.extraction import blocks_from_text, money_value, ollama_extract, rules_extract, assemble_terms
from mvp.schemas import AnalyzeRequest
from mvp.store import Store

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = json.loads((ROOT / "samples/manifest.json").read_text())


def analyze_sample(id, context=None):
    sample = next(s for s in SAMPLES if s["id"] == id)
    request = AnalyzeRequest(title=sample["title"], text=(ROOT / "samples" / f"{id}.txt").read_text(), contract_type=sample["contract_type"], context=context if context is not None else sample["context"])
    blocks, terms, extraction = extract(request)
    return evaluate(request, blocks, terms, extraction, "fixture", 1)


class ExtractionTests(unittest.TestCase):
    def test_six_scenarios_and_document_evidence(self):
        for sample in SAMPLES:
            with self.subTest(sample=sample["id"]):
                result = analyze_sample(sample["id"])
                fields = {t["key"]: t for t in result["terms"]}
                expected = sample["expected"]
                if "wage_status" in expected:
                    self.assertEqual(fields["wage"]["status"], expected["wage_status"])
                for key in ["wage", "deposit"]:
                    if key in expected:
                        self.assertEqual(fields[key]["candidates"][0]["normalized_value"]["amount"], expected[key])
                self.assertEqual(set(expected["issue_types"]), {i["issue_type"] for i in result["issues"]})
                blocks = {b["block_id"]: b for b in result["blocks"]}
                for term in result["terms"]:
                    for candidate in term["candidates"]:
                        e = candidate["evidence"]
                        self.assertEqual(blocks[e["block_id"]]["text"][e["start"]:e["end"]], e["quote"])
                        self.assertIn(candidate["value_text"], e["quote"])
                ids = {s["source_id"] for s in result["sources"]}
                for issue in result["issues"]:
                    self.assertTrue(set(issue["source_ids"]) <= ids)
                self.assertTrue(all("OC=" not in s["official_url"] for s in result["sources"]))
                self.assertTrue(all("/LSW/lsInfoP.do" in s["official_url"] for s in result["sources"] if s.get("kind", "law") == "law"))

    def test_money_units_zero_and_invalid(self):
        for raw, value in [("250만원",2500000),("1억 2천만원",120000000),("2,500,000원",2500000),("0원",0),("12.5만원",125000)]:
            self.assertEqual(money_value(raw),value)
        for raw in ["원", "-100원", "abc원", "0.5원"]:
            with self.assertRaises(ValueError):
                money_value(raw)

    def test_adjacent_amounts_and_wage_periods(self):
        blocks = blocks_from_text("보증금: 1000만원, 월세: 50만원\n시급: 12000원, 연봉: 3000만원\n퇴사 시 위약금 500만원")
        lease = rules_extract(blocks,"lease")
        work = rules_extract(blocks,"employment")
        self.assertEqual(lease["deposit"][0]["normalized_value"]["amount"],10000000)
        self.assertEqual(lease["rent"][0]["normalized_value"]["amount"],500000)
        self.assertEqual([c["normalized_value"]["period"] for c in work["wage"]],["hour","year"])
        self.assertEqual(len(work["wage"]),2)

    def test_historical_event_stays_unverified(self):
        result = analyze_sample("employment-attention",{"event_date":"2025-01-01","document_complete":True,"workplace_size":"5plus","weekly_work_hours":45})
        for issue in result["issues"]:
            if issue["source_ids"]:
                self.assertEqual(issue["status"],"insufficient_evidence")
                self.assertFalse(issue["validation"]["version_applicable"])

    def test_negated_penalty_is_not_flagged(self):
        text = "월급: 250만원\n위약금은 정하지 않는다."
        r=AnalyzeRequest(text=text)
        b,t,e=extract(r)
        result=evaluate(r,b,t,e,"test",1)
        self.assertNotIn("penalty",[i["issue_type"] for i in result["issues"]])

    def test_hallucinated_and_misbound_model_terms_are_rejected(self):
        blocks=blocks_from_text("월급: 250만원, 위약금: 300만원\n보증금: 1000만원")
        rows=[{"key":"wage","value_text":"999만원","block_id":"B0001"},
              {"key":"wage","value_text":"300만원","block_id":"B0001"},
              {"key":"wage","value_text":"1000만원","block_id":"B0002"},
              {"key":"wage","value_text":"250만원","block_id":"B0001"}]
        with patch("mvp.extraction.generate",return_value=({"terms":rows},"fixture-model")):
            found,model,rejected=ollama_extract(blocks,"employment")
        self.assertEqual(rejected,3)
        self.assertEqual(len(found["wage"]),1)
        self.assertEqual(found["wage"][0]["normalized_value"]["amount"],2500000)

    def test_model_full_wage_clause_is_bound_to_its_amount(self):
        blocks = blocks_from_text("- 월급 : 2,500,000원")
        rows = [{"key":"wage","value_text":"- 월급 : 2,500,000원","block_id":"B0001"}]
        with patch("mvp.extraction.generate",return_value=({"terms":rows},"fixture-model")):
            found,_,rejected = ollama_extract(blocks,"employment")
        self.assertEqual(rejected,0)
        self.assertEqual(found["wage"][0]["value_text"],"2,500,000원")
        self.assertEqual(found["wage"][0]["normalized_value"]["period"],"month")

    def test_unknown_wage_unit_needs_confirmation(self):
        r=AnalyzeRequest(text="급여: 250만원\n근무장소: 가상회사 사무실")
        b,t,e=extract(r)
        result=evaluate(r,b,t,e,"test",1)
        self.assertIn("wage_period",[i["issue_type"] for i in result["issues"]])

    def test_successful_model_omissions_are_supplemented_with_named_provenance(self):
        r = AnalyzeRequest(text=(ROOT / "samples/employment-basic.txt").read_text(),engine="ollama")
        with patch("mvp.extraction.generate",return_value=({"terms":[]},"fixture-model")), patch("mvp.review.semantic_review",return_value={"method":"ollama","complete":True,"findings":[],"rejected_candidates":0}):
            b,t,e = extract(r)
        self.assertEqual(e["method"], "ollama_with_form_rules")
        self.assertGreater(e["form_rule_candidates_added"],0)
        wage = next(term for term in t if term["key"] == "wage")
        self.assertEqual(wage["candidates"][0]["extraction_method"],"form_rules")
        self.assertEqual(wage["candidates"][0]["normalized_value"]["amount"],2500000)

    def test_model_short_break_value_is_bound_to_correct_label(self):
        blocks=blocks_from_text("근로시간: 8시간, 휴게시간: 1시간")
        rows=[{"key":"break_time","value_text":"1시간","block_id":"B0001"}, {"key":"break_time","value_text":"8시간","block_id":"B0001"}]
        with patch("mvp.extraction.generate",return_value=({"terms":rows},"fixture-model")):
            found,_,rejected=ollama_extract(blocks,"employment")
        self.assertEqual(rejected,1)
        self.assertEqual(found["break_time"][0]["normalized_value"],{"minutes":60})

    def test_draft_does_not_choose_conflicting_wage(self):
        result=analyze_sample("employment-conflict")
        document=draft(result,"request")
        self.assertTrue(document["review_required"])
        self.assertFalse(any(f["label"]=="임금" for f in document["facts_used"]))
        self.assertIn("[직접 입력]",document["draft_text"])
        self.assertIn("임금",document["missing_fields"])
        self.assertIsNone(result["structured_contract"]["wage"]["amount"])

    def test_official_form_structures_dates_clocks_and_checked_payment(self):
        result = analyze_sample("employment-basic")
        contract = result["structured_contract"]
        self.assertEqual(contract["contract_period"], {"start": "2026-10-10", "end": "2027-10-09"})
        self.assertEqual(contract["working_hours"]["break"], "12:00~13:00")
        self.assertEqual(contract["working_hours"]["break_minutes"], 60)
        self.assertEqual(contract["wage"]["payment_method"], "bank_transfer")
        self.assertEqual(contract["job_description"], "사무 보조")
        self.assertTrue(all(c["status"] == "confirmed" for c in result["validation_checks"]))

    def test_blank_break_is_not_filled_from_work_clocks(self):
        result = analyze_sample("employment-missing")
        contract = result["structured_contract"]
        self.assertEqual(contract["working_hours"]["start"], "09:00")
        self.assertIsNone(contract["working_hours"]["break_minutes"])
        self.assertIsNone(contract["wage"]["payment_method"])
        absent = {c["field"] for c in result["validation_checks"] if c["status"] == "not_found"}
        self.assertEqual(absent, {"working_hours.break", "wage.payday", "wage.payment_method", "contract_period.end", "annual_leave"})

    def test_indefinite_contract_does_not_require_an_end_date(self):
        sample = (ROOT / "samples/employment-basic.txt").read_text()
        sample = sample.replace("기간의 정함이 있는 경우", "기간의 정함이 없는 경우")
        sample = sample.replace("근로계약기간 : 2026년 10월 10일부터 2027년 10월 09일까지", "근로개시일 : 2026년 10월 10일부터")
        r = AnalyzeRequest(text=sample, context={"document_complete": True})
        b,t,e = extract(r)
        result = evaluate(r,b,t,e,"indefinite",1)
        self.assertFalse(result["structured_contract"]["fixed_term"])
        check = next(c for c in result["validation_checks"] if c["field"] == "contract_period.end")
        self.assertEqual(check["status"], "not_applicable")
        self.assertNotIn("missing_terms", [i["issue_type"] for i in result["issues"]])

    def test_invalid_calendar_and_impossible_workdays_stay_unconfirmed(self):
        blocks = blocks_from_text("근로계약기간 : 2026년 02월 30일부터 2027년 02월 28일까지\n근무일 : 매주 8일 근무")
        terms = {t["key"]:t for t in assemble_terms(rules_extract(blocks,"employment"),"employment")}
        self.assertEqual(terms["period"]["status"],"not_found")
        self.assertEqual(terms["work_days"]["status"],"not_found")

    def test_language_guides_preserve_candidates_and_source_ids(self):
        result=analyze_sample("employment-attention",{"event_date":"2026-10-10","document_complete":True,"weekly_work_hours":50,"workplace_size":"5plus"})
        for language in ["zh","es"]:
            translated=translate(result,language)
            self.assertTrue(translated["review_required"])
            self.assertFalse(translated["validation"]["meaning_reviewed"])
            for original,local in zip(result["terms"],translated["terms"]):
                self.assertEqual(original["candidates"],local["candidates"])
            for original,local in zip(result["issues"],translated["issues"]):
                self.assertEqual(original["source_ids"],local["source_ids"])
            context={f["key"]:f["raw_value"] for f in translated["context_facts"]}
            self.assertEqual(context["weekly_work_hours"],50)
            self.assertEqual(context["event_date"],"2026-10-10")


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/"test.sqlite3"
        self.client=TestClient(create_app(self.path))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def create(self,id="employment-attention",engine="rules",reading=None):
        sample=self.client.get("/api/samples/"+id).json()
        response=self.client.post("/api/analyses",json={"title":sample["title"],"text":sample["text"],"contract_type":sample["contract_type"],"context":sample["context"],"engine":engine,"reading":reading})
        self.assertEqual(response.status_code,202)
        id=response.json()["analysis_id"]
        for _ in range(100):
            result=self.client.get("/api/analyses/"+id).json()
            if result["status"] not in ["queued","running"]:
                return result
            time.sleep(.01)
        self.fail("Analysis timed out")

    def test_full_revision_draft_language_delete_flow(self):
        result=self.create()
        id=result["analysis_id"]
        self.assertEqual(result["status"],"awaiting_input")
        answer=self.client.post(f"/api/analyses/{id}/answers",json={"analysis_revision":1,"context":{"event_date":"2026-10-10","workplace_size":"5plus","weekly_work_hours":45}})
        self.assertEqual(answer.status_code,200)
        updated=answer.json()
        self.assertEqual(updated["analysis_revision"],2)
        self.assertEqual(updated["context"]["document_complete"],True)
        self.assertEqual(updated["status"],"completed")
        stale=self.client.post(f"/api/analyses/{id}/drafts",json={"analysis_revision":1})
        self.assertEqual(stale.status_code,409)
        for kind in ["summary","request"]:
            d=self.client.post(f"/api/analyses/{id}/drafts",json={"analysis_revision":2,"kind":kind})
            self.assertEqual(d.status_code,200)
            self.assertIn("250만원",d.json()["draft_text"])
        for lang in ["zh","es"]:
            t=self.client.post(f"/api/analyses/{id}/translations",json={"analysis_revision":2,"language":lang})
            self.assertEqual(t.status_code,200)
        self.assertEqual(self.client.delete(f"/api/analyses/{id}").status_code,204)
        self.assertEqual(self.client.get(f"/api/analyses/{id}").status_code,404)
        self.assertEqual(self.client.get("/api/analyses").json(),[])

    def test_ocr_origin_survives_answer_revision(self):
        reading = {"methods":["ocr"],"ocr_used":True,"warnings":["원본과 대조해주세요."]}
        result = self.create(reading=reading)
        self.assertEqual(result["reading"],reading)
        updated = self.client.post(f"/api/analyses/{result['analysis_id']}/answers",json={"analysis_revision":1,"context":{"event_date":"2026-10-10"}}).json()
        self.assertEqual(updated["reading"],reading)

    def test_pdf_upload_all_samples_matches_scenario(self):
        for s in SAMPLES:
            raw=(ROOT/"output/pdf"/(s["id"]+".pdf")).read_bytes()
            response=self.client.post("/api/uploads",files={"file":(s["id"]+".pdf",raw,"application/pdf")})
            self.assertEqual(response.status_code,200)
            r=AnalyzeRequest(text=response.json()["text"],contract_type=s["contract_type"],context=s["context"])
            b,t,e=extract(r);result=evaluate(r,b,t,e,"pdf",1)
            self.assertEqual(set(s["expected"]["issue_types"]),{i["issue_type"] for i in result["issues"]})

    def test_upload_errors(self):
        for name,raw,status in [("bad.jpg",b"image",422),("bad.doc",b"document",415),("bad.pdf",b"not a pdf",422),("bad.txt",b"\xff",422),("short.txt",b"tiny",422),("big.txt",b"a"*(5*1024*1024+1),413)]:
            self.assertEqual(self.client.post("/api/uploads",files={"file":(name,raw)}).status_code,status)
        writer=PdfWriter();writer.add_blank_page(width=595,height=842)
        stream=BytesIO();writer.write(stream)
        with patch("mvp.reading.recognize",return_value=""):
            self.assertEqual(self.client.post("/api/uploads",files={"file":("scan.pdf",stream.getvalue())}).status_code,422)

    def test_photo_and_mixed_pdf_reading_preserves_pages_and_ocr_notice(self):
        import fitz
        from PIL import Image
        photo = BytesIO(); Image.new("RGB",(100,100),"white").save(photo,format="PNG")
        text = "월급: 250만원\n소정근로시간: 09:00~18:00\n휴게시간: 12:00~13:00"
        with patch("mvp.reading.recognize",return_value=text) as recognize:
            response = self.client.post("/api/uploads",files={"file":("photo.png",photo.getvalue())})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()["reading"]["ocr_used"])
        self.assertIn("원본",response.json()["reading"]["warnings"][0])
        source = fitz.open(ROOT / "output/pdf/employment-basic.pdf")
        source.new_page()
        raw = source.tobytes(); source.close()
        with patch("mvp.reading.recognize",return_value=text) as recognize:
            response = self.client.post("/api/uploads",files={"file":("mixed.pdf",raw)})
        self.assertEqual(response.status_code,200)
        payload = response.json()
        self.assertEqual(payload["reading"]["methods"],["pdf_text","ocr"])
        self.assertEqual(payload["pages"],2)
        self.assertEqual(recognize.call_count,1)
        self.assertTrue(payload["text"].split("\f")[1].startswith("월급"))

    def test_missing_ocr_dependency_is_explicit(self):
        from PIL import Image
        photo = BytesIO(); Image.new("RGB",(100,100),"white").save(photo,format="PNG")
        with patch("mvp.reading.ocr_available",return_value=False):
            response = self.client.post("/api/uploads",files={"file":("photo.png",photo.getvalue())})
        self.assertEqual(response.status_code,503)

    def test_schema_and_cross_origin_validation(self):
        self.assertEqual(self.client.post("/api/analyses",json={"text":" "*20}).status_code,422)
        self.assertEqual(self.client.post("/api/analyses",json={"text":"계약서 내용을 입력하는 가상의 테스트 문서입니다.","context":{"document_complete":"true"}}).status_code,422)
        self.assertEqual(self.client.post("/api/analyses",headers={"Origin":"https://unrelated.example"},json={"text":"가상의 계약서 내용을 입력한 테스트 문서입니다."}).status_code,403)
        self.assertEqual(self.client.get("/api/samples/not-real").status_code,404)

    def test_model_error_is_failed_without_rule_fallback(self):
        with patch("mvp.analysis.ollama_extract",side_effect=ValueError("sensitive internal error")):
            result=self.create(engine="ollama")
        self.assertEqual(result["status"],"failed")
        self.assertNotIn("sensitive",result["error"])

    def test_lease_user_unreturned_context(self):
        result=self.create("lease-return")
        id=result["analysis_id"]
        updated=self.client.post(f"/api/analyses/{id}/answers",json={"analysis_revision":1,"context":{"deposit_returned":False,"move_in":True,"resident_registration":True,"event_date":"2026-10-10"}}).json()
        self.assertIn("deposit_unreturned",[i["issue_type"] for i in updated["issues"]])
        d=draft(updated,"summary")
        self.assertTrue(any(f.get("context_key")=="deposit_returned" and f["origin"]=="user_confirmed" for f in d["facts_used"]))


class StoreTests(unittest.TestCase):
    def test_restart_recovers_incomplete_jobs_and_delete_cannot_resurrect(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"db.sqlite3"
            store=Store(path)
            store.create("queued",{"title":"sample"})
            store.create("running",{"title":"sample"})
            self.assertTrue(store.start("running"))
            recovered=Store(path)
            self.assertEqual(recovered.get("queued")["status"],"failed")
            self.assertEqual(recovered.get("running")["status"],"failed")
            recovered.create("deleted",{"title":"sample"})
            recovered.start("deleted"); recovered.delete("deleted")
            recovered.finish("deleted",result={"status":"completed"})
            self.assertIsNone(recovered.get("deleted"))


if __name__=="__main__":
    unittest.main()
