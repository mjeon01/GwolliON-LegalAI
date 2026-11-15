"""Clause-type labels shared by the training scripts, the served model and the agent."""
import re

# AI Hub 계약법률문서 label variants that mean the same clause type.
ALIASES = {"비밀 유지": "비밀 유지 의무"}
# A section tagged only "기타" carries no specific type; it is a negative example, not a class.
IGNORED = {"기타"}
MIN_EXAMPLES = 30

# Clause types that can burden a worker, as backend/review.py rule ids (or agent issue types).
RISK_TYPES = {
    "손해배상의 예정": "penalty",
    "경업 및 겸직금지의무": "noncompete",
    "근로 환경 변경": "unilateral_change",
    "수습 기간": "unpaid_trial",
    "임금 지급 방법": "wage_deduction",
    "휴가": "leave_waiver",
    "근로 시간": "included_allowance",
}
# Types that are a burden by their nature: the model alone may raise them. The others are common,
# usually harmless clauses and become findings only when a review rule also matches the wording.
INHERENT_RISK = {"손해배상의 예정", "경업 및 겸직금지의무", "근로 환경 변경"}
# The model sees the clause type; the wording must still show the burden itself. Without these, the type alone
# flagged article headings, "실손해를 배상한다" (actual damages), in-employment side-job bans and changes
# that need the worker's consent (37.5% false alarms on AI Hub test clauses).
RISK_WORDING = {
    # 손해배상의 예정 means an amount fixed in advance, not liability for actual loss.
    "손해배상의 예정": re.compile(r"위약금|위약벌|배상액|\d[\d,]*\s*(?:만\s*)?원|\d+\s*개월\s*분|\d+\s*배"),
    # The burden is a restriction after leaving; side-job bans while employed are ordinary.
    "경업 및 겸직금지의무": re.compile(r"퇴직|퇴사|이직|(?:계약|근로관계)\S*\s*(?:종료|해지|만료)\s*(?:이\s*)?후"),
}
# A change that needs the worker's consent is not unilateral ("동의 없이" still is).
NEEDS_CONSENT = re.compile(r"(?:동의|합의|협의)(?!\s*없이)")


def wording_supports(label, text):
    """Whether the sentence itself shows the burden that the inherent-risk clause type suggests."""
    if label == "근로 환경 변경":
        return not NEEDS_CONSENT.search(text)
    pattern = RISK_WORDING.get(label)
    return bool(pattern.search(text)) if pattern else True
WORKER_RULES = ["penalty", "included_allowance", "wage_deduction", "leave_waiver", "noncompete", "unpaid_trial"]
RISK_LABELS = WORKER_RULES + ["unilateral_change"]
# Items 근로기준법 제17조 requires in writing; missing ones are a finding of their own.
REQUIRED = ["임금액", "임금 지급 방법", "근로 시간", "휴일", "휴가"]

PLACEHOLDER = re.compile(r"\(@[^)]*\)")


def normalize_text(text):
    return re.sub(r"\s+", " ", PLACEHOLDER.sub("[값]", str(text))).strip()


def normalize_labels(labels):
    out = []
    for label in labels or []:
        label = ALIASES.get(str(label).strip(), str(label).strip())
        if label and label not in IGNORED and label not in out:
            out.append(label)
    return out


def model_input(text, title="", with_context=True):
    """v1 reads the sentence alone; v2 also reads the article heading it belongs to."""
    return f"{title} || {text}" if with_context and title and title != text else text
