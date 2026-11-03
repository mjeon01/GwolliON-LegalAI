"""Stage 2: project validated evidence into JSON without choosing conflicting values."""
import re


def structure_contract(terms, blocks, contract_type):
    fields = {t["key"]: t for t in terms}

    def value(key):
        term = fields.get(key, {})
        if term.get("status") != "found":
            return None
        return term["candidates"][0].get("normalized_value")

    def text(key):
        item = value(key)
        return item.get("text") if item else None

    if contract_type == "sale":
        return {"contract_type": "부동산매매계약서", "price": value("price"),
                **{key: fields[key]["candidates"][0]["value_text"] if fields[key]["status"] == "found" else None for key in ("address", "settlement_date", "handover_terms")}}
    if contract_type == "lease":
        return {"contract_type": "주택임대차계약서", "deposit": value("deposit"), "rent": value("rent"),
                "contract_period": value("period"), "address": text("address") or (fields["address"]["candidates"][0]["value_text"] if fields["address"]["status"] == "found" else None)}
    document = "\n".join(b["text"] for b in blocks)
    period, wage = value("period") or {}, value("wage") or {}
    clocks, rest = value("work_hours") or {}, value("break_time") or {}
    fixed = True if re.search(r"기간의\s*정함이\s*있는|기간제", document) else False if period.get("indefinite") else True if period.get("end_date") else None
    payday = value("payment_date") or {}
    return {
        "contract_type": "일반근로계약서", "fixed_term": fixed,
        "contract_period": {"start": period.get("start_date"), "end": period.get("end_date")},
        "workplace": text("workplace"), "job_description": text("job_description"),
        "working_hours": {"start": clocks.get("start"), "end": clocks.get("end"),
                          "break": f"{rest['start']}~{rest['end']}" if rest.get("start") else None,
                          "break_minutes": rest.get("minutes"), "weekly_hours": (value("weekly_hours") or {}).get("hours")},
        "work_days": text("work_days"), "holiday": text("holiday"),
        "wage": {"type": {"month": "monthly", "hour": "hourly", "day": "daily", "year": "yearly"}.get(wage.get("period")),
                 "amount": wage.get("amount"), "currency": wage.get("currency"),
                 "payday": f"매월 {payday['day']}일" if payday.get("period") == "month" else None,
                 "payment_method": (value("payment_method") or {}).get("method")},
        "annual_leave": text("annual_leave"),
    }


def validate_completeness(contract, terms, contract_type):
    """Stage 3 checks document completeness, never labels the contract unlawful."""
    if contract_type != "employment":
        return []
    fields = {t["key"]: t for t in terms}
    checks = []
    specifications = [
        ("period", "contract_period.start", "근로 시작일", contract["contract_period"]["start"]),
        ("period", "contract_period.end", "계약 종료일", contract["contract_period"]["end"]),
        ("workplace", "workplace", "근무장소", contract["workplace"]),
        ("job_description", "job_description", "업무내용", contract["job_description"]),
        ("work_hours", "working_hours", "소정근로시간", contract["working_hours"]["start"] and contract["working_hours"]["end"]),
        ("break_time", "working_hours.break", "휴게시간", contract["working_hours"]["break_minutes"]),
        ("wage", "wage.amount", "임금", contract["wage"]["amount"]),
        ("payment_date", "wage.payday", "임금 지급일", contract["wage"]["payday"]),
        ("payment_method", "wage.payment_method", "임금 지급방법", contract["wage"]["payment_method"]),
        ("holiday", "holiday", "휴일", contract["holiday"]),
        ("annual_leave", "annual_leave", "연차유급휴가", contract["annual_leave"]),
    ]
    for key, path, label, val in specifications:
        state = fields[key]["status"]
        if path == "contract_period.end" and contract["fixed_term"] is False:
            status, message = "not_applicable", "기간의 정함이 없는 계약으로 읽었습니다. 종료일을 누락 항목으로 표시하지 않습니다."
        elif state == "conflict":
            status, message = "conflict", f"{label} 후보가 여러 개여서 적용할 값을 확인해야 합니다."
        elif path == "contract_period.end" and contract["fixed_term"] is None and val is None:
            status, message = "needs_context", "기간을 정한 계약인지 먼저 확인해야 합니다."
        elif val is None or val == "":
            status, message = "not_found", f"현재 읽은 문서에서 {label}을 확인하지 못했습니다. 누락 가능성과 다른 페이지·별첨을 확인하세요."
        else:
            status, message = "confirmed", f"{label}을 추출했습니다. 원문과 대조하세요."
        checks.append({"field": path, "term_key": key, "label": label, "status": status,
                       "message": message, "evidence": [c["evidence"] for c in fields[key]["candidates"]]})
    return checks
