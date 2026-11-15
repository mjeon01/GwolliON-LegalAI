"""외국인 표준근로계약서 (별지 제6호서식) reading and checks, and the Korean–Spanish guide."""
from pathlib import Path
import unittest

from backend import foreign_form, spanish_guide
from backend.extraction import blocks_from_text

ROOT = Path(__file__).resolve().parents[1]
CORRECT = ROOT / "mvp_pdf/외국인_표준근로계약서_올바른_작성본.pdf"
WRONG = ROOT / "mvp_pdf/외국인_표준근로계약서_틀린_작성본.pdf"
# The 14 errors the wrong sample's answer key lists, as finding types (lodging and signature each cover one row).
EXPECTED = {"foreign_identity", "foreign_period", "foreign_probation_wage", "foreign_workplace", "foreign_job", "foreign_hours",
            "foreign_overtime", "foreign_break", "foreign_holiday", "foreign_minimum_wage", "foreign_payday", "foreign_custody",
            "foreign_lodging", "foreign_signature"}

FORM = """■ 외국인근로자의 고용 등에 관한 법률 시행규칙 [별지 제6호서식]
표준근로계약서
Standard Labor Contract
성명 Name of the employee  KIM (킴)       생년월일 Birthdate  {birth}
1. 근로계약기간        - 신규 또는 재입국자: ( {months} ) 개월
* 수습기간: [  ]활용(입국일부터 [  ]1개월 [  ]2개월 [  ]3개월 [ ]개월) [✓]미활용
2. 근로장소     {place}
- 직무내용: {job}
4. 근로시간         {hours}
- 1일 평균 시간외 근로시간: 1 시간(사업장 사정에 따라 변동 가능: 2 시간 이내)
5. 휴게시간      1일 {rest} 분
6. 휴일        [✓]일요일 [✓]공휴일([✓]유급 [ ]무급)
1) 월 통상임금 ( {wage} )원
- 기본급[( 월, 시간, 일, 주)급] ( {wage} )원
8. 임금지급일    매월 ( 10 )일 또는 매주 (  )요일.
9. 지급방법        [ ]직접 지급, [✓]통장 입금
{note}
※ 사용자는 근로자 명의로 된 예금통장 및 도장을 관리해서는 안 됨.
12.         이 계약에서 정하지 않은 사항은 「근로기준법」에서 정하는 바에 따른다.
2026 년 11 월 13 일   (  26/11/13   ) (YY/MM/DD)
사용자 Employer : 김민준     김민준 (서명 또는 인 / signature)
근로자 Employee : KIM          (서명 또는 인 / signature)      Kim"""


def form(**values):
    defaults = {"birth": "1999. 04. 12.", "months": 36, "place": "부산광역시 강서구 미래산단로 123", "job": "프레스기 소재 투입",
                "hours": "08:30 ~ 17:30", "rest": 60, "wage": "2,156,880", "note": ""}
    return blocks_from_text(FORM.format(**{**defaults, **values}))


def kinds(blocks):
    return {f["kind"] for f in foreign_form.check(foreign_form.parse(blocks))}


class ForeignFormTests(unittest.TestCase):
    def test_a_correct_form_has_no_findings(self):
        self.assertEqual(kinds(form()), set())

    def test_each_error_is_found_from_its_own_line(self):
        cases = {"foreign_identity": {"birth": ""}, "foreign_period": {"months": 60},
                 "foreign_workplace": {"place": "본사 및 대표자가 지정하는 협력업체 현장"},
                 "foreign_job": {"job": "생산직 및 기타 회사가 지시하는 업무 일체"},
                 "foreign_minimum_wage": {"wage": "2,060,740"},
                 "foreign_custody": {"note": "※ 근로자 명의 통장·도장 및 여권은 이탈 방지를 위해 회사가 보관함"}}
        for kind, values in cases.items():
            with self.subTest(kind):
                self.assertEqual(kinds(form(**values)), {kind})
        self.assertEqual(kinds(form(hours="08:00 ~ 19:00", rest=30)), {"foreign_hours", "foreign_break", "foreign_overtime"})

    def test_the_printed_rule_against_holding_bank_books_is_not_a_finding(self):
        self.assertNotIn("custody", foreign_form.parse(form()))

    def test_other_contracts_are_not_read_as_the_form(self):
        self.assertIsNone(foreign_form.parse(blocks_from_text("근로계약서\n근로시간: 09:00~18:00")))

    def test_form_values_fill_the_contract_terms(self):
        terms = foreign_form.terms(foreign_form.parse(form()))
        self.assertEqual(terms["wage"][0]["normalized_value"], {"amount": 2156880, "currency": "KRW", "period": "month"})
        self.assertEqual(terms["period"][0]["normalized_value"]["months"], 36)
        self.assertIn("annual_leave", terms)


@unittest.skipUnless(CORRECT.is_file() and WRONG.is_file(), "demo PDFs not present")
class DemoPdfTests(unittest.TestCase):
    def analyze(self, path):
        from backend.analysis import evaluate, extract
        from backend.reading import read_document
        from backend.schemas import AnalyzeRequest
        request = AnalyzeRequest(text=read_document(path.read_bytes(), ".pdf")["text"], title=path.stem, contract_type="employment",
                                 user_role="worker", engine="rules", evidence_mode="local")
        return evaluate(request, *extract(request), "test", 1)

    def test_the_correct_sample_is_clear(self):
        result = self.analyze(CORRECT)
        self.assertEqual(result["review"]["findings"], [])
        self.assertEqual([i["issue_type"] for i in result["issues"]], ["review_scope"])

    def test_the_wrong_sample_shows_all_fourteen_errors(self):
        result = self.analyze(WRONG)
        self.assertEqual({f["issue_type"] for f in result["review"]["findings"]}, EXPECTED)


