"""Korean–Spanish labor contract guide (resources/labor-guide-ko-es.txt) for translations and explanations.

The guide fixes the Spanish name of each contract term, explains it for Spanish speakers, compares Korean rules
with Spain and Latin America, and lists what a foreign worker should check. It is reference material written
for November 2026, not law: legal claims still go through the law tools.
"""
from functools import lru_cache
import re

from backend.knowledge import ROOT

PATH = ROOT / "resources/labor-guide-ko-es.txt"
# Checklist items worth showing for each finding type of backend/foreign_form.py and backend/review.py.
CHECKLIST_FOR = {
    "foreign_signature": [1], "foreign_workplace": [2], "foreign_period": [2], "foreign_minimum_wage": [3],
    "foreign_probation_wage": [4, 3], "foreign_hours": [5], "foreign_break": [5], "foreign_overtime": [5, 8],
    "foreign_holiday": [8], "foreign_lodging": [11], "foreign_custody": [12, 13], "foreign_payday": [11],
    "included_allowance": [6], "unpaid_trial": [4], "wage_deduction": [11], "leave_waiver": [8],
}


# A parenthesis in a heading is either a synonym ('노동절 (근로자의 날)') or a qualifier ('공휴일 (유급)').
# A qualifier must not travel with the bare term: '공휴일을 무급으로' is not 'festivos remunerados'.
QUALIFIERS = {"유급": r"\s+remunerad[oa]s?\b"}


def _variants(heading):
    """'사용자 · 사업주' -> ['사용자', '사업주']; '노동절 (근로자의 날)' -> ['노동절', '근로자의 날']; '공휴일 (유급)' -> ['공휴일']."""
    out = []
    for part in heading.split("·"):
        base = re.sub(r"\s*\(.*?\)", "", part).strip()
        out += [base] + [p.strip() for p in re.findall(r"\((.*?)\)", part) if p.strip() not in QUALIFIERS]
    return [v for v in out if v]


def _plain_spanish(heading, spanish):
    for qualifier, pattern in QUALIFIERS.items():
        if f"({qualifier})" in heading.replace(" ", ""):
            spanish = re.sub(pattern, "", spanish)
    return spanish


@lru_cache(maxsize=1)
def load():
    text = PATH.read_text(encoding="utf-8") if PATH.is_file() else ""
    sections = re.split(r"^=+\n(\d)\.\s.*\n=+$", text, flags=re.M)
    parts = {sections[i]: sections[i + 1] for i in range(1, len(sections) - 1, 2)}
    glossary = []
    for number, heading, body in re.findall(r"^\[(\d+)\]\s*(.+)\n((?:\s+·.*\n?)+)", parts.get("1", ""), flags=re.M):
        fields = dict(re.findall(r"·\s*([^:]+?):\s*(.+)", body))
        glossary.append({"id": int(number), "ko": heading.strip(), "variants": _variants(heading),
                         "es": _plain_spanish(heading, fields.get("Español", "").strip()), "explanation_es": fields.get("Explicación en español", "").strip(),
                         "summary_ko": fields.get("한국어 요지", "").strip()})
    comparisons = []
    for topic, body in re.findall(r"^▶\s*(.+)\n((?:\s+·.*\n?)+)", parts.get("2", ""), flags=re.M):
        fields = dict(re.findall(r"·\s*([^:]+?):\s*(.+)", body))
        comparisons.append({"topic": topic.strip(), "korea": fields.get("한국", ""), "spain": fields.get("스페인", ""),
                            "latin_america": fields.get("중남미 주요국", ""), "note_ko": fields.get("외국인이 주의할 점", "")})
    checklist, help_lines = [], []
    third = parts.get("3", "")
    body, _, rest = third.partition("■ 4.")
    for number, title, item in re.findall(r"^\[(\d+)\]\s*(.+)\n((?:\s+·.*\n?)+)", body, flags=re.M):
        fields = dict(re.findall(r"·\s*([^:]+?):\s*(.+)", item))
        checklist.append({"id": int(number), "title_ko": title.strip(), "ko": fields.get("한국어 설명", ""),
                          "es": fields.get("Explicación para el trabajador", "")})
    for name, item in re.findall(r"^▶\s*(.+)\n((?:\s+·.*\n?)+)", rest.split("■ 출처")[0], flags=re.M):
        fields = dict(re.findall(r"·\s*([^:]+?):\s*(.+)", item))
        help_lines.append({"name_ko": name.strip(), "name_es": fields.get("Organismo", ""), "contact": fields.get("연락처", ""),
                           "purpose": fields.get("용도 · Para qué", "")})
    return {"glossary": glossary, "comparisons": comparisons, "checklist": checklist, "help": help_lines}


