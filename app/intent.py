from pydantic import BaseModel
from typing import Literal

IntentName = Literal["med_info", "small_talk"] #small_talk is the fallback option

class IntentResult(BaseModel):
    intent: IntentName
    confidence: float  # 0..1 #TODO: remove if not used
    lang: Literal["he", "en"]
    notes: str = ""  # optional short rationale for debugging #TODO: remove if not used

# from typing import Literal

# Intent = Literal["med_info", "other"]

# def detect_intent(text: str) -> Intent:
#     #TODO Add a small talk intent for "hi" and "שלום"
#     t = text.lower().strip()

#     # lightweight heuristics for now TODO: improve improve later - think of using keywords or let the LLM classify or mix 
#     keywords = [
#         "what is", "tell me about", "info", "information", "about",
#         "what does", "explain", "side effects", "interactions",  # still factual-only
#     ]
#     if any(k in t for k in keywords):
#         return "med_info"

#     # if it's just a single token that looks like a med name, also treat as med_info #TODO:reconsider
#     if 1 <= len(t.split()) <= 3:
#         return "med_info"

#     return "other"
