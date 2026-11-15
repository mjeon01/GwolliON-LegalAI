"""Agent tools. Each returns plain JSON data and registers what the model may later cite."""
import ast
import operator
import re
from datetime import date, timedelta

from backend.agent.remedies import REMEDIES, guide as remedy
from backend.knowledge import Knowledge

LAWS = ["근로기준법", "근로기준법 시행령", "최저임금법", "주택임대차보호법", "민법"]
REFERENCE_KINDS = {"precedent": ["precedent_reference"], "interpretation": ["interpretation_reference"],
                   "decision": ["decision_reference"], "qa": ["qa_example"], "summary": ["summary_example"],
                   "any": ["precedent_reference", "interpretation_reference", "decision_reference", "qa_example", "summary_example"]}
# Hourly minimum wage announced by the Ministry of Employment and Labor (최저임금위원회 의결·고시).
MINIMUM_WAGE = {2023: 9620, 2024: 9860, 2025: 10030, 2026: 10320}
FORMS = ["근로(고용)계약서", "아르바이트계약서", "연봉계약서"]


def function(name, description, properties, required=None):
    return {"type": "function", "name": name, "description": description, "strict": True,
            "parameters": {"type": "object", "properties": properties, "required": required or list(properties), "additionalProperties": False}}


def nullable(kind, **extra):
    return {"type": [kind, "null"], **extra}


def definitions(has_contract):
    tools = [
        function("lookup_law", "Fetch the official text of one statute article, versioned for the case date. Use before stating what a law says.",
                 {"law_title": {"type": "string", "enum": LAWS}, "article_number": {"type": "string", "description": "Digits only, e.g. '17'"}}),
        function("search_law", "Keyword search over the statute index when the article number is unknown.",
                 {"query": {"type": "string", "description": "2-6 Korean keywords"}}),
        function("search_references", "Search AI Hub court decisions, interpretations, Q&A and summaries. These are examples with other facts, never this user's facts or binding law.",
                 {"terms": {"type": "array", "items": {"type": "string"}, "description": "1-4 Korean keywords, 3+ characters each"},
                  "kind": {"type": "string", "enum": list(REFERENCE_KINDS)}}),
        function("typical_clauses", "How often each clause appears in real Korean employment contracts (AI Hub). Use to spot clauses the user's contract or account lacks.",
                 {"form": {"type": "string", "enum": FORMS}}),
        function("similar_clauses", "Excerpts of real employment contracts containing the terms, to compare wording.",
                 {"terms": {"type": "array", "items": {"type": "string"}, "description": "1-3 Korean keywords"}}),
        function("minimum_wage_check", "Compare a wage with the statutory hourly minimum wage. Weekly paid holiday hours are added when weekly hours are 15 or more.",
                 {"year": {"type": "integer"}, "amount": {"type": "number"}, "period": {"type": "string", "enum": ["hourly", "daily", "monthly"]},
                  "weekly_hours": nullable("number"), "daily_hours": nullable("number")}),
        function("calculate", "Evaluate arithmetic (+ - * / parentheses) for money, hours or dates differences.",
                 {"expression": {"type": "string"}}),
        function("record_fact", "Save a fact the USER stated in this conversation (not one from the contract or your inference). user_quote must be copied from the user's own message.",
                 {"key": {"type": "string", "description": "snake_case, e.g. hourly_wage, start_date, weekly_hours, workplace_size, contract_received"},
                  "value": {"type": "string"}, "user_quote": {"type": "string"}}),
        function("remedy_guide", "Remedy route for an issue: concrete steps, agencies with contacts, deadlines and statutes to look up. Use whenever the user asks what to do next or a burden is confirmed.",
                 {"issue_type": {"type": "string", "enum": sorted(REMEDIES)}}),
        function("draft_contract_request", "Prepare a written request asking the employer to deliver a written employment contract, filled from recorded facts. Use when the user has no written contract.", {}),
    ]
    if has_contract:
        tools.insert(1, function("classify_clauses", "Clause types of every contract line from the trained AI Hub clause model, burden candidates to check against the text, and 근로기준법 제17조 required items the contract lacks. Employment contracts only.", {}))
        tools.insert(0, function("read_contract", "Read contract blocks by id, or the blocks containing a keyword.",
                                 {"block_ids": {"type": "array", "items": {"type": "string"}}, "keyword": nullable("string")}))
    return tools


