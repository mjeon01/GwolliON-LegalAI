"""Clause dataset, metrics, classifier serving, remedy routes, risk scoring and the scenario harness.

Uses small synthetic AI Hub-shaped archives; never the downloaded data or a locally trained model.
"""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from backend.agent.remedies import AGENCIES, REMEDIES
from backend.agent.tools import Toolbox
from backend.agent.verify import verify
from backend.clause_labels import model_input, normalize_labels, normalize_text
from backend.clause_model import ClauseModel, RemoteClauseModel, classify, load
from scripts.ml import build_clause_dataset, evaluate_risk, train_clause
from scripts.ml.common import metrics, tune_thresholds
from scripts.ml.risk import combined, rule_hits

CLAUSES = [
    ("제1조(임금)", "임금", "월 급여는 [값]원으로 하며 매월 25일 지급한다."),
    ("제2조(근로시간)", "근로 시간", "근로시간은 09시부터 18시까지로 한다."),
    ("제3조(위약금)", "손해배상의 예정", "근로자가 1년 이내 퇴사하면 위약금 300만원을 지급한다."),
]


def document(name, variant, form="근로(고용)계약서"):
    sections = [{"format": {"is_article_title": False}, "content": {"description": "근로계약서", "content_labels": ["기타"]}}]
    for title, label, text in CLAUSES:
        sections.append({"format": {"is_article_title": True}, "content": {"description": title, "content_labels": [label]}})
        sections.append({"format": {"is_article_title": False}, "content": {"description": f"{text} ({variant}) (@성명1)", "content_labels": [label]}})
    if variant < 3:  # A label too rare to learn.
        sections.append({"format": {"is_article_title": False}, "content": {"description": f"희귀 조항 {variant}", "content_labels": ["희귀"]}})
    return {"document": {"metadata": {"file_info": {"document_name": name, "document_category": {"detail_category": form}}}, "sections": sections}}


