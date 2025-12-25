from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional

Role = Literal["user", "assistant"] #defining the only allowed roles

class ChatMessage(BaseModel):
    role: Role
    content: str

class FlowState(BaseModel):
    # "name" identifies which flow is active, if any
    name: Optional[str] = None
    # "step" identifies where we are inside that flow
    step: Optional[str] = None
    # "slots" holds collected parameters (e.g., med_name, branch)
    slots: Dict[str, Any] = Field(default_factory=dict) #fresh dict per slot
    # "done" indicates flow completion
    done: bool = False

class ToolCallRecord(BaseModel):
    name: str
    args: Dict[str, Any]
    result: Any

class ChatRequest(BaseModel):
    message: str #current user info
    history: List[ChatMessage] = Field(default_factory=list) #previous messages
    flow: FlowState = Field(default_factory=FlowState) #current conversational flow
    user_id: Optional[str] = None  # optional - good for logging and advanced features such as personalization

class ChatResponse(BaseModel):
    answer: str #model's response
    history: List[ChatMessage] #updated history
    flow: FlowState #updated flow state after the message handling
    tool_calls: List[ToolCallRecord] = Field(default_factory=list) #recorrding tools used during the hadling
