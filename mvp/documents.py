"""Drafts use traceable facts; language guides keep amounts and evidence intact."""
from mvp.analysis import QUESTION_LABELS


def draft(result, kind, incident=None):
    incident = incident.model_dump() if hasattr(incident, "model_dump") else (incident or {})
    facts = []
    for term in (result or {}).get("terms", []):
        if term["status"] == "found":
            value = term["candidates"][0]
            facts.append({"label": term["label"], "value": value["value_text"], "origin": "document", "evidence": value["evidence"]})
    for key, value in (result or {}).get("context", {}).items():
        if value is not None and value != "unknown":
            label = QUESTION_LABELS[key]
            text = "예" if value is True else "아니오" if value is False else str(value)
            facts.append({"label": label, "value": text, "origin": "user_confirmed", "context_key": key})
    if kind in {"lawyer_request", "help_request", "complaint"}:
        return action_draft(result, kind, incident, facts)
    fact_lines = [f"- {f['label']}: {f['value']}" for f in facts]
    conflicts = [t["label"] for t in result["terms"] if t["status"] == "conflict"]
    missing = ["작성자", "수신인", "작성일"] + [t["label"] for t in result["terms"] if t["status"] != "found"]
    title = "상담 준비 요약서" if kind == "summary" else "계약조건 사실확인 요청문"
    text = [title, "", f"대상 문서: {result['title']}", "작성자: [직접 입력]", "수신인: [직접 입력]", "작성일: [직접 입력]", "", "1. 문서와 사용자 답변에서 확인한 사실", *fact_lines]
    if kind == "summary":
        text += ["", "2. 상담에서 확인할 사항", *[f"- {i['title']}: {i['explanation_ko']}" for i in result["issues"]], "", "3. 준비할 자료와 다음 행동", *["- " + a for a in result["actions"]]]
    else:
        text += ["", "2. 확인 요청", "아래 계약조건의 내용과 적용 근거를 서면으로 확인해 주시기 바랍니다.", *[f"- {i['title']}" for i in result["issues"]], "답변 희망일: [직접 입력]", "", "3. 첨부 자료", "계약서·별첨·관련 기록: [직접 확인 후 입력]"]
    if conflicts:
        text += ["", "서로 다른 후보가 있어 확정하지 않은 항목: " + ", ".join(conflicts)]
    text += ["", "검토 메모: 이 초안은 원문과 사용자 답변을 정리한 자료입니다. 사실·날짜·수신인을 검토하고 수정하세요."]
    return {"analysis_revision": result["analysis_revision"], "kind": kind, "draft_text": "\n".join(text), "facts_used": facts, "missing_fields": missing, "review_required": True}


