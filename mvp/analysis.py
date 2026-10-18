"""A bounded contract review flow: extract -> cite -> ask -> prepare actions."""
from datetime import datetime, timezone
import re

from mvp.extraction import blocks_from_text, rules_extract, ollama_extract, assemble_terms
from mvp.knowledge import Knowledge
from mvp.structure import structure_contract, validate_completeness

QUESTION_LABELS = {
    "document_complete": "계약서의 모든 페이지와 별첨을 입력했나요?",
    "event_date": "확인하려는 계약·사건의 날짜는 언제인가요?",
    "workplace_size": "상시 근로자 수는 어느 범위인가요?",
    "weekly_work_hours": "실제로 일하는 주당 근로시간은 몇 시간인가요?",
    "move_in": "주택을 인도받고 입주했나요?",
    "resident_registration": "해당 주택에 전입신고를 마쳤나요?",
    "deposit_returned": "계약이 끝난 뒤 보증금을 전액 반환받았나요?",
}


def extract(request):
    blocks = blocks_from_text(request.text)
    from mvp.retrieval import retrieve
    grounding = retrieve(request, blocks)
    assisted = 0
    if request.engine == "ollama":
        found, model, rejected = ollama_extract(blocks, request.contract_type)
        # A successful model run can omit fields. Preserve its candidates, then
        # supplement from the same source with deterministic form parsing.
        # Model failures still fail the job; there is no silent fallback.
        form_terms = rules_extract(blocks, request.contract_type)
        for key, candidates in found.items():
            for item in candidates:
                item["extraction_method"] = "ollama"
            for item in form_terms[key]:
                if not any((c["normalized_value"] or c["value_text"]) == (item["normalized_value"] or item["value_text"]) for c in candidates):
                    item["extraction_method"] = "form_rules"
                    candidates.append(item)
                    assisted += 1
    else:
        found, model, rejected = rules_extract(blocks, request.contract_type), "rules-v2", 0
    metadata = {"engine": request.engine, "model": model, "rejected_candidates": rejected,
                "method": "ollama_with_form_rules" if request.engine == "ollama" else "form_rules", "form_rule_candidates_added": assisted,
                "grounding": grounding}
    if request.engine == "ollama":
        from mvp.review import semantic_review
        metadata["semantic_review"] = semantic_review(blocks, request.contract_type, request.user_role, grounding)
    return blocks, assemble_terms(found, request.contract_type), metadata