class SpanishGuideTests(unittest.TestCase):
    def test_guide_is_complete(self):
        guide = spanish_guide.load()
        self.assertEqual((len(guide["glossary"]), len(guide["checklist"])), (50, 15))
        self.assertTrue(guide["comparisons"] and guide["help"])

    def test_longest_term_wins_and_qualifiers_do_not_flip_meaning(self):
        line = spanish_guide.glossary_line(["공휴일을 무급으로 정했고 기본급이 최저임금보다 적습니다."])
        self.assertIn("최저임금=salario mínimo", line)
        self.assertNotIn("임금=Salario /", line)
        self.assertIn("공휴일=días festivos oficiales", line)
        self.assertNotIn("remunerados", line)

    def test_paired_names_stay_paired(self):
        line = spanish_guide.glossary_line(["지방노동청에 신고"])
        self.assertIn("지방노동청=Oficina regional de trabajo", line)

    def test_explanations_bring_the_checklist_for_each_finding(self):
        context = spanish_guide.explanation_context(["여권"], ["foreign_custody"])
        self.assertEqual({c["id"] for c in context["checklist"]} >= {12, 13}, True)

    def test_half_translated_lines_are_rejected_but_names_may_stay_korean(self):
        from backend.auto_translation import half_translated
        self.assertTrue(half_translated("※ 근로자 명의 통장·도장 및 여권은 회사가 보관함", "※ Trabajador 명의 통장·도장 및 여권은 회사가 보관함"))
        self.assertFalse(half_translated("사용자 Employer : 박상철 (서명 또는 인)", "Empleador: 박상철 (firma o sello)"))

    def test_translation_prompt_carries_the_glossary(self):
        from backend.translation import translated_fields
        prompts = []

        def run_model(schema, prompt, **kwargs):
            prompts.append(prompt)
            raise RuntimeError("stop")

        with self.assertRaises(RuntimeError):
            translated_fields({"a": "기본급이 최저임금보다 적습니다."}, "es", run_model=run_model)
        self.assertIn("최저임금=salario mínimo", prompts[0])


if __name__ == "__main__":
    unittest.main()


class StandaloneDraftTests(unittest.TestCase):
    def test_documents_need_no_contract(self):
        from backend.documents import draft
        facts = {"writer": "홍길동", "summary": "9월부터 일했는데 10월 월급 1,200,000원을 아직 못 받았습니다.", "loss": "10월 임금 1,200,000원"}
        petition = draft(None, "labor_petition", facts, written_on="2026-11-15")
        self.assertEqual(petition["title"], "진정서 (임금체불 등)")
        self.assertIn("10월 임금 1,200,000원", petition["draft_text"])
        self.assertIn("2026년 11월 15일", petition["draft_text"])
        self.assertEqual(draft(None, "complaint", facts)["title"], "고소장 초안")

    def test_a_petition_needs_the_facts(self):
        from backend.documents import draft
        with self.assertRaises(ValueError):
            draft(None, "labor_petition", {"summary": "짧음"})


class FilingTests(unittest.TestCase):
    PERSON = {"name": "홍길동", "address": "서울특별시 마포구 월드컵로 10", "phone": "010-1234-5678", "written_on": "2026-11-15"}
    FACTS = "9월 1일부터 일했는데 시급 9천원만 받았고 10월 월급은 아직 못 받았습니다."

    def petition(self, **extra):
        from backend.filings import build
        data = {**self.PERSON, "company": "행복편의점", "employer": "김사장", "company_address": "서울특별시 마포구 망원로 20",
                "start_date": "2026-09-01", "job": "계산", "unpaid": "10월 임금 1,200,000원", "facts": self.FACTS, **extra}
        return build("labor_petition", data, run_model=extra.pop("run_model", None) or (lambda *a, **k: ({"text": ""}, "x")))

    def test_a_petition_is_complete_with_no_blanks_or_notes(self):
        text = self.petition()["text"]
        self.assertTrue(text.startswith("진 정 서"))
        self.assertNotIn("[", text)
        self.assertNotIn("작성 전 확인", text)
        self.assertIn("2026. 9. 1. ~ 현재(재직 중)", text)
        self.assertTrue(text.endswith("관할 지방고용노동청장 귀하"))

    def test_missing_required_fields_are_named(self):
        from backend.filings import FilingError, build
        with self.assertRaisesRegex(FilingError, "사업장명"):
            build("labor_petition", {**self.PERSON, "facts": self.FACTS})

    def test_a_rewrite_with_a_new_number_is_rejected(self):
        from backend.filings import polish
        invented = lambda *a, **k: ({"text": "진정인은 2025. 1. 1.부터 근무하였습니다."}, "x")
        self.assertEqual(polish("labor_petition", self.FACTS, invented), self.FACTS)
        spelled = lambda *a, **k: ({"text": "진정인은 9월 1일부터 근무하며 시급 9,000원을 받았고 10월 임금을 받지 못하였습니다."}, "x")
        self.assertIn("9,000원", polish("labor_petition", self.FACTS, spelled))

    def test_the_pdf_keeps_the_closing_together(self):
        from backend.pdf_export import line_kind
        self.assertEqual([line_kind(l) for l in ["2026년 11월 15일", "위 진정인  홍길동  (서명 또는 인)", "서울서부지방고용노동청장 귀하"]],
                         ["date", "sign", "addressee"])