def action_draft(result, kind, incident, document_facts):
    """Use explicit incident facts; contractual sums are never claimed damages."""
    from mvp.knowledge import Knowledge
    labels = {"writer": "작성자", "counterparty": "상대방", "date": "사건 시점", "place": "사건 장소", "summary": "사건 경위", "loss": "사용자가 주장하는 피해", "evidence": "보유 자료", "desired_outcome": "요청하는 도움"}
    reported = [{"label": label, "value": incident.get(key, "").strip(), "origin": "user_reported", "incident_key": key}
                for key, label in labels.items() if incident.get(key, "").strip()]
    def supplied(key, placeholder="[직접 입력]"):
        return incident.get(key, "").strip() or placeholder
    findings = (result or {}).get("review", {}).get("findings", [])
    clauses = [f"- {f['title']}\n  원문: “{f['evidence'][0]['quote']}”\n  확인할 부담: {f['why_unfavorable']}" for f in findings]
    missing = [label for key, label in labels.items() if not incident.get(key, "").strip()] + ["수신 기관·수신인", "작성일", "작성자 연락처·주소", "서명"]
    sources = []
    if kind == "complaint":
        if len(incident.get("summary", "").strip()) < 20:
            raise ValueError("고소 초안에는 실제로 있었던 일을 20자 이상 입력해주세요.")
        missing += ["죄명 및 범죄 성립에 관한 검토", "피고소인 인적 사항", "사건 순서와 개별 행위의 구체적 일시"]
        title = "고소장 초안"
        lines = [title, "", "수신: [관할 경찰관서 직접 확인 후 입력]", "", "1. 고소인", f"성명: {supplied('writer')}", "주소·연락처: [직접 입력]", "", "2. 피고소인", f"성명·명칭: {supplied('counterparty', '[알고 있는 정보만 입력]')}", "주소·연락처·기타 식별 정보: [알고 있는 정보만 입력]", "", "3. 고소 취지", "아래 기재한 사실과 관련하여 피고소인의 행위에 범죄 혐의가 있는지 조사하여 주시고, 범죄가 확인될 경우 법에 따라 처리하여 주시기 바랍니다.", "죄명: [구체적인 사실과 법률 검토 후 입력 — 현재 미확정]", "", "4. 사건 경위 (고소인의 설명)", f"사건 시점: {supplied('date')}", f"장소: {supplied('place')}", supplied("summary"), "", "5. 피해 내용 (고소인의 주장)", supplied("loss", "[실제로 지급하거나 잃은 금액·피해 내용과 계산 근거 입력]"), "", "6. 증거 및 참고 자료", supplied("evidence", "[보유 중인 자료만 이름·날짜와 함께 입력]"), "자료별로 어떤 사실을 보여주는지와 제출 가능 여부: [직접 입력]", "", "7. 추가 요청", supplied("desired_outcome", "[수사기관에 설명하고 싶은 내용 입력]")]
        if result:
            lines += ["", "별첨 A. 관련 계약 문구 (범죄 발생을 확인한 사실이 아님)", f"대상 계약서: {result['title']}", *(clauses or ["이번 검토에서 별도로 표시한 주의 조항 없음."])]
        lines += ["", "작성일: [직접 입력]", f"고소인: {supplied('writer')} (서명 또는 날인)", "", "작성 전 확인: 위 경위와 피해는 사용자가 설명한 내용입니다. 계약상 불이행만으로 범죄가 성립한다고 판단하지 않았으며, 상대방의 구체적 행위·계약 당시 설명·지급 및 대화 기록을 확인해야 합니다. 사실과 다른 내용은 삭제하고 모르는 사항은 모름으로 표시하세요."]
        for number in (223, 237):
            source = Knowledge().lookup("형사소송법", number)
            if source:
                sources.append(source)
        lines += ["", "절차 확인용 법령 (범죄 성립을 판단하는 근거가 아님)", *[s["title"] + ": " + s["official_url"] for s in sources]]
    else:
        lawyer = kind == "lawyer_request"
        title = "변호사 상담 요청문" if lawyer else "도움 요청문"
        lines = [title, "", "수신: [변호사·상담기관 직접 입력]" if lawyer else "수신: [도움을 요청할 사람·기관 직접 입력]", f"작성자: {supplied('writer')}", "회신 연락처: [직접 입력]", "작성일: [직접 입력]", "", "안녕하세요. 아래 계약 또는 사건과 관련해 도움을 요청드립니다.", "", "1. 제가 설명하는 상황", f"상대방: {supplied('counterparty', '[알고 있는 정보 입력]')}", f"시점: {supplied('date')}", f"장소: {supplied('place')}", supplied("summary", "[현재 상황과 상대방의 구체적인 말·행동을 입력]"), "", "2. 계약서에서 확인한 내용"]
        if result:
            lines += [f"대상 문서: {result['title']}", f"검토 입장: {result.get('review', {}).get('role_label', '계약 당사자')}", *[f"- {f['label']}: {f['value']}" for f in document_facts if f["origin"] == "document"], "", "제가 검토받고 싶은 조항", *(clauses or ["이번 검토 범위에서 불리한 조항이 발견되지 않았거나 별도 주의 조항이 표시되지 않았습니다."])]
        else:
            lines += ["[관련 계약서나 합의가 있으면 자료를 첨부하고 조항을 입력]"]
        lines += ["", "3. 요청드리는 도움", supplied("desired_outcome", "불리한 약정의 의미와 수정 필요성, 현재 사실관계에서 가능한 대응 방법, 추가로 준비할 자료를 검토해 주시기 바랍니다." if lawyer else "위 상황을 이해하고 필요한 상담이나 대응을 준비할 수 있도록 도움을 부탁드립니다."), *[f"- ‘{f['title']}’ 조항을 수정하거나 삭제할 필요가 있는지 확인 부탁드립니다." for f in findings], "", "4. 피해 또는 부담 (사용자 설명)", supplied("loss", "[실제로 발생한 피해와 앞으로 우려되는 부담을 구분해 입력]"), "", "5. 제가 보유한 자료", supplied("evidence", "[계약서·이체내역·메시지 등 실제 보유 자료 입력]"), "", "확인한 사실과 아직 모르는 부분을 함께 검토받고 싶습니다. 가능한 상담 일정과 추가로 필요한 자료를 알려주시면 감사하겠습니다.", "", "작성 메모: 위 사건 경위는 사용자의 설명이며, 계약 문구만으로 피해 발생이나 범죄를 확인하지 않았습니다. 빈칸과 인적 사항을 검토한 뒤 사용하세요."]
    return {"analysis_revision": (result or {}).get("analysis_revision"), "kind": kind, "title": title,
            "draft_text": "\n".join(lines), "facts_used": reported + (document_facts if kind != "complaint" else []),
            "contract_clauses_used": [f["evidence"] for f in findings], "missing_fields": list(dict.fromkeys(missing)), "sources": sources, "review_required": True}


