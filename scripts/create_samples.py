#!/usr/bin/env python3
"""Create six fully synthetic contract fixtures and matching, extractable PDFs."""
import json
import re
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {"id": "employment-basic", "title": "기본 항목이 있는 근로계약", "contract_type": "employment", "tag": "기본 항목", "description": "월급·시간·휴일을 원문과 대조해보세요.",
     "context": {"document_complete": True, "event_date": "2026-10-10"},
     "lines": ["근로계약서 / 가상 시연 문서", "사용자: 가상회사 A / 근로자: 가상근로자 A", "계약기간: 2026-10-10 ~ 2027-10-09", "근무장소: 가상회사 A 사무실", "업무: 사무 보조", "월급: 2,500,000원", "지급일: 매월 25일, 근로자 명의 계좌로 지급", "근로시간: 09:00 ~ 18:00, 월요일부터 금요일까지", "주당 40시간 근무", "휴게시간: 1시간, 근로시간 도중 자유롭게 이용", "휴일: 매주 일요일 유급휴일, 토요일 휴무", "변경된 근로조건은 별도 서면으로 확인한다."],
     "expected": {"wage": 2500000, "wage_status": "found", "issue_types": ["review_scope"]}},
    {"id": "employment-missing", "title": "종료일·지급방법·휴게·연차가 빈 계약", "contract_type": "employment", "tag": "정보 누락", "description": "작성되지 않은 항목과 확인할 내용을 살펴보세요.", "context": {},
     "lines": ["아르바이트 근로계약서 / 가상 시연 문서", "사용자: 가상매장 B / 근로자: 가상근로자 B", "계약기간: 2026-10-10 ~ 2027-01-09", "근무장소: 가상매장 B", "업무: 매장 보조", "시급: 12,000원", "근로시간: 10:00 ~ 16:00", "주당 30시간 근무", "기타 조건은 추후 협의한다."],
     "expected": {"wage": 12000, "wage_status": "found", "issue_types": ["missing_terms", "break_time"]}},
    {"id": "employment-conflict", "title": "월급이 서로 다른 계약", "contract_type": "employment", "tag": "조항 충돌", "description": "본문과 특약의 금액을 함께 확인해보세요.", "context": {"document_complete": True, "event_date": "2026-10-10"},
     "lines": ["근로계약서 / 가상 시연 문서", "사용자: 가상회사 C / 근로자: 가상근로자 C", "계약기간: 2026-10-10 ~ 2027-10-09", "근무장소: 가상회사 C 사무실", "본문 월급: 250만원", "특약 월급: 230만원", "지급일: 매월 25일", "근로시간: 09:00 ~ 18:00", "주당 40시간 근무", "휴게시간: 1시간", "휴일: 매주 일요일 유급휴일"],
     "expected": {"wage_status": "conflict", "issue_types": ["conflicting_terms"]}},
    {"id": "employment-attention", "title": "수당·퇴사 배상 특약이 있는 계약", "contract_type": "employment", "tag": "주의 특약", "description": "법령 근거와 사업장 규모에 따른 질문을 확인하세요.", "context": {"document_complete": True},
     "lines": ["근로계약서 / 가상 시연 문서", "사용자: 가상회사 D / 근로자: 가상근로자 D", "계약기간: 2026-10-10 ~ 2027-10-09", "근무장소: 가상회사 D 작업장", "월급: 250만원", "지급일: 매월 25일", "근로시간: 09:00 ~ 19:00", "주당 45시간 근무", "휴게시간: 1시간", "휴일: 매주 일요일", "특약: 연장·야간·휴일근로 수당은 월급에 모두 포함한다.", "특약: 계약기간 중 퇴사하면 위약금 300만원을 지급한다."],
     "expected": {"wage": 2500000, "wage_status": "found", "issue_types": ["penalty", "included_allowance", "work_hours"]}},
    {"id": "lease-basic", "title": "처음 확인하는 주택 임대차계약", "contract_type": "lease", "tag": "주거 확인", "description": "보증금·월세와 입주·전입신고를 확인하세요.", "context": {"document_complete": True},
     "lines": ["주택 임대차계약서 / 가상 시연 문서", "임대인: 가상임대인 E / 임차인: 가상임차인 E", "목적물: 가상시 가상구 가상로 10, 101호", "보증금: 1,000만원", "월세: 50만원", "임대차기간: 2026-10-10 ~ 2028-10-09", "월세는 매월 10일에 지급한다.", "보증금 반환 조건: 계약 종료와 주택 인도 시 반환한다.", "수선 및 관리비는 별도 서면 합의로 정한다."],
     "expected": {"deposit": 10000000, "issue_types": ["lease_registration"]}},
    {"id": "lease-return", "title": "보증금 반환을 준비하는 계약", "contract_type": "lease", "tag": "반환 상담", "description": "미반환 상황을 입력하고 상담 요약을 만들어보세요.", "context": {"document_complete": True},
     "lines": ["주택 임대차계약서 / 가상 시연 문서", "임대인: 가상임대인 F / 임차인: 가상임차인 F", "목적물: 가상시 가상구 가상로 20, 202호", "보증금: 1억원", "월세: 0원", "임대차기간: 2026-10-10 ~ 2028-10-09", "특약: 새 임차인이 구해지면 보증금을 반환한다.", "특약: 반환 지연에 관한 사항은 별도 협의한다."],
     "expected": {"deposit": 100000000, "issue_types": ["lease_registration", "deposit_return"]}},
]


