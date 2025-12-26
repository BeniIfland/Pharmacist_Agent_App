import re

# A lightweight heuristic safety gate to detect medical advice requests
# Backs up the LLM decision making

_HE_PATTERNS = [
    r"\bמה כדאי\b", r"\bמומלץ\b", r"\bאיך לטפל\b", r"\bאבחון\b", r"\bמה לקחת\b",
    r"\bכואב לי\b", r"\bמה לעשות\b", r"\bלמה יש לי\b",
]
_EN_PATTERNS = [
    r"\bshould i\b", r"\brecommend\b", r"\bwhat should i take\b", r"\bhurts\b",
    r"\bdiagnos(e|is)\b", r"\btreat(ment)?\b", r"\bwhat do i do\b",
]

def is_medical_advice_request(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in _EN_PATTERNS) or any(re.search(p, text) for p in _HE_PATTERNS)