def terms_in(texts):
    """Glossary entries whose Korean term appears in the texts, longest terms first (최저임금 before 임금)."""
    joined = "\n".join(texts)
    found, covered = [], []
    entries = sorted(((v, e) for e in load()["glossary"] for v in e["variants"] if v), key=lambda pair: -len(pair[0]))
    for variant, entry in entries:
        for match in re.finditer(re.escape(variant), joined):
            span = range(match.start(), match.end())
            if any(match.start() in s and match.end() - 1 in s for s in covered):
                continue
            covered.append(span)
            if entry not in found:
                found.append(entry)
    return sorted(found, key=lambda e: e["id"])


# Names of laws, agencies and programs keep their capitals; other terms are common nouns inside a sentence.
PROPER = {3, 21, 37, 38, 39, 40, 41, 48, 49, 50}
GLOSSARY_RULE = ("Translate the WHOLE text into natural Spanish; leave no Korean words. The following reviewed glossary only fixes "
                 "the Spanish wording of these Korean terms (adapt articles, number and capitalization to the sentence): ")


def glossary_prompt(texts):
    """Prompt line asking for the glossary's wording; '' when no term appears."""
    terms = glossary_line(texts)
    return GLOSSARY_RULE + terms + ".\n" if terms else ""


def glossary_line(texts):
    """'근로계약서=Contrato de trabajo; ...' for the terms in the texts; '' when none."""
    pairs = []
    for entry in terms_in(texts):
        options = [o.strip() for o in entry["es"].split(" / ")]
        # '고용노동부 · 지방노동청' = 'Ministerio … / Oficina regional …' pair up; '근로자' = 'Trabajador / Empleado' are alternatives.
        paired = len(options) == len(entry["variants"]) > 1
        for i, variant in enumerate(entry["variants"]):
            spanish = options[i] if paired else options[0]
            pairs.append(f"{variant}={spanish if entry['id'] in PROPER else spanish[:1].lower() + spanish[1:]}")
    return "; ".join(dict.fromkeys(pairs))


def explanation_context(texts, issue_types=()):
    """Reference for explaining a case to a Spanish speaker: matching terms, checklist items and country comparisons."""
    guide = load()
    wanted = {n for kind in issue_types for n in CHECKLIST_FOR.get(kind, [])}
    joined = "\n".join(texts)
    checklist = [c for c in guide["checklist"] if c["id"] in wanted or any(w in joined for w in re.findall(r"[가-힣]{2,}", c["title_ko"]) if w not in {"확인", "여부", "필수", "보관", "금지"})]
    return {
        "note": "Reviewed Korean–Spanish reference (2026-11), informational, not law. Use its Spanish terms; quote its plain explanations; "
                "use the comparisons to correct expectations from Spain or Latin America (e.g. no legal aguinaldo in Korea). Verify legal claims with the law tools.",
        "glossary": [{k: e[k] for k in ("ko", "es", "explanation_es")} for e in terms_in(texts)],
        "checklist": checklist,
        "comparisons": guide["comparisons"],
        "help": guide["help"],
    }
