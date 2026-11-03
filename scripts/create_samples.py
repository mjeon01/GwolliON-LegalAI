#!/usr/bin/env python3
"""Create the contracts shown on the samples page. All parties are fictional."""
import json
import os
from pathlib import Path

import fitz
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]


def employment(employer, address, ceo, phone, worker, worker_address, worker_phone, signed, period, place, job, hours, days, weekly, wage, extras):
    return [
        ("title", "근 로 계 약 서"),
        ("text", f"{employer}(이하 “사업주”라 함)과 {worker}(이하 “근로자”라 함)은"),
        ("text", "다음과 같이 근로계약을 체결한다."),
        ("gap", ""),
        ("text", f"1. 근로계약기간 : {period}"),
        ("text", f"2. 근무장소 : {place}"),
        ("text", f"3. 업무의 내용 : {job}"),
        ("text", f"4. 소정근로시간 : {hours}"),
        ("text", f"5. 근무일/휴일 : {days}"),
        ("text", f"   주당 {weekly}시간 근무"),
        ("text", "6. 임금"),
        ("text", f"   - 월급 : {wage}"),
        ("text", "   - 임금지급일 : 매월 25일(휴일의 경우는 전일 지급)"),
        ("text", "   - 지급방법 : 근로자 명의 예금통장에 입금"),
        ("text", "7. 연차유급휴가 : 연차유급휴가는 근로기준법에서 정하는 바에 따라 부여함"),
        ("text", "8. 사회보험 적용여부 : 고용보험, 산재보험, 국민연금, 건강보험 모두 가입"),
        ("text", "9. 근로계약서 교부 : 사업주는 계약 체결과 동시에 사본을 근로자에게 교부함"),
        ("text", "10. 기타 사항"),
        *[("text", f"   - {line}") for line in extras],
        ("gap", ""),
        ("center", signed),
        ("gap", ""),
        ("text", f"(사업주) 사업체명 : {employer}      전화 : {phone}"),
        ("text", f"         주    소 : {address}"),
        ("text", f"         대 표 자 : {ceo}   (인)"),
        ("gap", ""),
        ("text", f"(근로자) 주    소 : {worker_address}"),
        ("text", f"         연 락 처 : {worker_phone}"),
        ("text", f"         성    명 : {worker}   (서명)"),
    ]


LEASE = [
    ("title", "주 택 임 대 차 계 약 서"),
    ("text", "임대인과 임차인은 아래 부동산에 관하여 다음과 같이 임대차계약을 체결한다."),
    ("gap", ""),
    ("heading", "1. 부동산의 표시"),
    ("text", "   소재지 : 서울특별시 은평구 연서로 214-7, 3층 302호"),
    ("text", "   구조·용도 : 철근콘크리트 / 다세대주택, 전용면적 39.6㎡"),
    ("gap", ""),
    ("heading", "2. 계약 내용"),
    ("text", "   보증금 : 금 50,000,000원"),
    ("text", "   월세 : 금 450,000원 (매월 5일 지급)"),
    ("text", "   계약금 : 금 5,000,000원은 계약 시 지급하고 영수함"),
    ("text", "   잔금 : 금 45,000,000원은 2026년 12월 5일 지급함"),
    ("text", "   임대차기간 : 2026년 12월 5일부터 2028년 12월 4일까지"),
    ("gap", ""),
    ("heading", "3. 일반 조항"),
    ("text", "   제1조 임차인은 임대인의 동의 없이 주택을 전대하거나 임차권을 양도하지 못한다."),
    ("text", "   제2조 관리비와 수도·전기·가스 요금은 임차인이 사용량에 따라 납부한다."),
    ("text", "   제3조 계약이 종료되면 임차인은 주택을 원상으로 회복하여 임대인에게 반환한다."),
    ("gap", ""),
    ("heading", "4. 특약사항"),
    ("text", "   1) 임대인은 새 임차인이 구해진 후 보증금을 반환한다."),
    ("text", "   2) 건물 노후로 인한 누수 등 모든 수리비는 임차인이 부담한다."),
    ("text", "   3) 임차인은 전입신고 및 확정일자 취득을 하지 못한다."),
    ("text", "   4) 임대인은 퇴거 시 보증금에서 수리비를 일방적으로 공제한다."),
    ("gap", ""),
    ("center", "2026년 11월 20일"),
    ("gap", ""),
    ("text", "임대인  주소 : 서울특별시 은평구 연서로 214-7, 1층      연락처 : 010-****-6204"),
    ("text", "        성명 : 이정숙   (인)"),
    ("gap", ""),
    ("text", "임차인  주소 : 서울특별시 서대문구 증가로 88, 201호      연락처 : 010-****-1837"),
    ("text", "        성명 : 박지훈   (인)"),
]