GUIDES = {
    "zh": {
        "heading": "合同核对指南", "notice": "此指南为核对合同的参考资料，尚未经过法律及语言专家审核。不能仅凭合同判断违法或诈骗。请同时查看韩文原文及法律依据。",
        "facts": "从韩文合同中提取的内容（保留原文、数字和单位）",
        "labels": ["工资", "支付日", "工作时间", "每周工作时间", "休息时间", "合同期限", "工作地点", "休息日", "押金", "月租", "租赁房屋", "押金退还条件"],
        "extra_labels": {"job_description": "工作内容", "payment_method": "工资支付方式", "annual_leave": "带薪年假", "work_days": "工作日"},
        "statuses": {"found": "已提取，请核对原文", "not_found": "未找到", "conflict": "存在多个不同值，需要确认"},
        "issues": {
            "contract_period": "请确认合同是否约定期限，并核对开始日期及适用的结束日期。",
            "missing_terms": "缺少部分合同信息。请检查其他页面及附件，并书面确认不明确的条件。",
            "conflicting_terms": "存在多个不同值或表述。请核对各项目及变更协议，确认适用内容。",
            "wage_period": "请确认工资是时薪、月薪还是年薪，以及计算和支付方式。",
            "penalty": "发现赔偿相关表述。请区分预先约定的违约赔偿与实际损失，并咨询具体适用条件。",
            "included_allowance": "请确认加班、夜间或休息日津贴的项目、金额及实际工作时间。还需确认工作场所规模等条件。",
            "hours_context": "合同时间与用户填写的实际工作时间不同。请核对考勤和加班记录。",
            "work_hours": "每周工作时间超过40小时。请核对休息时间、加班协议及适用例外，不能仅凭此认定违法。",
            "break_time": "未找到休息时间。请确认实际工作时长、休息时间及是否可自由利用。",
            "lease_registration": "请核对入住、居民登记及相关日期。仅完成手续不能确认权利顺位或押金能否收回。",
            "deposit_return": "请确认押金退还日期及扣款理由，并保留合同、付款和沟通记录。",
            "deposit_unreturned": "用户表示未全额收到押金。请整理合同终止、催还经过、未返还金额及对方答复；这不等于已确认诈骗。",
            "review_scope": "已找到本次核对范围内的基本项目。工资金额是否适当、实际履行及所有特别条款效力需要另行核查。",
        },
        "questions": {"document_complete": "是否已输入合同全部页面及附件？", "event_date": "所核对的合同或事件发生日期是什么？", "workplace_size": "工作场所的常用劳动者人数属于哪个范围？", "weekly_work_hours": "实际每周工作多少小时？", "move_in": "是否已接收房屋并入住？", "resident_registration": "是否已办理该房屋的迁入登记？", "deposit_returned": "合同结束后，是否已全额收到押金？"},
        "old_version": "需要另行核对事件当时适用的法律版本。",
        "actions": ["保留合同、附件、付款及沟通记录。", "向合同对方书面确认不明确的条件。", "携带相关资料向专业机构咨询。"],
    },
    "es": {
        "heading": "Guía para revisar el contrato", "notice": "Esta guía aún no ha sido revisada por especialistas jurídicos y lingüísticos. El contrato por sí solo no permite confirmar una infracción o un fraude. Consulte también el original coreano y las fuentes legales.",
        "facts": "Datos extraídos del contrato coreano (se conservan el texto, las cifras y las unidades originales)",
        "labels": ["Salario", "Día de pago", "Horario de trabajo", "Horas semanales", "Descanso", "Duración del contrato", "Lugar de trabajo", "Días de descanso", "Depósito", "Alquiler mensual", "Vivienda arrendada", "Condiciones de devolución del depósito"],
        "extra_labels": {"job_description": "Funciones", "payment_method": "Método de pago", "annual_leave": "Vacaciones anuales pagadas", "work_days": "Días de trabajo"},
        "statuses": {"found": "Extraído; revise el original", "not_found": "No encontrado", "conflict": "Hay varios valores; confirme cuál corresponde"},
        "issues": {
            "contract_period": "Confirme si el contrato tiene una duración determinada y compruebe las fechas de inicio y, cuando corresponda, de finalización.",
            "missing_terms": "Faltan algunos datos del contrato. Revise las demás páginas y los anexos, y confirme por escrito las condiciones poco claras.",
            "conflicting_terms": "Hay valores o expresiones diferentes. Revise los componentes y los acuerdos de modificación para confirmar qué condiciones se aplican.",
            "wage_period": "Confirme si el salario es por hora, mensual o anual, y cómo se calcula y paga.",
            "penalty": "Se detectaron expresiones relativas a indemnizaciones. Distinga una cantidad fijada por incumplir el contrato de los daños reales y consulte las condiciones aplicables.",
            "included_allowance": "Confirme los conceptos y cantidades de los complementos por horas extra, trabajo nocturno o en días de descanso, así como las horas reales y el tamaño del centro de trabajo.",
            "hours_context": "Las horas del contrato difieren de las indicadas por el usuario. Compare los registros de asistencia y las horas extra.",
            "work_hours": "Las horas semanales superan las 40. Compruebe los descansos, el acuerdo de horas extra y las excepciones aplicables; esto por sí solo no confirma una infracción.",
            "break_time": "No se encontró el descanso. Confirme la duración real del trabajo, los descansos y si pueden utilizarse libremente.",
            "lease_registration": "Compruebe la entrega de la vivienda, el registro de residencia y las fechas. Completar estos trámites no confirma la prioridad de derechos ni la recuperación del depósito.",
            "deposit_return": "Confirme la fecha de devolución del depósito y los motivos de las deducciones. Guarde el contrato, los pagos y las comunicaciones.",
            "deposit_unreturned": "El usuario indica que no recibió todo el depósito. Organice la terminación del contrato, las solicitudes, la cantidad pendiente y las respuestas. Esto no confirma un fraude.",
            "review_scope": "Se encontraron los datos básicos del alcance de esta revisión. La adecuación del salario, el cumplimiento real y la validez de todas las cláusulas especiales requieren otra revisión.",
        },
        "questions": {"document_complete": "¿Se incluyeron todas las páginas y los anexos?", "event_date": "¿Cuál es la fecha del contrato o del hecho que desea revisar?", "workplace_size": "¿Cuál es el rango del número habitual de trabajadores?", "weekly_work_hours": "¿Cuántas horas trabaja realmente por semana?", "move_in": "¿Ha recibido la vivienda y se ha instalado en ella?", "resident_registration": "¿Ha registrado su residencia en esa vivienda?", "deposit_returned": "¿Recibió todo el depósito después de finalizar el contrato?"},
        "old_version": "Es necesario comprobar la versión de la ley aplicable en la fecha del hecho.",
        "actions": ["Guarde el contrato, los anexos, los pagos y las comunicaciones.", "Confirme por escrito las condiciones poco claras con la otra parte.", "Consulte a una entidad especializada con la documentación."],
    },
}


