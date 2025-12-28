import re
from typing import Optional
from app.db import MEDICATIONS, BRANCHES
from app.simple_detectors import extract_rx_id,extract_user_id

# A lightweight heuristic safety gate to detect medical advice requests
# Backs up the LLM decision making

_HE_PATTERNS = [
    r"\bמה כדאי\b", r"\bמומלץ\b", r"\bאיך לטפל\b", r"\bאבחון\b", r"\bמה לקחת\b",
    r"\bכואב לי\b", r"\bמה לעשות\b", r"\bלמה יש לי\b",
]
_EN_PATTERNS = [
    r"\bshould i\b", r"\brecommend\b", r"\bwhat should i take\b", r"\bhurts\b",
    r"\bdiagnos(e|is)\b", r"\btreat(ment)?\b", r"\bwhat do i do\b", r"\boffer\b", r"\bencourage\b"
]

def is_medical_advice_request(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in _EN_PATTERNS) or any(re.search(p, text) for p in _HE_PATTERNS)

#the following parts are in charge of detecting when the user wants to cancel or escape the current flow
_CANCEL_PAT = re.compile(
    r"\b(cancel|stop|exit|quit|never mind|forget it|back)\b|"
    r"(ביטול|לא משנה|עזוב|צא|דיי|חזור)",
    re.IGNORECASE,)

_SMALLTALK_PAT = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|thx|good morning|good evening)\b|"
    r"^\s*(היי|הי|שלום|תודה|תודה רבה|בוקר טוב|ערב טוב)\b",
    re.IGNORECASE,
)

_META_PAT = re.compile(
    r"\b(what can you do|help|how does this work)\b|"
    r"(מה אתה יכול לעשות|עזרה|איך זה עובד)",
    re.IGNORECASE,
)


def is_cancel(text: str) -> bool:
    return bool(_CANCEL_PAT.search(text or ""))

def is_smalltalk_or_meta(text: str) -> bool:
    t = text or ""
    return bool(_SMALLTALK_PAT.search(t) or _META_PAT.search(t))

def _looks_like_short_answer(text: str) -> bool:
    # when awaiting a slot, answers are usually short
    t = (text or "").strip()
    return 0 < len(t) <= 15 and ("\n" not in t) #TODO: can try different lengths

def plausible_med_name(text: str) -> bool:
    """
    returns True if message is a short and contains
    any known med/alias as substring, OR is a single-word token.
    This is used to *prevent* reroute when user likely answered the slot.
    """
    t = (text or "").strip().lower()
    if not _looks_like_short_answer(t):
        return False

    # strong: matches known meds/aliases
    for m in MEDICATIONS:
        keys = [m.display_name] + list(m.aliases)
        if any(k.lower() in t for k in keys):
            return True

    # weaker: single token which can be a response of an unexisting med
    # still keep flow, the tool will return NOT_FOUND if wrong
    if re.fullmatch(r"[a-zA-Z\u0590-\u05FF0-9\-]{2,}", t):
        return True

    return False

def plausible_branch_name(text: str) -> bool:
    """
    returns True if message is a short and contains
    any known branch/alias as substring, OR is a single-word token.
    This is used to *prevent* reroute when user likely answered the slot.
    """
    t = (text or "").strip().lower()
    if not _looks_like_short_answer(t):
        return False

    # strong: matches known meds/aliases
    for b in BRANCHES:
        keys = [b.display_name] + list(b.aliases)
        if any(k.lower() in t for k in keys):
            return True

    # weaker: single token which can be a response of an unexisting branch
    # still keep flow, the tool will return NOT_FOUND if wrong
    if re.fullmatch(r"[a-zA-Z\u0590-\u05FF\-\"׳״\s]{2,}", t):
        return True

    return False


# prescriptions guardrails:

def plausible_rx_id(text: str) -> bool:
    return extract_rx_id(text) is not None

def plausible_user_id(text: str) -> bool:
    return extract_user_id(text) is not None

