"""Remedy routes (권익구제) per issue: what to do, where to go, deadlines. Static, sourced, reviewed by people.

Contacts change. Entries marked verify=True were not confirmed against an official page when written
and must be checked before release; the agent tells users to confirm on the official site.
"""
CHECKED = "2026-11"

AGENCIES = {
    "moel": {"name": "고용노동부 고객상담센터", "contact": "국번 없이 1350", "url": "https://www.moel.go.kr", "verify": False},
    "labor_portal": {"name": "고용노동부 노동포털 (임금체불 등 진정 접수)", "contact": "온라인 민원", "url": "https://labor.moel.go.kr", "verify": False},
    "klac": {"name": "대한법률구조공단", "contact": "국번 없이 132", "url": "https://www.klac.or.kr", "verify": False},
    "foreign_worker": {"name": "외국인력상담센터 (다국어 상담)", "contact": "1577-0071", "url": "https://www.eps.go.kr", "verify": False},
    "nlrc": {"name": "노동위원회 (부당해고 구제신청)", "contact": "관할 지방노동위원회", "url": "https://www.nlrc.go.kr", "verify": False},
    "lease_mediation": {"name": "주택임대차분쟁조정위원회", "contact": "대한법률구조공단 132로 안내", "url": "https://www.klac.or.kr", "verify": True},
    "jeonse_center": {"name": "전세피해지원센터 (주택도시보증공사)", "contact": "1533-8119", "url": "https://www.khug.or.kr", "verify": True},
}