def employment_lines(case):
    """Filled synthetic versions of the supplied MOEL numbered form."""
    code = {"employment-basic": "A", "employment-missing": "B", "employment-conflict": "C", "employment-attention": "D"}[case["id"]]
    missing = case["id"] == "employment-missing"
    attention = case["id"] == "employment-attention"
    company, worker = f"가상회사 {code}", f"가상근로자 {code}"
    end = "    년    월    일" if missing else "2027년 10월 09일"
    wage = "12,000원" if missing else "2,500,000원" if code == "A" else "250만원"
    unit = "시간급" if missing else "월급"
    rest = "   시   분 ~   시   분" if missing else "12시 00분 ~ 13시 00분"
    lines = [
        "표준근로계약서(기간의 정함이 있는 경우)",
        f'{company}(이하 “사업주”라 함)과 {worker}(이하 “근로자”라 함)은',
        "다음과 같이 근로계약을 체결한다.",
        f"1. 근로계약기간 : 2026년 10월 10일부터 {end}까지",
        f"2. 근 무 장 소 : {company} 사무실 (가상시 가상구 가상로 10)",
        "3. 업무의 내용 : 사무 보조",
        f"4. 소정근로시간 : 09시 00분부터 {'19' if attention else '18'}시 00분까지 (휴게시간 : {rest})",
        "5. 근무일/휴일 : 매주 5일(월요일~금요일) 근무, 주휴일 매주 일요일",
        f"   주당 {'45' if attention else '40'}시간 근무",
        "6. 임  금",
        f"   - {unit} : {wage}",
        "   - 상여금 : 있음 (    )                  원, 없음 ( O )",
        "   - 기타급여(제수당 등) : 있음 (    ), 없음 ( O )",
        "     · __________________ 원, __________________ 원",
        "     · __________________ 원, __________________ 원",
        "   - 임금지급일 : " + ("매월      일" if missing else "매월 25일(휴일의 경우는 전일 지급)"),
        "   - 지급방법 : 근로자에게 직접지급(    ), 근로자 명의 예금통장에 입금(" + ("    " if missing else " O ") + ")",
        "7. 연차유급휴가",
        "   - " + ("__________________________________________________" if missing else "연차유급휴가는 근로기준법에서 정하는 바에 따라 부여함"),
        "8. 사회보험 적용여부(해당란에 체크)",
        "   ☑ 고용보험    ☑ 산재보험    ☑ 국민연금    ☑ 건강보험",
        "9. 근로계약서 교부",
        "   - 사업주는 근로계약을 체결함과 동시에 본 계약서를 사본하여 근로자의",
        "     교부요구와 관계없이 근로자에게 교부함(근로기준법 제17조 이행)",
        "10. 근로계약, 취업규칙 등의 성실한 이행의무",
        "   - 사업주와 근로자는 각자가 근로계약, 취업규칙, 단체협약을 지키고",
        "     성실하게 이행하여야 함",
        "11. 기  타",
        "   - 이 계약에 정함이 없는 사항은 근로기준법령에 의함",
    ]
    if code == "C":
        lines.append("   - 특약 월급 : 230만원")
    if attention:
        lines += ["   - 특약: 연장·야간·휴일근로 수당은 월급에 모두 포함한다.",
                  "   - 특약: 계약기간 중 퇴사하면 위약금 300만원을 지급한다."]
    lines += ["2026년 10월 10일", f"(사업주) 사업체명 : {company}          (전화 : [가상 연락처])",
              "         주    소 : 가상시 가상구 가상로 10",
              f"         대 표 자 : 가상대표 {code}                    (서명)",
              "(근로자) 주    소 : 가상시 가상구 가상로 20",
              "         연 락 처 : [가상 연락처]",
              f"         성    명 : {worker}                    (서명)"]
    return lines


