"""Agent loop, verifier, tools and owner-token access. No paid calls: the Responses API is scripted."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.owner_client import OwnerClient

from backend.agent.runner import run_turn
from backend.agent.tools import Toolbox
from backend.agent.verify import verify
from backend.app import create_app
from backend.knowledge import Knowledge, ROOT

ARTICLE_17 = Knowledge().lookup("근로기준법", 17)


def response(*output):
    return {"status": "completed", "output": list(output)}, "scripted-model"


def tool_call(name, args, call_id="c1"):
    return {"type": "function_call", "name": name, "arguments": json.dumps(args, ensure_ascii=False), "call_id": call_id}


def final(answer_ko, citations=(), evidence=(), question=""):
    payload = {"answer": answer_ko, "answer_ko": answer_ko, "evidence_block_ids": list(evidence), "citations": list(citations),
               "ask": {"question": question, "question_ko": question, "options": ["예", "아니오"] if question else []}, "next_action": "none"}
    return {"type": "message", "content": [{"type": "output_text", "text": json.dumps(payload, ensure_ascii=False)}]}


def interview(facts=None, turns=()):
    return {"id": "s", "mode": "interview:employment:worker", "facts": facts or {}, "turns": list(turns), "analysis_id": None}


class RunnerTests(unittest.TestCase):
    def test_tool_result_is_citable_and_a_bad_quote_triggers_one_revision(self):
        quote = ARTICLE_17["text"][10:60]
        script = [response(tool_call("lookup_law", {"law_title": "근로기준법", "article_number": "17"})),
                  response(final("근로기준법 제17조에 따라 서면 교부를 요청할 수 있어 확인이 필요합니다.", [{"source_id": ARTICLE_17["source_id"], "quote": "지어낸 인용 문구입니다"}])),
                  response(final("근로기준법 제17조에 따라 서면 교부를 요청할 수 있어 확인이 필요합니다.", [{"source_id": ARTICLE_17["source_id"], "quote": quote}]))]
        events = []
        with patch("backend.agent.runner.openai_client.call", side_effect=script) as call:
            turn, _ = run_turn(interview(), None, "계약서를 못 받았어요", on_event=lambda *e: events.append(e))
        self.assertEqual(call.call_count, 3)
        self.assertTrue(turn["answer"]["revised"])
        self.assertEqual([c["quote"] for c in turn["answer"]["citations"]], [" ".join(quote.split())])
        self.assertEqual(turn["answer"]["warnings"], [])
        self.assertEqual(turn["steps"][0]["label"], "근로기준법 제17조 확인")
        self.assertIn(("step", {"tool": "lookup_law", "label": "근로기준법 제17조 확인"}), events)
        # The verifier's feedback reached the model as a message, after the tool output.
        self.assertIn("VERIFIER", json.dumps(call.call_args_list[2].args[0]["input"], ensure_ascii=False))

    def test_unrepaired_problems_are_shown_not_hidden(self):
        bad = final("이 조항은 무효입니다. 민법 제103조 때문입니다.")
        with patch("backend.agent.runner.openai_client.call", side_effect=[response(bad), response(bad)]):
            turn, _ = run_turn(interview(), None, "이거 무효야?")
        self.assertIn("무효입니다", turn["answer"]["text_ko"])
        self.assertEqual(len(turn["answer"]["warnings"]), 2)

    def test_step_limit_forces_a_final_answer(self):
        loop = [response(tool_call("calculate", {"expression": "1+1"}, f"c{i}")) for i in range(8)]
        with patch("backend.agent.runner.openai_client.call", side_effect=loop + [response(final("답변입니다."))]) as call:
            turn, _ = run_turn(interview(), None, "계산")
        self.assertEqual(call.call_args_list[-1].args[0]["tool_choice"], "none")
        self.assertEqual(len(turn["steps"]), 8)

    def test_question_back_to_the_user(self):
        with patch("backend.agent.runner.openai_client.call", side_effect=[response(final("시급을 알려주시면 계산해드릴게요.", question="주 15시간 이상 일하나요?"))]):
            turn, _ = run_turn(interview(), None, "최저임금 넘어?")
        self.assertEqual(turn["answer"]["ask"]["options"], ["예", "아니오"])


class ToolTests(unittest.TestCase):
    def test_facts_must_be_quoted_from_the_user(self):
        facts = {}
        box = Toolbox(None, facts, ["시급 9,000원 받기로 했어요"])
        self.assertTrue(box.run("record_fact", {"key": "hourly_wage", "value": "9000", "user_quote": "시급 9,000원"})["saved"])
        self.assertFalse(box.run("record_fact", {"key": "weekly_hours", "value": "40", "user_quote": "주 40시간"})["saved"])
        self.assertEqual(list(facts), ["hourly_wage"])

    def test_contract_request_uses_recorded_facts_and_marks_blanks(self):
        box = Toolbox(None, {"hourly_wage": {"value": "시급 10,320원", "quote": "x"}}, [])
        box.run("draft_contract_request", {})
        self.assertIn("시급 10,320원", box.document["text"])
        self.assertIn("[성명]", box.document["blanks"])

    def test_minimum_wage_matches_the_official_monthly_figure(self):
        result = Toolbox(None, {}, []).run("minimum_wage_check", {"year": 2026, "amount": 2156880, "period": "monthly", "weekly_hours": 40, "daily_hours": None})
        self.assertEqual((result["monthly_paid_hours"], result["monthly_minimum"], result["below_minimum"]), (209, 2156880, False))

    def test_contract_clause_numbers_are_not_mistaken_for_statutes(self):
        _, problems, _ = verify(final("계약서 제3조를 확인하세요.") and {"answer": "a", "answer_ko": "계약서 제3조를 확인하세요.", "evidence_block_ids": [], "citations": []},
                                Toolbox(None, {}, []))
        self.assertEqual(problems, [])


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "agent.sqlite3"
        samples = patch("backend.app.SAMPLES_DIR", ROOT / "tests/fixtures/samples")
        samples.start()
        self.addCleanup(samples.stop)
        self.client = OwnerClient(create_app(self.path))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        sample = self.client.get("/api/samples/employment-attention").json()
        self.id = self.client.post("/api/analyses", json={k: sample[k] for k in ("title", "text", "contract_type")}).json()["analysis_id"]
        for _ in range(200):
            if self.client.get(f"/api/analyses/{self.id}").json()["status"] in {"completed", "awaiting_input"}:
                break
            time.sleep(.01)

    def test_analysis_needs_its_owner_token(self):
        stranger = TestClient(self.client.app)
        self.assertEqual(stranger.get(f"/api/analyses/{self.id}").status_code, 404)
        self.assertEqual(stranger.get(f"/api/analyses/{self.id}", headers={"x-gwollion-token": "guess"}).status_code, 404)
        self.assertEqual(stranger.delete(f"/api/analyses/{self.id}").status_code, 404)
        self.assertEqual(stranger.get("/api/analyses").json(), [])
        self.assertEqual(stranger.get(f"/api/analyses/{self.id}?access={self.client.tokens[self.id]}").status_code, 200)
        self.assertEqual([i["analysis_id"] for i in self.client.get("/api/analyses").json()], [self.id])

    def test_rows_without_owner_are_local_only(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE analyses SET owner_hash=NULL")
        stranger = TestClient(self.client.app)
        self.assertEqual(stranger.get(f"/api/analyses/{self.id}").status_code, 200)
        with patch.object(type(self.client.app.state.store), "shared", True):
            self.assertEqual(stranger.get(f"/api/analyses/{self.id}").status_code, 404)

    def stream(self, session, message):
        with patch("backend.app.require_key"):
            with self.client.stream("POST", f"/api/agent/sessions/{session}/messages", json={"message": message},
                                    headers={"x-gwollion-token": self.client.tokens[session]}) as reply:
                text = "".join(reply.iter_text())
        return [(f.split("\n")[0][7:], json.loads(f.split("\n")[1][6:])) for f in text.split("\n\n") if f.startswith("event:")]

    def test_contract_session_survives_a_review_revision(self):
        owner = {"x-gwollion-token": self.client.tokens[self.id]}
        self.assertEqual(self.client.post("/api/agent/sessions", json={"analysis_id": self.id}, headers={"x-gwollion-token": "guess"}).status_code, 404)
        session = self.client.post("/api/agent/sessions", json={"analysis_id": self.id}, headers=owner).json()
        self.assertEqual(TestClient(self.client.app).get(f"/api/agent/sessions/{session['session_id']}").status_code, 404)
        block = self.client.get(f"/api/analyses/{self.id}").json()["blocks"][0]["block_id"]
        script = [response(tool_call("read_contract", {"block_ids": [block], "keyword": None})),
                  response(final("이 조항을 먼저 확인하세요.", evidence=[block, "B999"]))]
        with patch("backend.agent.runner.openai_client.call", side_effect=script):
            events = self.stream(session["session_id"], "첫 조항이 뭐야?")
        self.assertEqual([e for e, _ in events], ["status", "status", "step", "status", "status", "done"])
        done = events[-1][1]["turn"]
        self.assertEqual([e["block_id"] for e in done["answer"]["evidence"]], [block])
        self.client.post(f"/api/analyses/{self.id}/answers", json={"analysis_revision": 1, "context": {"document_complete": True}})
        again = self.client.post("/api/agent/sessions", json={"analysis_id": self.id}, headers=owner).json()
        self.assertEqual(again["session_id"], session["session_id"])
        self.assertEqual(len(again["turns"]), 1)
        self.client.delete(f"/api/analyses/{self.id}")
        self.assertIsNone(self.client.app.state.store.session(session["session_id"]))

    def test_interview_session_records_facts_and_can_forget_them(self):
        session = self.client.post("/api/agent/sessions", json={"contract_type": "employment", "user_role": "worker"}).json()
        sid = session["session_id"]
        script = [response(tool_call("record_fact", {"key": "hourly_wage", "value": "9000", "user_quote": "시급 9000원"})),
                  response(final("시급 9000원은 2026년 최저임금보다 낮을 수 있어 확인이 필요합니다."))]
        with patch("backend.agent.runner.openai_client.call", side_effect=script):
            events = self.stream(sid, "계약서 없이 시급 9000원 받기로 했어요")
        self.assertEqual(events[-1][1]["facts"]["hourly_wage"]["value"], "9000")
        self.assertEqual(self.client.get(f"/api/agent/sessions/{sid}").json()["mode"], "interview")
        self.assertEqual(self.client.delete(f"/api/agent/sessions/{sid}/facts/hourly_wage").json()["facts"], {})

    def test_agent_needs_openai_mode(self):
        session = self.client.post("/api/agent/sessions", json={}).json()
        with patch("backend.openai_client.ai_provider", return_value="ollama"):
            reply = self.client.post(f"/api/agent/sessions/{session['session_id']}/messages", json={"message": "안녕"})
        self.assertEqual((reply.status_code, reply.json()["code"]), (503, "openai_disabled"))


if __name__ == "__main__":
    unittest.main()