def evaluate(request, blocks, terms, extraction, analysis_id, revision):
    context = request.context.model_dump(mode="json")
    grounding = extraction.get("grounding", {})
    from datetime import date
    if grounding and grounding.get("target_date") != (context["event_date"] or date.today().isoformat()):
        from mvp.retrieval import retrieve
        extraction = {**extraction, "grounding": retrieve(request, blocks)}
        grounding = extraction["grounding"]
        if request.engine == "ollama":
            from mvp.review import semantic_review
            extraction["semantic_review"] = semantic_review(blocks, request.contract_type, request.user_role, grounding)
    knowledge = Knowledge(supplemental=grounding.get("sources", []))
    fields = {t["key"]: t for t in terms}
    structured = structure_contract(terms, blocks, request.contract_type)
    checks = validate_completeness(structured, terms, request.contract_type)
    sources, issues, requested = {s["source_id"]: s for s in grounding.get("sources", [])}, [], set()
    law = {"employment": "근로기준법", "lease": "주택임대차보호법", "sale": "민법"}[request.contract_type]

    def ask(*keys):
        for key in keys:
            if context[key] is None or context[key] == "unknown":
                requested.add(key)

    def add(kind, title, explanation, status, numbers=(), evidence=(), actions=(), missing=()):
        refs = []
        for number in numbers:
            source = knowledge.lookup(law, number, context["event_date"])
            if source:
                refs.append(source["source_id"])
                sources[source["source_id"]] = source
        effective = bool(refs) and all(sources[r]["version_applicable"] for r in refs)
        if numbers and not effective:
            status = "insufficient_evidence"
            explanation += " 적용 시점의 법령 근거를 추가 확인해야 합니다."
        if numbers:
            ask("event_date")
        ask(*missing)
        issues.append({"issue_id": f"I{len(issues)+1:03d}", "issue_type": kind, "title": title,
                       "status": status, "severity": "attention" if status == "attention" else "unassessed",
                       "explanation_ko": explanation, "evidence": list(evidence), "source_ids": refs,
                       "actions": list(actions), "validation": {"source_checked": bool(refs),
                       "version_applicable": effective, "context_complete": not any(context[k] is None or context[k] == "unknown" for k in missing)}})

    def hits(pattern, kind=None):
        from mvp.review import rule_matches
        return [{"block_id": b["block_id"], "page": b["page"], "start": 0, "end": len(b["text"]), "quote": b["text"]}
                for b in blocks if (rule_matches(b["text"], pattern, kind) if kind else re.search(pattern, b["text"]))]

    essential = ["price", "address", "settlement_date", "handover_terms"] if request.contract_type == "sale" else ["deposit", "period", "address", "return_terms"]
    absent = [c["label"] for c in checks if c["status"] == "not_found" and c["term_key"] != "break_time"] if request.contract_type == "employment" else [fields[k]["label"] for k in essential if fields[k]["status"] == "not_found"]
    if absent:
        add("missing_terms", "계약조건 추가 확인", "현재 읽은 문서에서 다음 항목을 찾지 못했습니다: " + ", ".join(absent) + ". 별첨·다른 페이지와 실제 약정을 확인하세요.",
            "attention" if context["document_complete"] is True else "needs_context", [17] if request.contract_type == "employment" else (),
            actions=["누락 페이지와 별첨을 확인하기", "불명확한 조건을 서면으로 확인하기"], missing=["document_complete"])
    for term in terms:
        if term["status"] == "conflict":
            add("conflicting_terms", term["label"] + " 후보가 여러 개입니다", "서로 다른 값 또는 표현이 있습니다. 항목별 구성이나 변경 약정인지 원문을 대조하고 적용할 값을 확인하세요.",
                "conflict", evidence=[v["evidence"] for v in term["candidates"]], actions=["해당 조항과 별첨을 함께 보관하기", "적용되는 값을 계약 상대방에게 확인하기"])
    if request.contract_type == "employment":
        if any(c["field"] == "contract_period.end" and c["status"] == "needs_context" for c in checks):
            add("contract_period", "계약기간 구분 확인", "기간의 정함이 있는 계약인지 확인되지 않습니다. 기간을 정했다면 종료일을, 정하지 않았다면 근로개시일을 원문·별첨과 대조하세요.", "needs_context",
                actions=["계약기간의 정함 여부와 시작·종료일을 서면으로 확인하기"])
        wage = fields["wage"]
        if wage["status"] == "found" and wage["candidates"][0]["normalized_value"]["period"] == "unknown":
            add("wage_period", "임금의 지급 단위 확인", "금액은 찾았지만 시급·월급·연봉 중 어떤 기준인지 확정하지 못했습니다. 지급 단위와 계산 방법을 확인하세요.", "attention", [17, 43],
                [wage["candidates"][0]["evidence"]], ["임금 구성항목·계산방법·지급방법 확인하기"])
        evidence = hits(r"(?:퇴사|퇴직|불이행|중도).*(?:위약금|벌금|배상액|손해배상.*(?:만원|원))|(?:위약금|배상액).*(?:지급|부담|공제)")
        if evidence:
            negative = all(re.search(r"(?:위약금|손해배상|배상액|벌금).*(?:없다|않는다|않기로|금지)", e["quote"]) for e in evidence)
            if not negative:
                add("penalty", "퇴사·불이행과 배상 약정 확인", "배상 관련 표현을 찾았습니다. 근로계약 불이행에 대한 금액을 미리 정한 약정인지, 실제 손해에 관한 내용인지 구분해 확인하세요.", "attention", [20], evidence,
                    ["배상 조건과 산정 근거를 서면으로 확인하기", "계약서와 관련 대화를 정리해 상담받기"])
        evidence = hits(r"(?:연장|야간|휴일).*(?:포함|일체|별도.*없|지급.*않)|포괄임금", "included_allowance")
        if evidence:
            add("included_allowance", "수당 포함 범위 확인", "수당을 포함하거나 별도 지급하지 않는 표현을 찾았습니다. 항목별 금액·시간·실제 근무와 적용 조건을 확인해야 합니다.",
                "needs_context" if context["workplace_size"] == "unknown" else "attention", [11, 56], evidence,
                ["기본급과 수당 내역 요청하기", "출퇴근·급여 기록 보관하기"], ["workplace_size", "weekly_work_hours"])
        weekly = fields["weekly_hours"]
        declared = weekly["candidates"][0]["normalized_value"]["hours"] if weekly["status"] == "found" and weekly["candidates"][0]["normalized_value"] else None
        actual = context["weekly_work_hours"]
        if declared is not None and actual is not None and declared != actual:
            add("hours_context", "계약과 실제 근무시간 대조", f"계약서에는 주 {declared:g}시간, 사용자 답변에는 주 {actual:g}시간으로 기록됐습니다. 차이의 원인과 연장근로 기록을 확인하세요.", "conflict",
                evidence=[weekly["candidates"][0]["evidence"]], actions=["계약시간과 실제 출퇴근 기록 비교하기"])
        hours = actual if actual is not None else declared
        if hours is not None and hours > 40:
            add("work_hours", "주 40시간 초과 근무 확인", "주당 시간이 40시간을 초과합니다. 휴게 제외 여부, 연장근로 합의, 유연근무와 적용 예외를 확인해야 합니다. 초과 자체만으로 위법을 확정하지 않습니다.",
                "needs_context" if context["workplace_size"] == "unknown" else "attention", [11, 50],
                [c["evidence"] for c in weekly["candidates"]], ["실근로·휴게·연장근로 시간 구분하기"], ["workplace_size"])
        if fields["break_time"]["status"] == "not_found":
            add("break_time", "휴게시간 확인", "휴게시간을 찾지 못했습니다. 실제 근무 길이에 따른 휴게시간과 자유롭게 사용할 수 있는지 확인하세요.", "needs_context", [54],
                actions=["휴게시간과 이용 방식을 확인하기"], missing=["document_complete", "weekly_work_hours"])
    elif request.contract_type == "lease" and not re.search(r"상가\s*(?:건물\s*)?임대차|점포\s*임대차|임차\s*상가", "\n".join(b["text"] for b in blocks[:5])):
        add("lease_registration", "입주·전입신고 상태 확인", "주택 인도와 주민등록은 대항력 확인에 필요한 정보입니다. 완료 여부만으로 권리 순위나 보증금 회수를 판단할 수 없으므로 등기와 관련 시점도 확인하세요.",
            "needs_context" if context["move_in"] is None or context["resident_registration"] is None else "attention" if not context["move_in"] or not context["resident_registration"] else "information", [3],
            actions=["입주·전입신고 날짜와 확정일자 자료 정리하기", "등기사항증명서와 권리 순위 확인하기"], missing=["move_in", "resident_registration"])
        evidence = hits(r"(?:새로운|새|다음|신규)\s*(?:임차인|세입자).*(?:구해|구할|구한|입주|계약|보증금)|(?:보증금|전세금).*(?:새로운|새|다음|신규)\s*(?:임차인|세입자)|보증금.*(?:반환.*포기|반환하지|몰수)") if request.user_role == "tenant" else []
        if evidence:
            add("deposit_return", "보증금 반환 조건 확인", "보증금 반환 관련 문구를 찾았습니다. 반환 시점·공제 사유를 확인하고, 계약이 끝났는데 미반환이라면 지급 기록과 요청·답변을 정리하세요.", "attention", [4, 10], evidence,
                ["계약서·이체내역·반환 요청 기록 보관하기", "반환 조건과 공제 근거 확인하기"])
        if context["deposit_returned"] is False:
            add("deposit_unreturned", "미반환 상황 상담 준비", "사용자가 보증금을 전액 반환받지 못했다고 답했습니다. 계약 종료 여부·요청일·반환된 금액과 상대방 답변을 확인해야 합니다. 이 답변만으로 사기 피해를 확정하지 않습니다.", "attention", [4],
                actions=["계약 종료·반환 요청 경위와 남은 금액 정리하기", "계약서·등기·지급 내역을 가지고 상담받기"])
    from mvp.review import review_contract
    review, review_sources = review_contract(request, blocks, checks, issues, extraction)
    for source in review_sources:
        sources[source["source_id"]] = source
    for finding in review["findings"]:
        if finding["source_ids"]:
            ask("event_date")
        if finding["issue_type"] not in {i["issue_type"] for i in issues}:
            add(finding["issue_type"], finding["title"], finding["why_unfavorable"], "attention", evidence=finding["evidence"], actions=["조항의 수정 문구를 협의하고 상담받기"])
            issues[-1]["source_ids"] = finding["source_ids"]
            law_ids = [s for s in finding["source_ids"] if sources[s].get("kind", "law") == "law"]
            issues[-1]["validation"] = {"source_checked": bool(finding["source_ids"]), "version_applicable": bool(law_ids) and all(sources[s]["version_applicable"] for s in law_ids), "context_complete": False}
            if finding["source_ids"] and not issues[-1]["validation"]["version_applicable"]:
                issues[-1]["status"] = "insufficient_evidence"
    if context["document_complete"] is not True:
        ask("document_complete")
    if not issues:
        add("review_scope", "기본 항목을 추출했습니다", "이번 추출 범위의 기본 항목을 찾았습니다. 금액의 적정성·최저임금·실제 이행·모든 특약의 효력은 별도 검토 대상입니다.", "information",
            actions=["추출값과 원문이 일치하는지 확인하기", "실제 근무와 지급 조건을 대조하기"])
    questions = [{"question_id": "Q_" + key, "context_key": key, "text_ko": QUESTION_LABELS[key],
                  "answer_type": "date" if key == "event_date" else "number" if key == "weekly_work_hours" else "category" if key == "workplace_size" else "boolean"}
                 for key in QUESTION_LABELS if key in requested]
    actions = list(dict.fromkeys(a for i in issues for a in i["actions"]))
    return {"schema_version": "2.0", "analysis_id": analysis_id, "analysis_revision": revision, "user_role": request.user_role, "review": review,
            "title": request.title, "contract_type": request.contract_type, "engine": extraction["engine"],
            "status": "awaiting_input" if questions else "completed", "created_at": datetime.now(timezone.utc).isoformat(),
            "blocks": blocks, "terms": terms, "structured_contract": structured, "validation_checks": checks,
            "pipeline": ["document_reading", "contract_structuring", "user_perspective_review", "review_validation"],
            "reading": request.reading.model_dump() if request.reading else {"methods": ["manual_text"], "ocr_used": False, "warnings": []},
            "issues": issues, "questions": questions, "sources": list(sources.values()),
            "grounding": {k: v for k, v in grounding.items() if k != "sources"}, "evidence_mode": request.evidence_mode,
            "actions": actions, "context": context, "extraction": extraction,
            "coverage": {"pages_read": sorted({b["page"] for b in blocks}), "document_complete": context["document_complete"],
                         "checked_issue_types": list(dict.fromkeys(i["issue_type"] for i in issues)),
                         "limitations": ["전문가 법률 검수 전의 쟁점 확인용 MVP", "단시간·기간제의 추가 조항은 근거 조회 지원; 외국인 전용 조항은 후속 범위", "사진·스캔 OCR은 오인식 가능: 추출문을 원본과 대조해야 함", "최저임금 금액·등기·손해액 계산 미지원; 검색된 판례의 직접 적용은 별도 검토"]},
            "versions": {"model": extraction["model"], "prompt": "extract-v2-grounded-review-v4", "rules": "review-v4",
                         "knowledge": sorted({s["snapshot_id"] for s in sources.values()})}}
