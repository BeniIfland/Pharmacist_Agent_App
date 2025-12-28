from pydantic import BaseModel
from typing import Literal

IntentName = Literal["med_info", "small_talk","stock_check"] #small_talk is the fallback option

class IntentResult(BaseModel):
    intent: IntentName
    confidence: float  # 0..1 #TODO: remove if not used
    lang: Literal["he", "en"]
    notes: str = ""  # optional short rationale for debugging #TODO: remove if not used