CASES = [
    {"id": "employment-cafe", "title": "카페 직원 근로계약서", "contract_type": "employment", "tag": "불리한 조항", "description": "수습 무급, 임금 공제, 퇴사 위약금이 들어 있는 계약입니다.",
     "context": {"document_complete": True, "event_date": "2026-11-16"}, "pages": employment(
        "카페 모래내길", "서울특별시 마포구 성산로 148-2, 1층", "정민호", "02-****-7714", "김서연", "서울특별시 마포구 월드컵로 31길 9, 202호", "010-****-3921", "2026년 11월 9일",
        "2026년 11월 16일부터 2027년 11월 15일까지", "카페 모래내길 매장 (서울특별시 마포구 성산로 148-2, 1층)", "음료 제조, 매장 관리 및 고객 응대",
        "09시 00분부터 18시 00분까지 (휴게시간 : 12시 00분 ~ 13시 00분)", "매주 5일(화요일~토요일) 근무, 주휴일 매주 일요일", 40, "2,300,000원",
        ["수습기간 1개월은 교육 기간으로 보아 무급으로 한다.", "근로자의 실수로 발생한 손해 및 재고 부족분은 월급에서 공제한다.", "계약기간 중 퇴사하는 경우 위약금으로 월급 1개월분을 지급한다.", "이 계약에 정함이 없는 사항은 근로기준법령에 의함"]),
     "expected": {"wage": 2300000, "wage_status": "found", "finding_types": ["penalty", "wage_deduction", "unpaid_trial"]},
     "translations": {"zh": {"title": "咖啡店员工劳动合同", "tag": "不利条款", "description": "包含试用期无薪、工资扣款和离职违约金。"}, "es": {"title": "Contrato de empleado de cafetería", "tag": "Cláusulas desfavorables", "description": "Incluye prueba sin sueldo, deducciones salariales y penalización por renuncia."}}},
    {"id": "employment-office", "title": "디자인 회사 근로계약서", "contract_type": "employment", "tag": "불리한 조항", "description": "수당 포함, 연차 포기, 퇴사 후 이직 제한이 들어 있는 계약입니다.",
     "context": {"document_complete": True, "event_date": "2026-11-16", "workplace_size": "5plus"}, "pages": employment(
        "주식회사 세움디자인랩", "서울특별시 성동구 왕십리로 58, 5층", "한지원", "02-****-3380", "최민재", "경기도 성남시 분당구 정자일로 72, 806호", "010-****-5512", "2026년 11월 13일",
        "2026년 11월 16일부터 2027년 11월 15일까지", "본사 사무실 (서울특별시 성동구 왕십리로 58, 5층)", "브랜드 및 웹 디자인 업무",
        "09시 30분부터 18시 30분까지 (휴게시간 : 12시 30분 ~ 13시 30분)", "매주 5일(월요일~금요일) 근무, 주휴일 매주 일요일", 40, "3,100,000원",
        ["월급에는 연장·야간·휴일근로 수당이 모두 포함된 것으로 본다.", "근로자는 연차휴가 사용 권리를 포기하고 회사 일정에 따른다.", "퇴사 후 2년간 동종 업계 취업을 금지하며 위반 시 책임을 진다.", "이 계약에 정함이 없는 사항은 근로기준법령에 의함"]),
     "expected": {"wage": 3100000, "wage_status": "found", "finding_types": ["included_allowance", "leave_waiver", "noncompete"]},
     "translations": {"zh": {"title": "设计公司劳动合同", "tag": "不利条款", "description": "包含工资含加班费、放弃年假和离职后就业限制。"}, "es": {"title": "Contrato de empresa de diseño", "tag": "Cláusulas desfavorables", "description": "Incluye horas extra en el salario, renuncia a vacaciones y restricción de empleo."}}},
    {"id": "employment-logistics", "title": "물류센터 근로계약서", "contract_type": "employment", "tag": "불리한 조항", "description": "파손 공제, 중도 퇴사 배상, 서로 다른 월급, 긴 근무시간을 확인해보세요.",
     "context": {"document_complete": True, "event_date": "2026-11-16", "workplace_size": "5plus"}, "pages": employment(
        "주식회사 다온물류서비스", "인천광역시 서구 봉수대로 412", "오세훈", "032-****-9021", "정태윤", "인천광역시 서구 검단로 233, 1104호", "010-****-7746", "2026년 11월 12일",
        "2026년 11월 16일부터 2027년 11월 15일까지", "다온물류 인천센터 (인천광역시 서구 봉수대로 412)", "입출고 관리 및 상품 분류",
        "08시 00분부터 18시 00분까지 (휴게시간 : 12시 00분 ~ 13시 00분)", "매주 6일(월요일~토요일) 근무, 주휴일 매주 일요일", 54, "2,800,000원",
        ["특약 월급 : 2,600,000원 (입사 후 6개월간 적용)", "화물 파손 또는 분실로 인한 손해는 해당 금액을 임금에서 공제한다.", "중도 퇴사 시 교육비 명목으로 배상액 200만원을 지급한다.", "이 계약에 정함이 없는 사항은 근로기준법령에 의함"]),
     "expected": {"wage_status": "conflict", "finding_types": ["penalty", "wage_deduction"], "issue_types": ["conflicting_terms", "work_hours"]},
     "translations": {"zh": {"title": "物流中心劳动合同", "tag": "不利条款", "description": "请确认损坏扣款、中途离职赔偿、不一致的月薪和较长工时。"}, "es": {"title": "Contrato de centro logístico", "tag": "Cláusulas desfavorables", "description": "Revise deducciones por daños, indemnización por renuncia, salarios distintos y jornada larga."}}},
    {"id": "employment-fair", "title": "불리한 조항이 없는 근로계약서", "contract_type": "employment", "tag": "비교용", "description": "같은 양식에 불리한 특약이 없는 계약입니다. 위 계약과 비교해보세요.",
     "context": {"document_complete": True, "event_date": "2026-11-16", "workplace_size": "5plus"}, "pages": employment(
        "주식회사 한결소프트", "서울특별시 금천구 가산디지털2로 101, 9층", "서유진", "02-****-4196", "윤하늘", "서울특별시 관악구 신림로 59, 403호", "010-****-2268", "2026년 11월 13일",
        "2026년 11월 16일부터 2027년 11월 15일까지", "본사 사무실 (서울특별시 금천구 가산디지털2로 101, 9층)", "고객 지원 및 사무 행정",
        "09시 00분부터 18시 00분까지 (휴게시간 : 12시 00분 ~ 13시 00분)", "매주 5일(월요일~금요일) 근무, 주휴일 매주 일요일", 40, "2,900,000원",
        ["연장·야간·휴일근로 수당은 근로기준법에 따라 별도 산정하여 지급한다.", "근로조건을 변경할 때에는 양 당사자가 서면으로 합의한다.", "이 계약에 정함이 없는 사항은 근로기준법령에 의함"]),
     "expected": {"wage": 2900000, "wage_status": "found", "finding_types": []},
     "translations": {"zh": {"title": "没有不利条款的劳动合同", "tag": "对照用", "description": "相同格式但没有不利特约，可与上面的合同比较。"}, "es": {"title": "Contrato sin cláusulas desfavorables", "tag": "Comparación", "description": "Mismo formato sin condiciones desfavorables. Compárelo con los anteriores."}}},
    {"id": "lease-villa", "title": "다세대주택 임대차계약서", "contract_type": "lease", "tag": "부동산", "description": "보증금 반환 조건, 수리비 전가, 전입신고 제한이 들어 있는 계약입니다.",
     "context": {"document_complete": True, "event_date": "2026-11-20"}, "pages": LEASE,
     "expected": {"deposit": 50000000, "finding_types": ["deposit_return", "repair_burden", "registration_waiver", "deposit_deduction"]},
     "translations": {"zh": {"title": "多户住宅租赁合同", "tag": "房地产", "description": "包含押金返还条件、转嫁维修费和限制迁入登记。"}, "es": {"title": "Contrato de alquiler de vivienda", "tag": "Inmueble", "description": "Incluye condiciones de devolución del depósito, reparaciones y límite al registro."}}},
]