def employment_pdf(path, lines, title):
    canvas = Canvas(str(path), pagesize=A4)
    canvas.setTitle(title)
    canvas.setAuthor("권리ON / 합성 시연 문서")
    width = A4[0] - 100
    canvas.setLineWidth(.6)
    canvas.rect(50, 769, width, 30)
    canvas.setFont("Form", 16)
    canvas.drawCentredString(A4[0] / 2, 779, lines[0])
    body = ParagraphStyle("form", fontName="Form", fontSize=10.4, leading=14.3, wordWrap="CJK")
    y = 751
    for line in lines[1:]:
        if re.match(r"\d+\.", line):
            y -= 4
        if line == "2026년 10월 10일":
            y -= 9
            canvas.setFont("Form", 11)
            canvas.drawCentredString(A4[0] / 2, y - 10, line)
            y -= 25
            continue
        indent = 12 if line.startswith(" ") else 0
        content = escape(line.strip()).replace("☑", '<font name="Korean">☑</font>')
        content = re.sub(r" {2,}", lambda match: "&nbsp;" * len(match[0]), content)
        paragraph = Paragraph(content, body)
        _, height = paragraph.wrap(width - indent, 1000)
        y -= height
        if y < 57:
            raise ValueError(f"Employment form exceeds one page: {path}")
        paragraph.drawOn(canvas, 50 + indent, y)
    canvas.setFont("Korean", 7.5)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(50, 32, "고용노동부 제공 서식 참고 / 기능 테스트용 가상 문서 / 실제 계약서가 아닙니다.")
    canvas.drawRightString(A4[0] - 50, 32, "1 / 1")
    canvas.save()


def main():
    font = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    import os
    font = Path(os.environ.get("GWOLLION_PDF_FONT", font))
    if not font.exists():
        raise SystemExit("한국어 TTF 글꼴 경로를 GWOLLION_PDF_FONT에 설정해주세요.")
    pdfmetrics.registerFont(TTFont("Korean", str(font)))
    serif = Path(os.environ.get("GWOLLION_FORM_FONT", "/System/Library/Fonts/Supplemental/AppleMyungjo.ttf"))
    pdfmetrics.registerFont(TTFont("Form", str(serif if serif.exists() else font)))
    samples = ROOT / "samples"
    output = ROOT / "output/pdf"
    samples.mkdir(exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    body = ParagraphStyle("body", fontName="Korean", fontSize=11, leading=19, textColor=colors.HexColor("#25334a"), wordWrap="CJK", spaceAfter=9)
    heading = ParagraphStyle("heading", parent=body, fontSize=20, leading=29, spaceAfter=22)
    note = ParagraphStyle("note", parent=body, fontSize=9, leading=15, textColor=colors.HexColor("#546174"))
    for case in CASES:
        lines = employment_lines(case) if case["contract_type"] == "employment" else case["lines"]
        text = "\n".join(lines) + "\n\n이 문서는 기능 테스트를 위해 만든 합성 샘플이며 실제 계약서가 아닙니다.\n"
        (samples / f"{case['id']}.txt").write_text(text, encoding="utf-8")
        manifest.append({k: v for k, v in case.items() if k != "lines"})
        if case["contract_type"] == "employment":
            employment_pdf(output / f"{case['id']}.pdf", lines, case["title"])
            continue
        doc = SimpleDocTemplate(str(output / f"{case['id']}.pdf"), pagesize=A4, rightMargin=48, leftMargin=48, topMargin=45, bottomMargin=50, title=case["title"], author="권리ON MVP")
        story = [Paragraph("권리ON  /  SAMPLE DOCUMENT", note), Spacer(1, 12), Paragraph(escape(lines[0].split(" / ")[0]), heading),
                 HRFlowable(width="100%", thickness=1, color=colors.HexColor("#c8d3df")), Spacer(1, 18)]
        story += [Paragraph(escape(line), body) for line in lines]
        story += [Spacer(1, 20), Paragraph("이 문서는 기능 테스트를 위해 만든 합성 샘플이며 실제 계약서가 아닙니다.", note)]

        def footer(canvas, doc):
            canvas.setFont("Korean", 9)
            canvas.setFillColor(colors.HexColor("#546174"))
            canvas.drawString(48, 30, "권리ON 1차 MVP · 합성 데이터")
            canvas.drawRightString(A4[0] - 48, 30, str(doc.page))

        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    (samples / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Created {len(manifest)} synthetic TXT/PDF sample pairs.")


if __name__ == "__main__":
    main()