REMEDIES = {
    "penalty": {"title": "퇴사·불이행 위약금 요구",
                "steps": ["위약금·손해배상액을 미리 정한 조항과 실제 요구 내용(문자·녹음)을 보관한다.",
                          "요구받은 돈을 바로 내거나 임금에서 빼는 데 동의하지 않고, 서면으로 근거를 요청한다.",
                          "임금에서 공제됐다면 급여명세서와 이체내역을 모아 진정을 검토한다."],
                "agencies": ["moel", "labor_portal", "klac"], "laws": [("근로기준법", "20"), ("근로기준법", "43")], "deadlines": []},
    "wage_deduction": {"title": "임금에서 손해·벌금 공제",
                       "steps": ["공제된 금액·날짜를 급여명세서와 통장 내역으로 정리한다.", "공제 근거(법령·단체협약·본인 동의 여부)를 서면으로 묻는다.",
                                 "미지급분은 노동포털에서 임금체불 진정을 검토한다."],
                       "agencies": ["moel", "labor_portal"], "laws": [("근로기준법", "43"), ("근로기준법", "49")], "deadlines": ["임금채권은 3년 동안 행사하지 않으면 소멸한다(근로기준법 제49조)."]},
    "unpaid_wage": {"title": "임금·수당 미지급",
                    "steps": ["근무 일정·출퇴근 기록, 급여명세서, 계약서, 대화 기록을 모은다.", "받아야 할 금액과 실제 받은 금액의 차이를 계산한다.",
                              "사업주에게 서면으로 지급을 요청하고, 지급되지 않으면 노동포털이나 관할 고용노동관서에 진정한다."],
                    "agencies": ["moel", "labor_portal", "klac", "foreign_worker"], "laws": [("근로기준법", "43"), ("근로기준법", "36"), ("근로기준법", "49")],
                    "deadlines": ["임금채권은 3년 동안 행사하지 않으면 소멸한다(근로기준법 제49조)."]},
    "minimum_wage": {"title": "최저임금보다 적은 임금",
                     "steps": ["시급·근무시간·주휴수당 포함 여부를 확인하고 최저임금과 비교한다.", "수습 감액이나 산입 범위 예외에 해당하는지 확인한다.",
                               "부족분을 정리해 사업주에게 요청하고, 해결되지 않으면 진정한다."],
                     "agencies": ["moel", "labor_portal", "foreign_worker"], "laws": [("최저임금법", "6"), ("근로기준법", "49")], "deadlines": ["임금채권은 3년 동안 행사하지 않으면 소멸한다(근로기준법 제49조)."]},
    "included_allowance": {"title": "연장·야간·휴일 수당 포함(포괄임금) 문제",
                           "steps": ["실제 연장·야간·휴일 근무시간을 기록한다.", "임금 구성(기본급·수당별 금액과 대상 시간)을 서면으로 요청한다.",
                                     "포함된 금액보다 실제 수당이 많다면 차액 지급을 요청하고 상담한다."],
                           "agencies": ["moel", "labor_portal"], "laws": [("근로기준법", "56"), ("근로기준법", "17")], "deadlines": []},
    "no_written_contract": {"title": "근로계약서를 받지 못함",
                            "steps": ["근무 시작일·시급·근무시간 등 들은 조건과 그 증거(문자·공고)를 모은다.", "근로계약서 서면 교부를 요청한다(권리ON 교부 요청서 활용).",
                                      "교부하지 않으면 고용노동부에 상담하거나 진정을 검토한다."],
                            "agencies": ["moel", "labor_portal", "foreign_worker"], "laws": [("근로기준법", "17")], "deadlines": []},
    "noncompete": {"title": "경업·겸직 금지",
                   "steps": ["금지 기간·지역·업종 범위와 대가(보상) 지급 여부를 확인한다.", "범위가 넓거나 보상이 없다면 수정을 요청하고, 분쟁이 생기면 상담한다."],
                   "agencies": ["klac"], "laws": [], "deadlines": []},
    "unilateral_change": {"title": "근무지·업무·조건의 일방적 변경",
                          "steps": ["변경 통보 내용과 날짜를 보관한다.", "변경 사유와 범위를 서면으로 확인하고, 동의하지 않는다는 의사를 기록으로 남긴다."],
                          "agencies": ["moel", "klac"], "laws": [("근로기준법", "17")], "deadlines": []},
    "probation": {"title": "수습 기간 조건",
                  "steps": ["수습 기간·임금 감액 비율·종료 후 조건을 확인한다.", "최저임금 감액 허용 요건(기간·직종)에 맞는지 상담한다."],
                  "agencies": ["moel"], "laws": [("최저임금법", "5")], "deadlines": []},
    "dismissal": {"title": "해고·계약 종료 통보",
                  "steps": ["해고 통보서(서면 여부·사유·날짜)를 보관한다.", "부당해고라고 생각되면 노동위원회 구제신청을 검토한다."],
                  "agencies": ["nlrc", "moel", "klac"], "laws": [("근로기준법", "23"), ("근로기준법", "27"), ("근로기준법", "28")],
                  "deadlines": ["부당해고 구제신청은 해고가 있었던 날부터 3개월 이내에 해야 한다(근로기준법 제28조)."]},
    "deposit_return": {"title": "보증금 반환 지연·거부",
                       "steps": ["계약서, 보증금 이체내역, 반환 요청 문자·내용증명을 보관한다.", "이사 전 대항력·우선변제권 유지 방법(임차권등기명령 등)을 상담한다.",
                                 "협의가 안 되면 주택임대차분쟁조정이나 소송을 검토한다."],
                       "agencies": ["klac", "lease_mediation"], "laws": [("주택임대차보호법", "3")], "deadlines": []},
    "jeonse_fraud": {"title": "전세사기 피해 의심",
                     "steps": ["등기사항증명서, 계약서, 이체내역, 중개인·임대인과의 대화를 모은다.", "전세피해지원센터에서 피해 상담과 지원 요건을 확인한다.",
                               "이사하기 전에 임차권등기명령 등 권리 보전 방법을 상담한다."],
                     "agencies": ["jeonse_center", "klac"], "laws": [("주택임대차보호법", "3")], "deadlines": []},
}


def guide(issue_type):
    entry = REMEDIES.get(issue_type)
    if entry is None:
        return {"found": False, "available": sorted(REMEDIES)}
    return {"found": True, "issue_type": issue_type, "title": entry["title"], "steps": entry["steps"],
            "agencies": [AGENCIES[a] for a in entry["agencies"]],
            "laws_to_lookup": [{"law_title": law, "article_number": number} for law, number in entry["laws"]],
            "deadlines": entry["deadlines"],
            "note": f"연락처·절차는 {CHECKED} 기준입니다. verify가 true인 기관은 공식 사이트에서 다시 확인하도록 안내하세요. 법령 내용은 lookup_law로 확인한 뒤 인용하세요."}
