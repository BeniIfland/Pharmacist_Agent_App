from pydantic import BaseModel
from typing import Literal

IntentName = Literal["med_info", "small_talk","stock_check","rx_verify"] #small_talk is the fallback option

class IntentResult(BaseModel):
    intent: IntentName
    confidence: float  # 0..1  - only for debugging
    lang: Literal["he", "en"]
    notes: str = ""  # optional short rationale for debugging 


