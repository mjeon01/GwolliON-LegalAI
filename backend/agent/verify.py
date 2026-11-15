"""Check a drafted answer against what the run actually retrieved. Repair what can be repaired; flag the rest."""
import re

from backend.review import role_reversal

DEFINITIVE = re.compile(r"(?:불법|위법|무효|사기(?:죄)?|범죄)(?:입니다|이다|예요|이에요|에\s*해당합니다|가\s*성립합니다|가\s*확실)")
# Only statute articles ("근로기준법 제17조"), not contract clauses ("계약서 제3조").
ARTICLE = re.compile(r"(?:법|시행령)\s*제\s*(\d+)\s*조")
# Shown to the user when a problem survives the model's one revision.
NOTICES = {"citation": "확인되지 않은 인용을 답변에서 제외했습니다.",
           "definitive": "법적 판단을 단정하는 표현이 남아 있습니다. 결론은 전문가 상담으로 확인하세요.",
           "article": "답변에 원문을 확인하지 못한 조문 번호가 있습니다. 해당 조문은 직접 확인이 필요합니다.",
           "role": "당사자 의무 설명이 사용자 입장과 맞지 않을 수 있습니다. 주의해서 읽어주세요.",
           "empty": "답변을 만들지 못했습니다. 다시 질문해주세요."}


def squash(text):
    return re.sub(r"\s+", " ", text or "").strip()


def verify(payload, toolbox, contract_type=None, role=None):
    """Return (cleaned answer, [(code, instruction for the model)], notices for the user)."""
    problems, warnings = [], []
    evidence = [i for i in dict.fromkeys(payload.get("evidence_block_ids", [])) if i in toolbox.blocks]
    if len(evidence) < len(payload.get("evidence_block_ids", [])):
        warnings.append("존재하지 않는 조항 번호를 근거에서 제외했습니다.")
    citations, dropped = [], 0
    for item in payload.get("citations", []):
        source, quote = toolbox.sources.get(item.get("source_id")), squash(item.get("quote"))
        if source and 6 <= len(quote) <= 400 and quote in squash(source.get("text")):
            citations.append({"source_id": source["source_id"], "quote": quote, "title": source["title"],
                              "kind": source.get("kind", "law"), "dataset_kind": source.get("dataset_kind"),
                              "version_note": source.get("version_note", "")})
        else:
            dropped += 1
    if dropped:
        problems.append(("citation", f"인용 {dropped}건이 조회한 원문과 일치하지 않습니다. 도구로 받은 원문에서 연속된 문구를 그대로 복사하거나 인용을 빼세요."))
    text_ko = payload.get("answer_ko") or ""
    if DEFINITIVE.search(text_ko):
        problems.append(("definitive", "위법·무효·범죄를 단정했습니다. '~에 해당할 수 있어 확인이 필요합니다'처럼 가능성과 확인할 사실로 표현하세요."))
    known_articles = {str(s.get("article_number")) for s in toolbox.sources.values() if s.get("kind", "law") == "law" and s.get("article_number")}
    unverified = sorted(set(ARTICLE.findall(text_ko)) - known_articles)
    if unverified:
        problems.append(("article", "조회하지 않은 조문을 언급했습니다: 제" + "조, 제".join(unverified) + "조. lookup_law로 확인하거나 언급을 빼세요."))
    if contract_type and role and role_reversal(text_ko, contract_type, role):
        problems.append(("role", "당사자의 의무를 뒤바꿨습니다(예: 임차인이 보증금을 반환). 사용자의 입장을 다시 확인하세요."))
    if not payload.get("answer", "").strip() or not text_ko.strip():
        problems.append(("empty", "답변이 비어 있습니다."))
    cleaned = {**payload, "evidence_block_ids": evidence, "citations": citations, "dropped_citations": dropped}
    warnings += [NOTICES[code] for code, _ in problems if code != "citation"] + ([NOTICES["citation"]] if dropped else [])
    return cleaned, problems, warnings