def archive(root, split, docs):
    folder = root / split / "02.라벨링데이터"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / f"T_인사_고용_노무_고용계약.zip", "w") as z:
        for i, doc in enumerate(docs):
            z.writestr(f"{i}.json", json.dumps(doc, ensure_ascii=False))


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        training = [document(f"근로계약서_{i:03d}", i) for i in range(40)] + [document("연봉_000", 0, form="연봉계약서"), document("기타계약", 0, form="각서")]
        archive(self.root / "data", "Training", training)
        # One validation document copies a training document and must not reach the test split.
        archive(self.root / "data", "Validation", [document("검증_001", 1001), document("검증_복제", 3)])
        self.card = build_clause_dataset.build(self.root / "data", self.root / "out", min_examples=20)

    def rows(self, split):
        return [json.loads(line) for line in (self.root / "out" / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_splits_are_by_document_and_test_excludes_training_copies(self):
        docs = {split: {r["doc_id"] for r in self.rows(split)} for split in ("train", "dev", "test")}
        self.assertFalse(docs["train"] & docs["dev"])
        self.assertEqual(docs["test"], {"검증_001"})
        self.assertEqual(self.card["documents"]["test_excluded_as_training_duplicate"], 1)
        self.assertNotIn("기타계약", docs["train"] | docs["dev"])

    def test_labels_are_normalized_and_rare_ones_dropped(self):
        self.assertEqual(json.loads((self.root / "out/labels.json").read_text()), ["근로 시간", "손해배상의 예정", "임금"])
        self.assertIn("희귀", self.card["dropped_rare_labels"])
        row = next(r for r in self.rows("train") if "위약금 300만원" in r["text"])
        self.assertEqual((row["title"], row["labels"]), ("제3조(위약금)", ["손해배상의 예정"]))
        self.assertNotIn("(@", row["text"])
        self.assertEqual(next(r for r in self.rows("train") if r["text"] == "근로계약서")["labels"], [])

    def test_baseline_trains_serves_and_classifies_contract_lines(self):
        train_clause.train_baseline(self.root / "out", self.root / "out/baseline")
        model = ClauseModel(self.root / "out/baseline")
        self.assertEqual(model.predict([{"text": "퇴사하면 위약금 300만원을 지급한다.", "title": ""}]), [["손해배상의 예정"]])
        blocks = [{"block_id": "B0001", "text": "제5조(위약금)"}, {"block_id": "B0002", "text": "중도 퇴사 시 위약금 300만원을 지급한다."}]
        found = classify(blocks, "employment", model)
        self.assertEqual(found["blocks"][1]["risk_candidates"], ["penalty"])
        self.assertIn("휴일", found["missing_required"])
        self.assertIsNone(classify(blocks, "lease", model))


class HelperTests(unittest.TestCase):
    def test_label_and_text_normalization(self):
        self.assertEqual(normalize_labels(["비밀 유지", "기타", "비밀 유지 의무"]), ["비밀 유지 의무"])
        self.assertEqual(normalize_text("성명 : (@성명1)\n  주소"), "성명 : [값] 주소")
        self.assertEqual(model_input("본문", "제1조"), "제1조 || 본문")
        self.assertEqual(model_input("본문", "제1조", with_context=False), "본문")

    def test_metrics_and_thresholds(self):
        result = metrics([["a"], ["a", "b"], []], [["a"], ["a"], ["b"]], ["a", "b"])
        self.assertEqual((result["micro"]["tp"], result["micro"]["fp"], result["micro"]["fn"]), (2, 1, 1))
        self.assertEqual(result["per_label"]["b"]["f1"], 0.0)
        # Never below 0.5, even when a lower threshold has the best dev F1.
        probs, gold = [[0.3]] * 5 + [[0.2]], [["a"]] * 5 + [[]]
        self.assertEqual(tune_thresholds(probs, gold, ["a"]), [0.5])
        # Raised above 0.5 when that removes false alarms.
        probs, gold = [[0.9]] * 5 + [[0.6]] * 3, [["a"]] * 5 + [[]] * 3
        self.assertEqual(tune_thresholds(probs, gold, ["a"]), [0.65])
        # Too few dev positives to tune: stays 0.5.
        self.assertEqual(tune_thresholds([[0.9], [0.6]], [["a"], []], ["a"]), [0.5])

    def test_missing_model_and_off_switch(self):
        self.assertIsNone(load("/nonexistent/model"))
        with patch.dict("os.environ", {"GWOLLION_CLAUSE_MODEL": "off"}):
            load.cache_clear()
            self.assertIsNone(load())
        load.cache_clear()


class RemoteModelTests(unittest.TestCase):
    blocks = [{"block_id": "B0001", "text": "제5조(위약금)"}, {"block_id": "B0002", "text": "중도 퇴사 시 위약금 300만원을 지급한다."}]

    def remote(self, handler):
        import httpx
        return RemoteClauseModel("https://space.example/", token="hf_x", transport=httpx.MockTransport(handler), key="k1")

    def test_remote_labels_feed_the_same_burden_filter(self):
        import httpx
        seen = {}

        def handler(request):
            seen.update(path=request.url.path, auth=request.headers.get("authorization"), key=request.headers.get("x-api-key"),
                        body=json.loads(request.content))
            return httpx.Response(200, json={"model": "v2", "labels": [["손해배상의 예정"], ["손해배상의 예정"]]})

        found = classify(self.blocks, "employment", self.remote(handler))
        self.assertEqual((seen["path"], seen["auth"], seen["key"]), ("/classify", "Bearer hf_x", "k1"))
        self.assertEqual(seen["body"]["rows"][1], {"text": "중도 퇴사 시 위약금 300만원을 지급한다.", "title": "제5조(위약금)"})
        self.assertEqual((found["model"], found["kind"]), ("v2", "remote"))
        self.assertEqual(found["blocks"][1]["risk_candidates"], ["penalty"])

    def test_failing_or_malformed_server_falls_back_to_rules(self):
        import httpx
        for handler in (lambda r: httpx.Response(503, text="sleeping"),
                        lambda r: httpx.Response(200, json={"labels": [["a"]]}),
                        lambda r: httpx.Response(200, text="not json")):
            self.assertIsNone(classify(self.blocks, "employment", self.remote(handler)))

    def test_url_setting_selects_the_remote_model(self):
        with patch.dict("os.environ", {"GWOLLION_CLAUSE_MODEL_URL": "https://space.example", "GWOLLION_CLAUSE_MODEL_TOKEN": "t",
                                       "GWOLLION_CLAUSE_MODEL_KEY": "k"}):
            load.cache_clear()
            model = load()
            self.assertIsInstance(model, RemoteClauseModel)
            self.assertEqual((model.url, model.token, model.key), ("https://space.example", "t", "k"))
        load.cache_clear()


class AgentConnectionTests(unittest.TestCase):
    def test_classify_tool_uses_the_analysis_result(self):
        result = {"contract_type": "employment", "blocks": [{"block_id": "B0001", "page": 1, "text": "퇴사 시 위약금 300만원"}], "sources": [],
                  "extraction": {"clause_model": {"model": "v2", "kind": "transformer", "missing_required": ["휴일"], "note": "n",
                                                  "blocks": [{"block_id": "B0001", "labels": ["손해배상의 예정"], "risk_candidates": ["penalty"]}]}}}
        found = Toolbox(result, {}, []).run("classify_clauses", {})
        self.assertEqual((found["burden_candidates"][0]["text"], found["missing_required"]), ("퇴사 시 위약금 300만원", ["휴일"]))
        self.assertFalse(Toolbox(None, {}, []).run("classify_clauses", {})["available"])

    def test_remedy_routes_make_their_statutes_citable(self):
        box = Toolbox(None, {}, [])
        route = box.run("remedy_guide", {"issue_type": "unpaid_wage"})
        self.assertIn("국번 없이 1350", [a["contact"] for a in route["agencies"]])
        self.assertTrue(all(law["found"] for law in route["laws"]))
        answer = {"answer": "x", "answer_ko": "근로기준법 제49조에 따라 임금채권은 3년 안에 행사해야 할 수 있어 확인이 필요합니다.", "evidence_block_ids": [], "citations": []}
        self.assertEqual(verify(answer, box)[1], [])
        self.assertFalse(box.run("remedy_guide", {"issue_type": "unknown"})["found"])

    def test_every_route_cites_only_listed_articles_and_known_agencies(self):
        for key, entry in REMEDIES.items():
            cited = {n for text in entry["deadlines"] for n in re.findall(r"제(\d+)조", text)}
            self.assertLessEqual(cited, {n for _, n in entry["laws"]}, key)
            self.assertTrue(set(entry["agencies"]) <= set(AGENCIES), key)


class RiskTests(unittest.TestCase):
    def test_model_adds_only_inherent_burdens(self):
        self.assertEqual(rule_hits("근로자가 중도 퇴사하면 위약금 300만원을 지급한다."), ["penalty"])
        self.assertEqual(combined("회사는 필요에 따라 근무지를 변경할 수 있다.", ["근로 환경 변경"]), ["unilateral_change"])
        self.assertEqual(combined("근로시간은 09시부터 18시까지로 한다.", ["근로 시간"]), [])

    def test_model_burden_needs_supporting_wording(self):
        penalty, noncompete, change = ["손해배상의 예정"], ["경업 및 겸직금지의무"], ["근로 환경 변경"]
        self.assertEqual(combined("위반 시 급여 총액의 3배를 위약벌로 지급한다.", penalty), ["penalty"])
        self.assertEqual(combined("귀국 시 2개월 분의 급여를 배상하여야 한다.", penalty), ["penalty"])
        self.assertEqual(combined("근로자는 실손해액을 배상하여야 한다.", penalty), [])
        self.assertEqual(combined("제14조 (손해배상)", penalty), [])
        self.assertEqual(combined("퇴사 후 1년간 경쟁업체에 취업하지 않는다.", noncompete), ["noncompete"])
        self.assertEqual(combined("재직 중 승인 없이 타 업무에 종사하여서는 아니 된다.", noncompete), [])
        self.assertEqual(combined("회사는 근무 장소를 변경할 수 있으며, 사원이 동의할 경우에만 가능하다.", change), [])
        self.assertEqual(combined("회사는 근로자의 동의 없이 근무 장소를 변경할 수 있다.", change), ["unilateral_change"])

    def test_scoring_skips_unreviewed_rows_and_rejects_unknown_ids(self):
        rows = [{"text": "중도 퇴사하면 위약금 300만원을 지급한다.", "model_types": "손해배상의 예정", "gold_risk": "penalty"},
                {"text": "근로시간은 09시부터 18시까지로 한다.", "model_types": "근로 시간", "gold_risk": "none"},
                {"text": "회사는 근무지를 변경할 수 있다.", "model_types": "근로 환경 변경", "gold_risk": "unilateral_change"},
                {"text": "미검수", "model_types": "", "gold_risk": ""}]
        report = evaluate_risk.score(rows)
        self.assertEqual((report["reviewed"], report["skipped_unreviewed"]), (3, 1))
        self.assertEqual(report["systems"]["rules"]["micro"]["recall"], 0.5)
        self.assertEqual(report["systems"]["model_and_rules"]["micro"]["recall"], 1.0)
        self.assertEqual(report["systems"]["model_and_rules"]["false_alarm_rate"], 0.0)
        with self.assertRaises(ValueError):
            evaluate_risk.parse("illegal")

    def test_scoring_reports_each_source(self):
        rows = [{"source": "samples", "text": "중도 퇴사하면 위약금 300만원을 지급한다.", "model_types": "", "gold_risk": "penalty"},
                {"source": "aihub_test", "text": "퇴사 후 2년간 동종업계 취업을 금지한다.", "model_types": "경업 및 겸직금지의무", "gold_risk": "noncompete"},
                {"source": "aihub_test", "text": "근로자는 실손해액을 배상한다.", "model_types": "손해배상의 예정", "gold_risk": "none"}]
        parts = evaluate_risk.score(rows)["by_source"]
        self.assertEqual((parts["samples"]["reviewed"], parts["aihub_test"]["risky_clauses"]), (1, 1))
        self.assertEqual(parts["aihub_test"]["systems"]["model_and_rules"]["false_alarm_rate"], 0.0)


class ScenarioHarnessTests(unittest.TestCase):
    def test_dry_run_scores_every_scenario(self):
        from scripts.ml import eval_agent_scenarios as harness
        with patch.object(harness, "classify", return_value=None):
            report = harness.dry_run(harness.load())
        self.assertEqual({s["id"] for s in report["scenarios"]}, {"foreign_worker_b_zh", "foreign_worker_b_es", "first_job_tenant", "jeonse_fraud"})
        self.assertEqual(report["summary"]["passed_turns"], report["summary"]["turns"])

    def test_checks_catch_wrong_language_and_definitive_claims(self):
        from scripts.ml.eval_agent_scenarios import check
        turn = {"steps": [], "answer": {"text": "이건 사기죄입니다.", "text_ko": "이건 사기죄입니다.", "evidence": [], "ask": {"question": ""}, "warnings": []}}
        checks = check(turn, {"language": "zh", "tools_all": ["remedy_guide"]}, {}, {})
        self.assertEqual((checks["language"], checks["tools_all"], checks["no_forbidden"]), (False, False, False))


if __name__ == "__main__":
    unittest.main()
