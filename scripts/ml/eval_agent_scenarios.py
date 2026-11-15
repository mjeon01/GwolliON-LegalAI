#!/usr/bin/env python3
"""Run the user scenarios (tests/fixtures/scenarios) through the agent and score every turn.

  .venv/bin/python scripts/ml/eval_agent_scenarios.py            # real OpenAI calls (GWOLLION_AI_PROVIDER=openai)
  .venv/bin/python scripts/ml/eval_agent_scenarios.py --dry-run  # scripted model: checks the harness only, no cost

Checks per turn: required tools, response language, cited contract text, facts recorded, a question
back when expected, required mentions (e.g. contacts) and forbidden phrasings (definitive verdicts,
duty reversals). Writes var/evaluation/agent-scenarios.{json,md}.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.agent.runner import run_turn
from backend.analysis import evaluate, extract
from backend.clause_model import classify
from backend.schemas import AnalyzeRequest

SCENARIOS = ROOT / "tests/fixtures/scenarios"
OUT = ROOT / "var/evaluation"
DEFINITIVE = re.compile(r"(?:불법|위법|무효|사기(?:죄)?|범죄)(?:입니다|이다|예요|이에요|에\s*해당합니다|가\s*성립합니다)")


def language_of(text):
    hangul, han = len(re.findall(r"[가-힣]", text)), len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-záéíóúñ]", text))
    return max((("ko", hangul), ("zh", han), ("es", latin)), key=lambda x: x[1])[0]


def case(scenario):
    if scenario["mode"] == "interview":
        return {"id": scenario["id"], "mode": f"interview:{scenario['contract_type']}:{scenario['user_role']}", "facts": {}, "turns": [], "analysis_id": None}, None
    text = (ROOT / scenario["contract"]).read_text(encoding="utf-8")
    request = AnalyzeRequest(title=scenario["title"], text=text, contract_type=scenario["contract_type"], user_role=scenario["user_role"], engine="rules")
    blocks, terms, extraction = extract(request)
    extraction["clause_model"] = classify(blocks, scenario["contract_type"])
    return {"id": scenario["id"], "mode": "contract", "facts": {}, "turns": [], "analysis_id": scenario["id"]}, evaluate(request, blocks, terms, extraction, scenario["id"], 1)


def check(turn, expect, facts_before, facts_after):
    answer, tools = turn["answer"], [s["tool"] for s in turn["steps"]]
    text = answer["text"] + "\n" + answer["text_ko"]
    checks = {}
    if expect.get("tools_all"):
        checks["tools_all"] = all(t in tools for t in expect["tools_all"])
    if expect.get("tools_any"):
        checks["tools_any"] = any(t in tools for t in expect["tools_any"])
    if expect.get("language"):
        checks["language"] = language_of(answer["text"]) == expect["language"]
    if expect.get("evidence"):
        checks["evidence"] = bool(answer["evidence"])
    if expect.get("facts_min"):
        checks["facts_recorded"] = len(facts_after) - len(facts_before) >= expect["facts_min"] or len(facts_after) >= expect["facts_min"]
    if expect.get("asks"):
        checks["asks_back"] = bool(answer["ask"]["question"])
    if expect.get("mentions_any"):
        checks["mentions"] = any(m in text for m in expect["mentions_any"])
    checks["no_forbidden"] = not any(re.search(p, text) for p in expect.get("forbidden", [])) and not DEFINITIVE.search(answer["text_ko"])
    checks["verifier_clean"] = not answer["warnings"]
    return checks


def run(scenarios, on_turn=None):
    results = []
    for scenario in scenarios:
        session, result = case(scenario)
        turns = []
        for spec in scenario["turns"]:
            before = dict(session["facts"])
            started = time.monotonic()
            calls = {"n": 0}
            from backend import openai_client
            original = openai_client.call

            def counted(*args, **kwargs):
                calls["n"] += 1
                return original(*args, **kwargs)

            try:
                with patch("backend.agent.runner.openai_client.call", side_effect=counted):
                    turn, facts = run_turn(session, result, spec["message"], scenario["language"])
                error = None
            except Exception as exc:  # A failed turn is a result, not a crash of the evaluation.
                turn, facts, error = None, session["facts"], f"{type(exc).__name__}: {exc}"
            seconds = round(time.monotonic() - started, 1)
            if turn:
                session["turns"].append(turn)
                session["facts"] = facts
            checks = check(turn, spec["expect"], before, facts) if turn else {"completed": False}
            entry = {"message": spec["message"], "checks": checks, "passed": all(checks.values()), "error": error, "seconds": seconds,
                     "model_calls": calls["n"], "tools": [s["tool"] for s in turn["steps"]] if turn else [],
                     "answer": turn["answer"]["text"] if turn else "", "answer_ko": turn["answer"]["text_ko"] if turn else "",
                     "ask": turn["answer"]["ask"]["question"] if turn else "", "citations": len(turn["answer"]["citations"]) if turn else 0,
                     "warnings": turn["answer"]["warnings"] if turn else [], "revised": turn["answer"]["revised"] if turn else False}
            turns.append(entry)
            if on_turn:
                on_turn(scenario, entry)
        results.append({"id": scenario["id"], "title": scenario["title"], "persona": scenario["persona"], "language": scenario["language"],
                        "turns": turns, "passed_turns": sum(t["passed"] for t in turns)})
    every = [t for r in results for t in r["turns"]]
    names = sorted({k for t in every for k in t["checks"]})
    summary = {"turns": len(every), "passed_turns": sum(t["passed"] for t in every),
               "check_pass_rate": {k: round(sum(t["checks"][k] for t in every if k in t["checks"]) / sum(k in t["checks"] for t in every), 3) for k in names},
               "mean_model_calls": round(sum(t["model_calls"] for t in every) / len(every), 2) if every else 0,
               "mean_seconds": round(sum(t["seconds"] for t in every) / len(every), 1) if every else 0,
               "revised_share": round(sum(t["revised"] for t in every) / len(every), 3) if every else 0}
    return {"created_at": datetime.now(timezone.utc).isoformat(), "summary": summary, "scenarios": results}


def markdown(report, model):
    s = report["summary"]
    lines = [f"# 에이전트 시나리오 평가", "", f"- 실행: {report['created_at'][:19]}Z, 모델: {model}",
             f"- 통과한 턴: {s['passed_turns']}/{s['turns']}, 턴당 모델 호출 평균 {s['mean_model_calls']}회, 평균 {s['mean_seconds']}초, 검증 후 재작성 비율 {s['revised_share']:.0%}", "",
             "| 확인 항목 | 통과율 |", "| --- | --- |"] + [f"| {k} | {v:.0%} |" for k, v in s["check_pass_rate"].items()]
    for scenario in report["scenarios"]:
        lines += ["", f"## {scenario['title']} ({scenario['passed_turns']}/{len(scenario['turns'])})", "", f"{scenario['persona']}", ""]
        for i, t in enumerate(scenario["turns"], 1):
            failed = [k for k, v in t["checks"].items() if not v]
            lines += [f"**{i}. {t['message']}**", "", f"- 결과: {'통과' if t['passed'] else '실패 — ' + ', '.join(failed)}" + (f" ({t['error']})" if t["error"] else ""),
                      f"- 도구: {', '.join(t['tools']) or '없음'} · 모델 호출 {t['model_calls']}회 · {t['seconds']}초 · 확인된 인용 {t['citations']}건",
                      f"- 답변(한국어): {t['answer_ko'][:300]}" + (f"\n- 되물음: {t['ask']}" if t["ask"] else ""), ""]
    return "\n".join(lines)


def scripted(payload, purpose=None):
    """--dry-run model: call each offered tool the scenario needs once, then answer in the requested language."""
    items = payload["input"]
    request = next(json.loads(i["content"].split("\n", 1)[1]) for i in reversed(items) if isinstance(i, dict) and i.get("role") == "user" and i["content"].startswith("USER MESSAGE"))
    done = [i for i in items if isinstance(i, dict) and i.get("type") == "function_call"]
    offered = {t["name"] for t in payload["tools"]}
    wanted = [n for n in scripted.plan.get(request["message"], []) if n in offered]
    if payload["tool_choice"] != "none" and len(done) < len(wanted):
        name = wanted[len(done)]
        args = {"remedy_guide": {"issue_type": "unpaid_wage"}, "minimum_wage_check": {"year": 2026, "amount": 9000, "period": "hourly", "weekly_hours": 40, "daily_hours": None},
                "read_contract": {"block_ids": ["B0001"], "keyword": None}, "lookup_law": {"law_title": "근로기준법", "article_number": "17"},
                "record_fact": {"key": "note", "value": request["message"][:20], "user_quote": request["message"][:12]}}.get(name, {})
        return {"status": "completed", "output": [{"type": "function_call", "name": name, "arguments": json.dumps(args, ensure_ascii=False), "call_id": f"c{len(done)}"}]}, "dry-run"
    text = {"Simplified Chinese": "请先确认合同条款。可以拨打1350咨询。", "Spanish": "Revise primero la cláusula. Puede llamar al 1350."}.get(request["language"], "조항을 먼저 확인하세요. 1350, 임차권등기, 전세피해지원센터에 상담할 수 있습니다.")
    answer = {"answer": text, "answer_ko": "조항을 먼저 확인하세요. 1350, 임차권등기, 전세피해지원센터에 상담할 수 있습니다.", "evidence_block_ids": ["B0001"] if "read_contract" in offered else [], "citations": [],
              "ask": {"question": "전입신고를 했나요?", "question_ko": "전입신고를 했나요?", "options": ["예", "아니오"]}, "next_action": "consult"}
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(answer, ensure_ascii=False)}]}]}, "dry-run"


scripted.plan = {}


def load(only=None):
    scenarios = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(SCENARIOS.glob("*.json"))]
    return [s for s in scenarios if not only or s["id"] in only]


def dry_run(scenarios):
    scripted.plan = {t["message"]: list(dict.fromkeys(t["expect"].get("tools_all", []) + t["expect"].get("tools_any", [])[:1] + (["record_fact"] if t["expect"].get("facts_min") else [])))
                     for s in scenarios for t in s["turns"]}
    with patch("backend.openai_client.call", side_effect=scripted):
        return run(scenarios)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", nargs="*", help="scenario ids")
    args = parser.parse_args()
    scenarios = load(args.only)
    if args.dry_run:
        report, model = dry_run(scenarios), "dry-run (scripted)"
    else:
        from backend.openai_client import require_key
        model = require_key()[1]
        report = run(scenarios, on_turn=lambda s, t: print(f"[{s['id']}] {'PASS' if t['passed'] else 'FAIL'} {t['message'][:30]} tools={t['tools']}", flush=True))
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "-dry-run" if args.dry_run else ""
    (OUT / f"agent-scenarios{suffix}.json").write_text(json.dumps({**report, "model": model}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / f"agent-scenarios{suffix}.md").write_text(markdown(report, model), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
