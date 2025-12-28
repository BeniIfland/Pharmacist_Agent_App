import re
from typing import Optional
from app.db import BRANCHES
from app.utils import norm

# The following detector is used to detect user language and allow bilinguality
# if user language isn't Hebrew it is asumed to be english
# An extension could be to notify the user that the agent only speaks Hebrew or English if they try to speak another language

def detect_lang(text: str) -> str:
    """
    Heuristically  (based on chars' encoding) determines if user language is hebrew,
    otherwise assumes its english.
    
    :param text: user message
    :type text: str
    :return: he or en i.e., determined language
    :rtype: str
    """
    # simlistic but effective: any Hebrew character => Hebrew
    return "he" if any("\u0590" <= ch <= "\u05FF" for ch in text) else "en"



#used to extract branch name - could be implemented using an LLM like med name but prefered a simple version
def extract_branch_name(text: str) -> Optional[str]:
    """
    Very simple deterministic extractor:
    - If any branch alias/display name appears as a whole word/substring, return that alias/display.
    - Returns the matched string (not branch_id). 
    """
    t = (text or "").strip().lower()
    if not t:
        return None

    
    candidates: list[str] = []
    for b in BRANCHES:
        keys = [b.display_name] + list(b.aliases)
        for k in keys:
            k_norm = norm(k)
            if not k_norm:
                continue
            if k_norm in t:
                candidates.append(k)

    if not candidates:
        return None

    # Prefer longer matches to avoid "ha" matching "haifa"
    candidates.sort(key=lambda s: len(s), reverse=True)
    return candidates[0]

# next parts are relevant for the prescriptions flow


_RX_RE = re.compile(r"\bRX[- ]?\d{5,}\b", re.IGNORECASE)
_USER_RE = re.compile(r"\buser_\d{3}\b", re.IGNORECASE)

def extract_rx_id(text: str) -> Optional[str]:
    """
    Deterministic extractor for prescription IDs like RX-10001 / RX 10001.
    Returns normalized uppercase with dash: RX-10001
    """
    t = (text or "").strip()
    if not t:
        return None
    m = _RX_RE.search(t)
    if not m:
        return None
    raw = m.group(0).upper().replace(" ", "-")
    # normalize RX10001 -> RX-10001 (if no dash)
    if raw.startswith("RX") and "-" not in raw:
        raw = "RX-" + raw[2:]
    print(f"extract_rx_id result: {raw}") #TODO: delete debug
    return raw

def extract_user_id(text: str) -> Optional[str]:
    """
    Deterministic extractor for user IDs like user_009.
    """
    t = (text or "").strip()
    if not t:
        return None
    m = _USER_RE.search(t)
    if not m:
        return None
    return m.group(0).lower()
