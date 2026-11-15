"""외국인근로자 표준근로계약서 (외국인고용법 시행규칙 별지 제6호서식) reader and checks.

The bilingual form puts every term in a fixed numbered row, so the filled values can be read line by line
instead of guessed. Checks compare those values with the form's own instructions and the statutory floors
(근로기준법, 최저임금법, 외국인고용법, 고용노동부 숙식비 지침). Each finding quotes the line it is based on.
"""
from datetime import date
import re

# 최저임금 시급 (고용노동부 고시). Monthly = hourly × 209 hours (주 40시간 + 주휴).
MINIMUM_WAGE = {2024: 9860, 2025: 10030, 2026: 10320}
MONTHLY_HOURS = 209
# 고용노동부 「외국인근로자 숙식정보 제공 및 비용징수 관련 업무지침」(2017): share of monthly 통상임금.
LODGING_CEILING = {("house", True): 0.20, ("house", False): 0.15, ("temporary", True): 0.13, ("temporary", False): 0.08}
TEMPORARY_HOUSING = ("컨테이너", "조립식 패널", "사업장 건물")
E9_MAX_MONTHS = 36

# "high": the written value is below a statutory floor or breaks the form's own rule; "check": something to fill in
# or confirm (a blank, a vague duty, a rule that depends on the workplace size).
SEVERITY = {"foreign_period": "high", "foreign_probation_wage": "high", "foreign_workplace": "high", "foreign_hours": "high",
            "foreign_break": "high", "foreign_overtime": "high", "foreign_minimum_wage": "high", "foreign_payday": "high",
            "foreign_custody": "high", "foreign_lodging": "high",
            "foreign_identity": "check", "foreign_job": "check", "foreign_holiday": "check", "foreign_signature": "check"}
TOPIC = {"foreign_minimum_wage": "임금", "foreign_probation_wage": "임금", "foreign_payday": "임금",
         "foreign_hours": "근로시간·휴일", "foreign_break": "근로시간·휴일", "foreign_overtime": "근로시간·휴일", "foreign_holiday": "근로시간·휴일",
         "foreign_identity": "계약·서류", "foreign_period": "계약·서류", "foreign_workplace": "계약·서류", "foreign_job": "계약·서류",
         "foreign_signature": "계약·서류", "foreign_custody": "숙식·통장", "foreign_lodging": "숙식·통장"}
TOPICS = ["임금", "근로시간·휴일", "계약·서류", "숙식·통장"]


def summary(findings):
    """Counts the review page shows above the cards."""
    form = [f for f in findings if f["issue_type"] in SEVERITY]
    return {"form": "foreign_standard", "high": sum(f["severity"] == "high" for f in form),
            "check": sum(f["severity"] == "check" for f in form),
            "topics": [{"topic": name, "count": n} for name in TOPICS if (n := sum(f.get("topic") == name for f in form))]}


CHECK = r"[✓✔√vVoO○●■]"
MARK = r"\[\s*" + CHECK + r"\s*\]"
AMOUNT = r"\(\s*([\d,]+)\s*\)\s*원"


def is_foreign_form(blocks):
    head = " ".join(b["text"] for b in blocks[:12])
    return bool(re.search(r"별지\s*제\s*6\s*호\s*서식", head) or ("표준근로계약서" in head and "Standard Labor Contract" in head))


def _won(raw):
    return int(raw.replace(",", "")) if raw and raw.replace(",", "").isdigit() else None


