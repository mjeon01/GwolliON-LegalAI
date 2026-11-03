"""Render an edited draft as a downloadable PDF, using the same line rules as the screen preview."""
from io import BytesIO
import re
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from backend.knowledge import ROOT

INK = HexColor("#1f2733")


def register_fonts():
    if "DocRegular" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("DocRegular", str(ROOT / "resources/fonts/Pretendard-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("DocBold", str(ROOT / "resources/fonts/Pretendard-Bold.ttf")))


def styles():
    body = ParagraphStyle("body", fontName="DocRegular", fontSize=10.5, leading=17.5, textColor=INK, wordWrap="CJK", spaceAfter=3)
    return {
        "title": ParagraphStyle("title", parent=body, fontName="DocBold", fontSize=18, leading=26, alignment=TA_CENTER, spaceAfter=20),
        "heading": ParagraphStyle("heading", parent=body, fontName="DocBold", fontSize=11.5, leading=19, spaceBefore=10, spaceAfter=5),
        "clause": ParagraphStyle("clause", parent=body, fontName="DocBold", spaceBefore=6),
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=11, firstLineIndent=-11),
        "indent": ParagraphStyle("indent", parent=body, leftIndent=11),
        "body": body,
    }


def line_kind(line):
    if re.match(r"\d+\.\s", line):
        return "heading"
    if re.match(r"조항 \d+\.\s", line):
        return "clause"
    if line.startswith("- "):
        return "bullet"
    return "indent" if line.startswith(" ") else "body"


def render_pdf(text, title):
    register_fonts()
    style = styles()
    story, titled = [], False
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            story.append(Spacer(1, 7))
        elif not titled:
            story.append(Paragraph(escape(line.strip()), style["title"]))
            titled = True
        else:
            kind = line_kind(line)
            shown = "•&nbsp;&nbsp;" + escape(line[2:]) if kind == "bullet" else escape(line.strip())
            story.append(Paragraph(shown, style[kind]))

    def page_number(canvas, doc):
        canvas.setFont("DocRegular", 8.5)
        canvas.setFillColor(HexColor("#6b7686"))
        canvas.drawCentredString(A4[0] / 2, 28, str(doc.page))

    output = BytesIO()
    SimpleDocTemplate(output, pagesize=A4, leftMargin=62, rightMargin=62, topMargin=64, bottomMargin=58, title=title).build(
        story, onFirstPage=page_number, onLaterPages=page_number)
    return output.getvalue()