def translate(result, language):
    guide = GUIDES[language]
    keys = ["wage", "payment_date", "work_hours", "weekly_hours", "break_time", "period", "workplace", "holiday", "deposit", "rent", "address", "return_terms"]
    labels = dict(zip(keys, guide["labels"]))
    labels.update(guide["extra_labels"])
    context_keys = list(QUESTION_LABELS)
    context_labels = dict(zip(context_keys, ["全部页面及附件", "合同或事件日期", "常用劳动者人数", "实际每周工作时间", "已接收房屋并入住", "已办理迁入登记", "合同结束后已全额收到押金"] if language == "zh" else ["Todas las páginas y anexos", "Fecha del contrato o del hecho", "Número habitual de trabajadores", "Horas reales por semana", "Vivienda recibida y ocupada", "Residencia registrada", "Depósito recibido íntegramente al finalizar el contrato"]))
    value_labels = {"true":"是", "false":"否", "under5":"少于5人", "5plus":"5人或以上"} if language == "zh" else {"true":"Sí", "false":"No", "under5":"Menos de 5", "5plus":"5 o más"}
    context_facts = [{"key": key, "label": context_labels[key], "raw_value": value,
                      "text": value_labels.get(str(value).lower(), str(value))}
                     for key, value in result["context"].items() if value is not None and value != "unknown"]
    return {"analysis_revision": result["analysis_revision"], "language": language, "method": "template-v1",
            "review_required": True, "heading": guide["heading"], "notice": guide["notice"], "facts_heading": guide["facts"],
            "terms": [{"key": t["key"], "label": labels.get(t["key"], t["label"]), "status_text": guide["statuses"][t["status"]], "candidates": t["candidates"]} for t in result["terms"]],
            "issues": [{"issue_id": i["issue_id"], "status": i["status"], "text": guide["issues"].get(i["issue_type"], ("此新增条款尚无翻译，请查看韩文说明：" if language == "zh" else "Esta cláusula nueva todavía no tiene traducción. Consulte la explicación en coreano: ") + i["explanation_ko"]) + (" " + guide["old_version"] if i["status"] == "insufficient_evidence" else ""), "source_ids": i["source_ids"], "evidence": i["evidence"]} for i in result["issues"]],
            "questions": [{**q, "text": guide["questions"][q["context_key"]]} for q in result["questions"]],
            "actions": guide["actions"], "sources": result["sources"],
            "context_heading": "用户提供的信息" if language == "zh" else "Información indicada por el usuario", "context_facts": context_facts,
            "validation": {"values_preserved": True, "source_ids_preserved": True, "context_preserved": True, "meaning_reviewed": False}}