def _minutes(clock):
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def parse(blocks):
    """Filled values of the form, each with the block it was read from; None if this is not the form."""
    if not is_foreign_form(blocks):
        return None
    form = {}

    def find(pattern, key=None, start=0):
        for block in blocks[start:]:
            match = re.search(pattern, block["text"])
            if match:
                if key:
                    form[key + "_block"] = block
                return match, block
        return None, None

    match, block = find(r"생년월일\s*(?:Birthdate)?\s*(.*)", "birthdate")
    if block:
        found = re.search(r"\d{4}\s*[.\-/년]\s*\d{1,2}\s*[.\-/월]\s*\d{1,2}", match[1])
        form["birthdate"] = found[0] if found else None
    match, _ = find(r"신규\s*또는\s*재입국자\s*[:：]\s*\(\s*(\d*)\s*\)\s*개월", "period")
    if match:
        form["period_months"] = int(match[1]) if match[1] else None
    match, block = find(r"수습\s*기간\s*[:：]", "probation")
    if block:
        text = block["text"]
        form["probation"] = False if re.search(MARK + r"\s*미활용", text) else True if re.search(MARK + r"\s*활용", text) else None
        months = re.search(MARK + r"\s*(\d)\s*개월", text)
        form["probation_months"] = int(months[1]) if months else None
    match, _ = find(r"^\s*2\.\s*근로장소\s+(.+)", "workplace")
    form["workplace"] = match[1].strip() if match else None
    match, _ = find(r"직무\s*내용\s*[:：]\s*(.*)", "job")
    form["job"] = match[1].strip() if match else None
    match, block = find(r"^\s*4\.\s*근로시간\s+(\d{1,2}:\d{2})\s*[~∼-]\s*(\d{1,2}:\d{2})", "hours")
    if match:
        form["start"], form["end"] = match[1].zfill(5), match[2].zfill(5)
    match, _ = find(r"시간외\s*근로시간\s*[:：]\s*(\d+(?:\.\d+)?)\s*시간(?:.*?(\d+(?:\.\d+)?)\s*시간\s*이내)?", "overtime")
    if match:
        form["overtime_avg"] = float(match[1])
        form["overtime_max"] = float(match[2]) if match[2] else float(match[1])
    match, _ = find(r"^\s*5\.\s*휴게시간\s+1일\s*(\d+(?:\.\d+)?)\s*(분|시간)", "break")
    if match:
        form["break_minutes"] = float(match[1]) * (60 if match[2] == "시간" else 1)
    match, block = find(r"^\s*6\.\s*휴일\s+(.+)", "holiday")
    if block:
        rows = match[1] + " " + blocks[blocks.index(block) + 1]["text"] if blocks.index(block) + 1 < len(blocks) else match[1]
        days = re.findall(MARK + r"\s*([가-힣]+(?:\s*토요일)?)", rows)
        form["holiday"] = "·".join(d.replace("공휴일", "공휴일" + ("(유급)" if re.search(MARK + r"\s*유급", rows) else "(무급)" if re.search(MARK + r"\s*무급", rows) else ""))
                                  for d in days if d not in {"유급", "무급"}) or match[1].strip()
        paid = re.search(r"공휴일\s*\(\s*\[(.*?)\]\s*유급\s*\[(.*?)\]\s*무급", block["text"])
        form["public_holiday_paid"] = None if not paid else bool(paid[1].strip()) if bool(paid[1].strip()) != bool(paid[2].strip()) else None
    match, _ = find(r"월\s*통상임금\s*" + AMOUNT, "wage")
    form["normal_wage"] = _won(match[1]) if match else None
    match, _ = find(r"기본급.*?" + AMOUNT, "base")
    form["base_wage"] = _won(match[1]) if match else None
    match, _ = find(r"수습기간\s*중\s*임금\s*" + AMOUNT, "probation_wage")
    form["probation_wage"] = _won(match[1]) if match else None
    match, block = find(r"^\s*8\.\s*임금지급일\s+매월\s*\(\s*(\d*)\s*\)\s*일", "payday")
    if match:
        form["payday"] = int(match[1]) if match[1] else None
        index = blocks.index(block)
        # A handwritten note under the row ("※ 임금은 분기 말일에 일괄 지급함") changes the schedule.
        for note in blocks[index + 1:index + 3]:
            if re.search(r"분기|[2-9]\s*개월|격월|일괄\s*지급|연\s*\d+\s*회", note["text"]) and re.search(r"[가-힣]", note["text"]):
                form["payday_note"], form["payday_note_block"] = note["text"], note
                break
    match, block = find(r"^\s*9\.\s*지급방법\s+(.+)", "method")
    if block:
        form["method"] = "bank_transfer" if re.search(MARK + r"\s*통장", block["text"]) else "direct" if re.search(MARK + r"\s*직접", block["text"]) else None
        index = blocks.index(block)
        for note in blocks[index + 1:index + 4]:
            text = note["text"]
            if re.search(r"(?:통장|도장|여권|외국인등록증|신분증).*(?:보관|관리|맡)", text) and not re.search(r"해서는\s*안|아니\s*됨|금지", text) and re.search(r"[가-힣]", text):
                form["custody"], form["custody_block"] = text, note
                break
    match, block = find(r"숙박시설\s*제공\s*여부\s*[:：]", "lodging")
    if block:
        form["lodging"] = True if re.search(MARK + r"\s*제공", block["text"]) else False if re.search(MARK + r"\s*미제공", block["text"]) else None
        index = blocks.index(block)
        kinds = next((b["text"] for b in blocks[index:index + 3] if "유형" in b["text"]), "")
        form["lodging_type"] = next((name for name in TEMPORARY_HOUSING if re.search(MARK + r"\s*" + name, kinds)), None)
        form["lodging_temporary"] = form["lodging_type"] is not None
    match, _ = find(r"숙박시설\s*제공\s*시\s*근로자\s*부담금액\s*[:：]\s*매월\s*(.*)", "lodging_cost")
    if match:
        amount = re.search(r"([\d,]+)\s*원", match[1])
        form["lodging_cost"] = _won(amount[1]) if amount else None
        form["lodging_cost_text"] = match[1].strip()
    match, block = find(r"식사\s*제공\s*여부\s*[:：]", "meals")
    if block:
        form["meals"] = False if re.search(MARK + r"\s*미제공", block["text"]) else True if re.search(r"제공\s*\(.*" + MARK, block["text"]) else None
    match, _ = find(r"식사\s*제공\s*시\s*근로자\s*부담금액\s*[:：]\s*매월\s*([\d,]+)", "meal_cost")
    form["meal_cost"] = _won(match[1]) if match else None
    match, _ = find(r"입국\s*전\s*(?:확정|결정)|(?:급여|임금)에서\s*일괄\s*공제", "prearranged")
    form["prearranged_costs"] = bool(match)
    match, _ = find(r"이\s*계약에서\s*정하지\s*않은\s*사항은\s*「?근로기준법", "statute")
    form["follows_statute"] = bool(match)
    match, block = find(r"^\s*(\d{4})?\s*년\s*(\d{1,2})?\s*월\s*(\d{1,2})?\s*일\s*\(", "signed_on")
    if match:
        form["signed_on"] = f"{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}" if all(match.groups()) else None
    for role, label in (("employer", r"사용자\s*Employer"), ("worker", r"근로자\s*Employee")):
        match, block = find(label + r"\s*[:：]\s*(.*)", "sign_" + role)
        if block:
            body = match[1]
            name, _, after = body.partition("(서명")
            after = after.split(")", 1)[1] if ")" in after else ""
            words = name.split()
            # A signature shows as text after the "(서명 또는 인)" box, or the name written twice before it.
            form["signed_" + role] = bool(after.strip()) or (len(words) >= 2 and len(words) % 2 == 0 and words[:len(words)//2] == words[len(words)//2:])
    return form


def year_of(form, today=None):
    signed = form.get("signed_on")
    return int(signed[:4]) if signed else (today or date.today()).year


def minimum_monthly(year):
    hourly = MINIMUM_WAGE.get(year) or MINIMUM_WAGE[max(MINIMUM_WAGE)]
    return hourly, hourly * MONTHLY_HOURS


def _evidence(block):
    return {"block_id": block["block_id"], "page": block["page"], "start": 0, "end": len(block["text"]), "quote": block["text"]}


def terms(form):
    """Form values as extraction candidates (keys of backend.extraction.EMPLOYMENT)."""
    found = {}

    def put(key, block_key, value, normalized):
        block = form.get(block_key + "_block")
        if block and value:
            found[key] = [{"value_text": block["text"], "normalized_value": normalized, "extraction_method": "foreign_form",
                           "evidence": _evidence(block)}]

    wage = form.get("base_wage") or form.get("normal_wage")
    put("wage", "base" if form.get("base_wage") else "wage", wage, {"amount": wage, "currency": "KRW", "period": "month"})
    if form.get("payday"):
        put("payment_date", "payday", form["payday"], {"day": form["payday"], "period": "month"})
    put("work_hours", "hours", form.get("start"), {"start": form.get("start"), "end": form.get("end")})
    if form.get("break_minutes") is not None:
        put("break_time", "break", True, {"minutes": form["break_minutes"]})
    if form.get("period_months"):
        put("period", "period", True, {"start_date": None, "end_date": None, "indefinite": False,
                                       "months": form["period_months"], "text": f"입국일부터 {form['period_months']}개월"})
    put("workplace", "workplace", form.get("workplace"), {"text": form.get("workplace")})
    put("job_description", "job", form.get("job"), {"text": form.get("job")})
    put("holiday", "holiday", form.get("holiday"), {"text": form.get("holiday")})
    if form.get("method"):
        put("payment_method", "method", True, {"method": form["method"], "text": "근로자 명의 예금통장에 입금" if form["method"] == "bank_transfer" else "근로자에게 직접지급"})
    # The form has no leave row: item 12 applies 근로기준법 to everything it does not set, annual leave included.
    if form.get("follows_statute"):
        put("annual_leave", "statute", True, {"text": "근로기준법에 따름 (계약서 12항)"})
    return found


def check(form, today=None):
    """Findings for the filled form: (kind, title, why, scenario, suggestion, block, refs)."""
    out = []

    def add(kind, title, why, scenario, suggestion, block, refs=()):
        if block:
            out.append({"kind": kind, "title": title, "why": why, "scenario": scenario, "suggestion": suggestion,
                        "evidence": [_evidence(block)], "refs": refs})

    year = year_of(form, today)
    hourly, monthly = minimum_monthly(year)
    if "birthdate" in form and not form["birthdate"]:
        add("foreign_identity", "근로자 생년월일이 비어 있습니다",
            "생년월일은 근로자를 특정하는 필수 인적사항입니다. 고용허가·사증 절차에서 여권 정보와 대조되므로 비어 있으면 계약 당사자를 확인하기 어렵습니다.",
            "여권 정보와 맞지 않아 고용허가나 입국 절차가 늦어질 수 있습니다.",
            "여권과 같은 생년월일을 적는다.", form.get("birthdate_block"))
    months = form.get("period_months")
    if months and months > E9_MAX_MONTHS:
        add("foreign_period", f"계약기간 {months}개월은 취업활동기간 3년을 넘습니다",
            f"고용허가제(E-9) 외국인의 취업활동기간은 입국일부터 3년 이내이고 근로계약도 그 안에서 맺어야 합니다(외국인고용법 제9조·제18조). {months}개월은 법정 한도를 넘습니다.",
            "3년이 지난 뒤의 기간은 체류자격 없이 일하는 상황이 될 수 있습니다. 연장은 재고용 절차로 따로 진행됩니다.",
            f"신규 또는 재입국자 근로계약기간을 ( {E9_MAX_MONTHS} )개월 이내로 적는다.", form.get("period_block"))
    base = form.get("base_wage") or form.get("normal_wage")
    probation_wage = form.get("probation_wage")
    if form.get("probation") and probation_wage and base and probation_wage < base:
        floor = int(monthly * 0.9)
        add("foreign_probation_wage", "수습기간 임금을 깎아 정했습니다",
            f"수습 감액은 1년 이상 계약에서 수습 시작 후 3개월 이내만, 최저임금의 90%({floor:,}원)까지 허용되고 단순노무 업무는 아예 감액할 수 없습니다(최저임금법 제5조제2항). "
            f"수습 중 임금 {probation_wage:,}원은 {year}년 최저 월 환산액 {monthly:,}원의 {probation_wage / monthly:.0%}입니다.",
            f"처음 3개월 동안 매달 {monthly - probation_wage:,}원 이상 적게 받을 수 있습니다.",
            "수습기간을 활용하지 않거나, 활용하더라도 정상 임금과 같은 금액을 지급한다.", form.get("probation_wage_block"), (("최저임금법", 5),))
    workplace = form.get("workplace") or ""
    if re.search(r"지정|협력업체|파견|기타|등지|이외|외의?\s*장소|각\s*현장", workplace):
        add("foreign_workplace", "근로장소가 허가받은 사업장 밖까지 열려 있습니다",
            "외국인근로자는 고용허가를 받은 사업장에서만 일할 수 있고, 양식에도 '계약서에서 정한 장소 외 근로 금지'가 적혀 있습니다. 다른 사업장 투입은 근무처 변경·추가 허가 위반이나 불법파견 문제가 될 수 있습니다.",
            "대표자가 지정한 다른 회사 현장으로 보내져 허가 없이 일하게 될 수 있습니다.",
            "허가받은 사업장의 주소 하나만 구체적으로 적는다.", form.get("workplace_block"))
    job = form.get("job") or ""
    if re.search(r"일체|기타\s*(?:회사|사용자|대표)|지시하는\s*(?:모든\s*)?업무|모든\s*업무", job):
        add("foreign_job", "업무내용이 '회사가 지시하는 업무 일체'로 포괄적입니다",
            "양식은 수행할 구체적인 업무를 반드시 적도록 합니다. 종사 업무는 서면으로 밝혀야 하는 근로조건이고(근로기준법 제17조), 포괄 문구는 위험하거나 계약과 다른 업무 지시의 근거가 될 수 있습니다.",
            "계약하지 않은 위험 작업을 지시받아도 계약서로 거절하기 어려울 수 있습니다.",
            "직무내용을 구체적으로 적는다. 예: 금속부품 절삭기 소재 투입, 완제품 검수·포장", form.get("job_block"), (("근로기준법", 17),))
    if form.get("start") and form.get("end"):
        span = (_minutes(form["end"]) - _minutes(form["start"])) % (24 * 60)
        rest = form.get("break_minutes") or 0
        daily = (span - rest) / 60
        if daily > 8:
            add("foreign_hours", f"소정근로시간이 하루 {daily:g}시간입니다",
                f"{form['start']}~{form['end']}에서 휴게 {rest:g}분을 빼면 하루 {daily:g}시간입니다. 법정근로시간은 1일 8시간, 1주 40시간이라 소정근로시간 자체를 8시간 넘게 정할 수 없습니다(근로기준법 제50조).",
                "매일 연장근로가 기본 근무처럼 굳어져 추가 수당과 휴식이 줄어들 수 있습니다.",
                "근로시간을 하루 8시간 이내로 적는다. 예: 08:30 ~ 17:30 (휴게 1시간)", form.get("hours_block"), (("근로기준법", 50),))
        need = 60 if daily >= 8 else 30 if daily >= 4 else 0
        if rest < need:
            add("foreign_break", f"휴게시간 {rest:g}분이 법정 기준보다 짧습니다",
                f"근로시간이 8시간 이상이면 휴게시간은 1시간 이상이어야 합니다(근로기준법 제54조). 하루 {daily:g}시간 일하는데 휴게는 {rest:g}분입니다.",
                "쉬는 시간이 부족한 채로 장시간 일하게 되어 사고 위험이 커질 수 있습니다.",
                f"휴게시간을 1일 {need}분 이상으로 적는다.", form.get("break_block"), (("근로기준법", 54),))
        if form.get("overtime_max") is not None:
            weekly = (max(0.0, daily - 8) + form["overtime_max"]) * 5
            if weekly > 12:
                add("foreign_overtime", f"연장근로가 주 12시간을 넘게 적혀 있습니다",
                    f"연장근로는 당사자가 합의해도 1주 12시간이 한도입니다(근로기준법 제53조). 하루 평균 {form['overtime_avg']:g}시간, 최대 {form['overtime_max']:g}시간이면 주 5일만 일해도 연장근로가 최대 주 {weekly:g}시간이 됩니다.",
                    "주 52시간을 넘는 장시간 근무가 계약 내용처럼 요구될 수 있습니다.",
                    "시간외 근로를 1주 12시간 이내가 되도록 적는다. 예: 평균 1시간, 최대 2시간", form.get("overtime_block"), (("근로기준법", 53),))
    if form.get("public_holiday_paid") is False:
        add("foreign_holiday", "공휴일을 무급으로 정했습니다",
            "상시근로자 5인 이상 사업장은 관공서 공휴일을 유급휴일로 보장해야 합니다(근로기준법 제55조제2항). 4인 이하 사업장이면 적용되지 않으니 사업장 규모를 확인해야 합니다.",
            "공휴일에 쉬면 그날 임금이 빠지거나, 일해도 휴일근로 수당을 받지 못할 수 있습니다.",
            "공휴일을 [✓]유급으로 표시한다.", form.get("holiday_block"), (("근로기준법", 55),))
    if base and base < monthly:
        add("foreign_minimum_wage", f"기본급이 {year}년 최저임금보다 {monthly - base:,}원 적습니다",
            f"{year}년 최저임금은 시급 {hourly:,}원, 월 환산 {monthly:,}원(209시간)입니다. 기본급 {base:,}원은 이보다 적고, 외국인에게도 같은 최저임금이 적용됩니다(최저임금법 제6조)."
            + (" 이 금액은 2024년 최저임금(시급 9,860원 × 209시간)과 같습니다." if base == 9860 * MONTHLY_HOURS else ""),
            f"매달 {monthly - base:,}원씩, 1년이면 {(monthly - base) * 12:,}원을 덜 받게 됩니다.",
            f"기본급을 월 {monthly:,}원 이상으로 적는다.", form.get("base_block") or form.get("wage_block"), (("최저임금법", 6),))
    if "payday" in form and (not form["payday"] or form.get("payday_note")):
        add("foreign_payday", "임금을 매달 정해진 날에 주지 않습니다",
            "임금은 매월 1회 이상 일정한 날짜를 정해 지급해야 합니다(근로기준법 제43조제2항). "
            + ("지급일 칸이 비어 있고 " if not form["payday"] else "") + (f"'{form['payday_note'].lstrip('※ ').strip()}'라는 문구가 있습니다." if form.get("payday_note") else "지급일이 정해지지 않았습니다."),
            "몇 달 치 임금을 한꺼번에 받게 되어 생활비가 부족하거나 체불이 생겨도 알아채기 어렵습니다.",
            "임금지급일을 매월 ( 10 )일처럼 구체적인 날짜로 적는다.", form.get("payday_note_block") or form.get("payday_block"), (("근로기준법", 43),))
    if form.get("custody"):
        add("foreign_custody", "회사가 통장·도장·여권을 보관한다고 적혀 있습니다",
            "양식에 '사용자는 근로자 명의 통장·도장을 관리해서는 안 됨'이 적혀 있고, 임금은 근로자에게 직접·전액 지급해야 합니다(근로기준법 제43조). 여권을 계약 이행 확보 목적으로 보관하는 것도 금지됩니다(출입국관리법 제33조의3).",
            "월급이 들어와도 본인이 쓸 수 없고, 여권이 없어 일을 그만두거나 이동하기 어려워질 수 있습니다.",
            "보관 문구를 지우고 지급방법은 [✓]통장 입금만 표시한다.", form.get("custody_block"), (("근로기준법", 43),))
    lodging_cost, meal_cost = form.get("lodging_cost"), form.get("meal_cost") or 0
    reasons = []
    if form.get("prearranged_costs") or (form.get("lodging") and lodging_cost):
        reasons.append("신규 입국자의 숙식비 부담은 입국 후 협의해 정하도록 양식에 적혀 있는데, 금액을 미리 정했습니다")
    if form.get("meals") is False and meal_cost > 0:
        reasons.append(f"식사를 제공하지 않으면서 식비 월 {meal_cost:,}원을 받습니다")
    wage_base = form.get("normal_wage") or base
    if lodging_cost and wage_base:
        meals = bool(form.get("meals"))
        ceiling = LODGING_CEILING[("temporary" if form.get("lodging_temporary") else "house", meals)]
        share = (lodging_cost + (meal_cost if meals else 0)) / wage_base
        if share > ceiling:
            kind = f"{form['lodging_type']} 등 임시주거시설" if form.get("lodging_temporary") else "주택"
            reasons.append(f"고용노동부 숙식비 지침은 {kind}에서 {'숙식' if meals else '숙소만'} 제공 시 통상임금의 {ceiling:.0%}를 상한으로 두는데, 숙소비가 통상임금의 약 {share:.0%}입니다")
    if reasons:
        add("foreign_lodging", "숙식비를 미리 정해 임금에서 공제합니다",
            ". ".join(reasons) + ". 공제하려면 근로자의 서면 동의가 필요합니다.",
            f"숙식비로 매달 {lodging_cost + meal_cost:,}원이 빠져 실제 받는 돈이 크게 줄 수 있습니다." if lodging_cost else "실제 받는 임금이 예상보다 줄 수 있습니다.",
            "숙소 유형을 표시하고 비용은 '입국 후 협의 결정'으로 적는다. 식사를 제공하지 않으면 식비는 0원으로 한다.",
            form.get("lodging_cost_block") or form.get("prearranged_block"))
    if "signed_on" in form and (not form["signed_on"] or form.get("signed_worker") is False):
        missing = [label for label, gap in (("작성일", not form["signed_on"]), ("근로자 서명", form.get("signed_worker") is False)) if gap]
        add("foreign_signature", f"{'·'.join(missing)}이 없습니다",
            "근로조건은 서면으로 밝히고 근로자에게 교부해야 합니다(근로기준법 제17조). 근로자 서명이 없으면 합의했다는 사실을, 작성일이 없으면 계약 시점을 확인하기 어렵습니다.",
            "나중에 근로조건을 두고 다툴 때 이 계약서가 언제, 누구와 합의한 것인지 증명하기 어려울 수 있습니다.",
            "작성일을 적고 사용자와 근로자가 모두 서명한 뒤 근로자에게 1부를 준다.",
            form.get("sign_worker_block") if form.get("signed_worker") is False else form.get("signed_on_block"), (("근로기준법", 17),))
    return out