def write_pdf(path, case):
    canvas = Canvas(str(path), pagesize=A4)
    canvas.setTitle(case["title"])
    width, height = A4
    y = height - 70
    for kind, text in case["pages"]:
        if kind == "title":
            canvas.setFont("Contract", 19)
            canvas.drawCentredString(width / 2, y, text)
            y -= 36
        elif kind == "gap":
            y -= 9
        elif kind == "center":
            canvas.setFont("Contract", 11)
            canvas.drawCentredString(width / 2, y, text)
            y -= 19
        else:
            canvas.setFont("Contract", 11 if kind == "heading" else 10.3)
            if canvas.stringWidth(text.strip(), canvas._fontname, canvas._fontsize) + 110 > width:
                raise ValueError(f"Line would wrap and split a clause: {text}")
            indent = len(text) - len(text.lstrip())
            canvas.drawString(55 + indent * 3.2, y, text.strip())
            y -= 19 if kind != "heading" else 20
        if y < 45:
            raise ValueError(f"Contract exceeds one page: {case['id']}")
    canvas.save()


def main():
    font = Path(os.environ.get("GWOLLION_FORM_FONT", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))
    if not font.exists():
        raise SystemExit("한국어 TTF 글꼴 경로를 GWOLLION_FORM_FONT에 설정해주세요.")
    pdfmetrics.registerFont(TTFont("Contract", str(font)))
    samples = ROOT / "samples"
    (samples / "pdf").mkdir(parents=True, exist_ok=True)
    (samples / "images").mkdir(exist_ok=True)
    for case in CASES:
        lines = [text.strip() if kind in {"title", "center"} else text for kind, text in case["pages"] if kind != "gap"]
        (samples / f"{case['id']}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        pdf = samples / "pdf" / f"{case['id']}.pdf"
        write_pdf(pdf, case)
        with fitz.open(pdf) as document:
            document[0].get_pixmap(matrix=fitz.Matrix(2.5, 2.5), alpha=False).save(samples / "images" / f"{case['id']}.png")
    manifest = [{k: v for k, v in case.items() if k != "pages"} for case in CASES]
    (samples / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Created {len(CASES)} sample contracts as TXT, PDF and PNG.")


if __name__ == "__main__":
    main()
