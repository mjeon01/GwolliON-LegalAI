"""Plan public topic queries; never send contract text or personal facts to an API."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import re

from mvp.corpus import Corpus
from mvp.knowledge import Knowledge
from mvp.legal_api import LegalAPI, EvidenceError

TOPICS = {
    "penalty": ("근로계약 위약금", ["위약금", "손해배상", "근로계약"]),
    "included_allowance": ("포괄임금", ["포괄임금", "연장근로", "근로수당"]),
    "wage_deduction": ("임금 공제", ["임금공제", "손해배상", "임금지급"]),
    "leave_waiver": ("연차휴가", ["연차휴가", "유급휴가"]),
    "noncompete": ("경업금지 약정", ["경업금지", "취업금지", "경쟁업체"]),
    "deposit_return": ("임대차보증금 반환", ["보증금", "임대차", "반환"]),
    "repair_burden": ("임대인 수선의무", ["수선의무", "수리비", "임대차"]),
    "registration_waiver": ("주택임대차 대항력", ["전입신고", "확정일자", "대항력"]),
    "unilateral_termination": ("임대차 해지", ["임대차", "계약해지"]),
    "rent_waiver": ("임대차 차임", ["임대차", "차임지급"]),
    "sale_advance": ("소유권이전 동시이행", ["소유권이전", "동시이행", "잔금지급"]),
    "sale_cancellation": ("매매 계약금 해제", ["계약금", "계약해제", "매매계약"]),
    "sale_transfer_first": ("소유권이전 동시이행", ["소유권이전", "동시이행", "잔금지급"]),
    "unpaid_trial": ("수습 근로 임금", ["수습기간", "임금지급", "최저임금"]),
    "deposit_deduction": ("임대차보증금 공제", ["보증금", "수리비", "공제금액"]),
    "sale_defect_waiver": ("매매 하자담보 면책", ["하자담보", "면책특약", "매매계약"]),
}


def plan(request, blocks):
    from mvp.review import RULES, rule_matches
    refs = {"employment": [("근로기준법", n) for n in (17, 11, 43, 50, 54, 56, 60)],
            "lease": [("주택임대차보호법", n) for n in (3, 4, 10)] + [("민법", n) for n in (536, 623)],
            "sale": [("민법", n) for n in (536, 565)]}[request.contract_type]
    matched = [r for r in RULES if r[1] == request.contract_type and request.user_role in r[2] and any(rule_matches(b["text"], r[3], r[0]) for b in blocks)]
    topics = [r[0] for r in matched]
    text = "\n".join(b["text"] for b in blocks)
    commercial = request.contract_type == "lease" and re.search(r"상가\s*(?:건물\s*)?임대차|점포\s*임대차", text[:1000])
    if commercial:
        refs = [("상가건물 임대차보호법", n) for n in (3, 9, 15)] + [("민법", n) for n in (536, 623)]
    if request.contract_type == "employment":
        if re.search(r"단시간|시간제|기간제|아르바이트", text):
            refs.append(("기간제 및 단시간근로자 보호 등에 관한 법률", 17))
        if "퇴직금" in text:
            refs += [("근로자퇴직급여 보장법", 4), ("근로자퇴직급여 보장법", 8)]
        if "최저임금" in text:
            refs.append(("최저임금법", 6))
    refs = list(dict.fromkeys(ref for r in matched for ref in r[-1])) + refs
    if commercial:
        refs = [r for r in refs if r[0] != "주택임대차보호법"]
    query, terms = TOPICS[topics[0]] if topics else {
        "employment": ("근로계약 임금", ["근로계약", "근로시간", "임금지급"]),
        "lease": ("임대차보증금 반환", ["임대차", "보증금", "반환"]),
        "sale": ("부동산 매매 동시이행", ["매매계약", "소유권이전", "동시이행"]),
    }[request.contract_type]
    administrative_query = next((term for term in ("영업정지", "등록취소", "행정처분", "중개업") if term in text), None)
    return {"topics": topics, "article_refs": list(dict.fromkeys(refs)), "public_query": query, "dataset_terms": terms,
            "case_focus": {"deposit_return": ["동시이행", "보증금 반환의무", "반환 지체", "신규 임차인"], "repair_burden": ["수선의무", "수선 의무"], "noncompete": ["경업금지"], "penalty": ["위약금", "손해배상액의 예정"], "sale_advance": ["동시이행"], "sale_defect_waiver": ["하자담보", "담보책임"]}.get(topics[0], []) if topics else [],
            "case_targets": ["prec", "expc"] + (["decc"] if administrative_query else []),
            "case_queries": {"prec": query, "expc": query, **({"decc": administrative_query} if administrative_query else {})}}


def retrieve(request, blocks):
    selected, corpus, knowledge = plan(request, blocks), Corpus(), Knowledge()
    sources, failures, law_status = {}, [], {}
    target = request.context.event_date.isoformat() if request.context.event_date else None
    refs = selected["article_refs"]
    for law, number in refs:
        source = knowledge.lookup(law, number, target)
        if source:
            source.update(kind="law", retrieval_method="local_snapshot")
            sources[source["source_id"]] = source
    if request.evidence_mode == "live":
        try:
            api = LegalAPI()
            jobs = [("law", law) for law in dict.fromkeys(law for law, _ in refs)] + list(selected["case_queries"].items())
            with ThreadPoolExecutor(max_workers=3) as pool:
                tasks = {pool.submit(api.law, q, target) if kind == "law" else pool.submit(api.cases, kind, q, target, focus_terms=[q] if kind == "decc" else selected["case_focus"]): (kind, q) for kind, q in jobs}
                for task in as_completed(tasks):
                    kind, query = tasks[task]
                    try:
                        fetched = task.result()
                        if kind == "law":
                            wanted = {str(n) for law, n in refs if law == query}
                            fetched = [s for s in fetched if s["article_number"] in wanted and not s["branch_number"]]
                            sources = {k: s for k, s in sources.items() if s.get("law_title") != query}
                            law_status[query] = {"status": "verified", "articles": len(fetched)}
                            if {s["article_number"] for s in fetched} != wanted:
                                failures.append({"target": "law", "query": query, "reason": "requested_article_missing"})
                        for source in fetched:
                            sources[source["source_id"]] = source
                    except (EvidenceError, OSError, ValueError, TypeError, KeyError):
                        failures.append({"target": kind, "query": query, "reason": "official_retrieval_unavailable"})
                        if kind == "law":
                            law_status[query] = {"status": "unavailable"}
        except (EvidenceError, OSError, ValueError):
            failures.append({"target": "configuration", "reason": "official_api_unavailable"})
    for source in corpus.search(selected["dataset_terms"], limit=2, kinds=["contract", "contract_label", "precedent_reference", "interpretation_reference", "decision_reference", "law_reference", "qa_example", "summary_example"]):
        sources[source["source_id"]] = source
    status = corpus.status()
    law_order = {(law, str(n)): i for i, (law, n) in enumerate(refs)}
    ordered = sorted(sources.values(), key=lambda s: (0, law_order.get((s.get("law_title"), s.get("article_number")), 999)) if s.get("kind") == "law" else (1, s["source_id"]))
    return {"mode": request.evidence_mode, "target_date": target or date.today().isoformat(), "plan": selected, "sources": ordered,
            "law_status": law_status, "failures": failures,
            "corpus": {k: status.get(k) for k in ("status", "records", "runtime_split", "exact_text_hash_overlap")},
            "privacy": "법령명과 미리 정의된 일반 법률 쟁점만 공식 API에 전송합니다. 계약서 원문과 사용자 설명은 전송하지 않습니다.",
            "limitations": ["검색된 사례의 사실관계가 이 계약과 같다는 의미는 아님", "제공된 데이터는 학습·참고 자료이며 법률 판단 정답이 아님"]}


def prompt_sources(bundle, limit=10):
    # Reserve room for case material and examples rather than fill the prompt with statutes.
    source_list = bundle.get("sources", [])
    ordered = [s for s in source_list if s.get("kind") == "law"][:6] + [s for s in source_list if s.get("kind") != "law"][:4]
    return [{"source_id": s["source_id"], "kind": s.get("kind", "law"), "title": s["title"], "text": s["text"][:1000],
             "version_applicable": s.get("version_applicable", False), "version_note": s.get("version_note", ""),
             "decision_date": s.get("decision_date"), "effective_date": s.get("effective_date")} for s in ordered[:limit]]


def validate_citations(citations, supplied):
    index = {s["source_id"]: s for s in supplied}
    if not isinstance(citations, list) or len(citations) > 4:
        return None
    accepted = []
    for citation in citations:
        if not isinstance(citation, dict):
            return None
        source = index.get(citation.get("source_id"))
        quote = citation.get("quote")
        if not source or not isinstance(quote, str) or len(quote.strip()) < 8 or quote not in source["text"]:
            return None
        accepted.append({"source_id": source["source_id"], "quote": quote, "kind": source.get("kind", "law")})
    return accepted