class Toolbox:
    def __init__(self, result, facts, user_messages, corpus_path=None):
        self.result, self.facts, self.user_messages = result, facts, user_messages
        self.blocks = {b["block_id"]: b for b in (result or {}).get("blocks", [])}
        # Everything citable in this run: analysis sources plus whatever tools return.
        self.sources = {s["source_id"]: s for s in (result or {}).get("sources", [])}
        self.knowledge = Knowledge(supplemental=[s for s in self.sources.values() if s.get("kind", "law") == "law"])
        self.corpus_path = corpus_path
        self.document = None

    def case_date(self):
        value = self.facts.get("event_date", {}).get("value") or ((self.result or {}).get("context") or {}).get("event_date")
        return value if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)) else date.today().isoformat()

    def register(self, source, limit=1500):
        self.sources[source["source_id"]] = source
        return {"source_id": source["source_id"], "kind": source.get("kind", "law"), "title": source["title"],
                "text": source["text"][:limit], **({"version_note": source["version_note"]} if source.get("version_note") else {})}

    def run(self, name, args):
        handler = getattr(self, "tool_" + name, None)
        if handler is None:
            return {"error": "unknown_tool"}
        try:
            return handler(**args)
        except (TypeError, ValueError, KeyError, ZeroDivisionError, SyntaxError) as exc:
            return {"error": "invalid_arguments", "detail": type(exc).__name__}

    def tool_read_contract(self, block_ids, keyword):
        picked = [self.blocks[i] for i in block_ids if i in self.blocks]
        if keyword:
            picked += [b for b in self.blocks.values() if keyword in b["text"] and b not in picked]
        return {"blocks": [{"block_id": b["block_id"], "page": b["page"], "text": b["text"]} for b in picked[:10]],
                "note": "" if picked else "일치하는 조항이 없습니다."}

    def tool_lookup_law(self, law_title, article_number):
        number = re.sub(r"\D", "", article_number)
        source = self.knowledge.lookup(law_title, number, self.case_date()) if number else None
        if not source:
            return {"found": False, "note": "색인에 없는 조문입니다. 이 조문 내용을 단정하지 마세요."}
        return {"found": True, "version_applicable": source.get("version_applicable", False), **self.register(source)}

    def tool_search_law(self, query):
        return {"articles": [self.register(a, 600) for a in self.knowledge.search(query[:100], 5) if a["law_title"] in LAWS]}

    def tool_search_references(self, terms, kind):
        from backend.corpus import Corpus
        found = Corpus(self.corpus_path).search(terms[:4], limit=4, kinds=REFERENCE_KINDS[kind], diverse=kind == "any")
        return {"references": [{**self.register(s, 900), "dataset_kind": s.get("dataset_kind")} for s in found],
                "caution": "다른 사건의 자료입니다. 사용자의 사실이나 확정된 법률 판단으로 쓰지 마세요."}

    def tool_typical_clauses(self, form):
        from backend.corpus import typical_clauses
        return typical_clauses(form, self.corpus_path)

    def tool_similar_clauses(self, terms):
        from backend.corpus import similar_clauses
        return {"excerpts": [self.register(s, 700) for s in similar_clauses(terms[:3], self.corpus_path)]}

    def tool_minimum_wage_check(self, year, amount, period, weekly_hours, daily_hours):
        minimum = MINIMUM_WAGE.get(year)
        if minimum is None:
            return {"known": False, "note": f"{year}년 최저임금은 이 도구에 없습니다. 고용노동부 고시를 확인하도록 안내하세요."}
        if period == "daily" and not daily_hours:
            return {"error": "daily_hours_required"}
        if period == "monthly" and not weekly_hours:
            return {"error": "weekly_hours_required"}
        hours = monthly_paid_hours(weekly_hours or 40)
        hourly = amount if period == "hourly" else amount / daily_hours if period == "daily" else amount / monthly_paid_hours(weekly_hours)
        return {"known": True, "year": year, "minimum_hourly": minimum, "computed_hourly": round(hourly), "below_minimum": hourly < minimum,
                "monthly_paid_hours": hours, "monthly_minimum": minimum * hours,
                "assumptions": "월 환산 시간 = (주 소정근로시간 + 주휴시간) × 4.345주, 반올림. 주 15시간 이상이면 주휴시간 포함. 수습 감액·최저임금 산입에서 빠지는 수당·연장수당은 반영하지 않음.",
                "source": "고용노동부 최저임금 고시"}

    def tool_calculate(self, expression):
        return {"expression": expression, "result": arithmetic(expression)}

    def tool_record_fact(self, key, value, user_quote):
        key = re.sub(r"[^a-z0-9_]", "", key.lower())[:40]
        quote = re.sub(r"\s+", " ", user_quote).strip()
        said = [re.sub(r"\s+", " ", m) for m in self.user_messages]
        # The model may only store what the user actually typed; inferred facts are rejected.
        if not key or len(quote) < 2 or not any(quote in m for m in said):
            return {"saved": False, "reason": "user_quote가 사용자의 실제 메시지에 없습니다. 사용자가 말한 사실만 기록하세요."}
        self.facts[key] = {"value": value[:200], "quote": quote[:200]}
        return {"saved": True, "key": key}

    def tool_classify_clauses(self):
        from backend.clause_model import classify
        result = self.result or {}
        found = (result.get("extraction") or {}).get("clause_model") or classify(result.get("blocks", []), result.get("contract_type"))
        if not found:
            return {"available": False, "note": "조항 분류 모델이 없거나 근로계약서가 아닙니다. read_contract로 직접 확인하세요."}
        texts = {b["block_id"]: b["text"] for b in result.get("blocks", [])}
        typed = [{**b, "text": texts.get(b["block_id"], "")[:120]} for b in found["blocks"] if b["labels"]]
        return {"available": True, "model": found["model"], "clauses": typed[:60], "missing_required": found["missing_required"],
                "burden_candidates": [b for b in typed if b["risk_candidates"]], "note": found["note"]}

    def tool_remedy_guide(self, issue_type):
        found = remedy(issue_type)
        if found["found"]:
            # Fetch the official text of every article the route relies on, so the answer may cite it.
            found["laws"] = [self.tool_lookup_law(item["law_title"], item["article_number"]) for item in found.pop("laws_to_lookup")]
        return found

    def tool_draft_contract_request(self):
        fact = lambda k, blank="[직접 입력]": self.facts.get(k, {}).get("value") or blank
        today = date.today()
        reply = today + timedelta(days=7)
        lines = [
            "근로계약서 서면 교부 요청서", "",
            f"수신: {fact('employer_name', '[사업주 또는 회사명]')}",
            f"발신: {fact('worker_name', '[성명]')}", "",
            f"저는 {fact('start_date', '[근무 시작일]')}부터 {fact('workplace', '[사업장]')}에서 {fact('job', '[담당 업무]')} 업무를 하고 있습니다.",
            "아직 근로조건이 적힌 근로계약서를 서면으로 받지 못했습니다.", "",
            "근로기준법 제17조는 임금의 구성항목·계산방법·지급방법, 소정근로시간, 휴일, 연차 유급휴가에 관한 사항을 서면으로 명시하여 근로자에게 교부하도록 정하고 있습니다.",
            "이에 다음 내용이 포함된 근로계약서를 교부해 주실 것을 요청드립니다.", "",
            f"1. 임금: {fact('hourly_wage', fact('monthly_wage', '[들은 금액]'))} (구성항목·계산방법·지급일·지급방법)",
            f"2. 근로시간: {fact('daily_hours', '[하루 근무시간]')} / {fact('weekly_hours', '[주당 근무시간]')} 및 휴게시간",
            f"3. 휴일: {fact('days_off', '[휴일]')}",
            "4. 연차 유급휴가", f"5. 근무 장소와 업무: {fact('workplace', '[근무 장소]')} / {fact('job', '[업무]')}", "",
            f"{reply.year}년 {reply.month}월 {reply.day}일까지 회신해 주시기 바랍니다.",
            "", f"{today.year}년 {today.month}월 {today.day}일", f"요청인 {fact('worker_name', '[성명]')} (서명)",
        ]
        self.document = {"kind": "contract_delivery_request", "title": "근로계약서 서면 교부 요청서", "text": "\n".join(lines),
                         "blanks": sorted({m for m in re.findall(r"\[[^\]]+\]", "\n".join(lines))})}
        return {"prepared": True, "title": self.document["title"], "blanks": self.document["blanks"],
                "note": "문서는 화면에 첨부됩니다. 빈칸을 사용자에게 안내하세요."}


def monthly_paid_hours(weekly_hours):
    """The Ministry's monthly conversion: 40 hours a week gives 209 hours."""
    holiday = min(weekly_hours, 40) / 5 if weekly_hours >= 15 else 0
    return round((weekly_hours + holiday) * 4.345)


OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def arithmetic(expression):
    if len(expression) > 200:
        raise ValueError("too long")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](visit(node.operand))
        raise ValueError("unsupported")

    value = visit(ast.parse(expression.replace(",", ""), mode="eval"))
    return round(value, 4) if isinstance(value, float) else value
