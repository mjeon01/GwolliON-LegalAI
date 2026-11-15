"""Worker-burden detection at clause level: (a) review rules alone, (b) clause model + rules."""
from backend.clause_labels import INHERENT_RISK, RISK_TYPES, WORKER_RULES, wording_supports
from backend.review import RULES, rule_matches

RULE_PATTERNS = {r[0]: r[3] for r in RULES if r[1] == "employment" and "worker" in r[2] and r[0] in WORKER_RULES}


def rule_hits(text):
    return [kind for kind, pattern in RULE_PATTERNS.items() if rule_matches(text, pattern, kind)]


def combined(text, model_labels):
    """Rules, plus burdens the model sees in clause types that are burdens by nature, when the wording shows the burden."""
    found = rule_hits(text)
    found += [RISK_TYPES[label] for label in model_labels
              if label in INHERENT_RISK and RISK_TYPES[label] not in found and wording_supports(label, text)]
    return found
