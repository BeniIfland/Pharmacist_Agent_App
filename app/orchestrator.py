from typing import Iterator, Tuple
from app.schemas import ChatRequest, ChatResponse, ChatMessage, FlowState, ToolCallRecord
from app.llm import stream_llm
from app.tools import get_medication_by_name

def handle_turn(req: ChatRequest) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Stateless orchestrator.
    Yields (delta_text, partial_response) based on app logic so the UI can stream.
    """
    # Copy flow-state from request (client-owned)
    history = list(req.history)
    flow = req.flow or FlowState()

    # Add the new user message to history
    history.append(ChatMessage(role="user", content=req.message))

    # Prepare an empty assistant message and stream into it
    assistant = ChatMessage(role="assistant", content="")
    history.append(assistant)

    tool_calls: list[ToolCallRecord] = []  # empty at the moment

    # SUPER THIN "router": try tool first if message is short-ish (likely a name) #TODO: delete
    #TODO: replace with an intent detection/flows 
    maybe_name = req.message.strip()
    tool_result = get_medication_by_name(maybe_name)
    tool_calls.append(ToolCallRecord(name="get_medication_by_name", args={"name": maybe_name}, result=tool_result))

    # The safe OK scenario 
    #TODO: right now no LLM - have to change to llm stream grounded on the retrieved info
    if tool_result["status"] == "OK": 
        med = tool_result["medication"]
        # Compose a safe factual response (no advice)
        assistant.content = (
            f'{med["display_name"]} (active ingredient: {med["active_ingredient"]}).\n'
            f'Prescription required: {"Yes" if med["rx_required"] else "No"}.\n'
            f'Info: {med["label_summary"]}\n\n'
            "I can provide factual information, but I can’t give medical advice. "
            "For personal guidance, consult a pharmacist or doctor.")
        
        partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
        # yield once (no need to stream this fixed text yet)
        yield assistant.content, partial
        return

    # The ambigous scenario
    #TODO: consider taking advantage of the GUI to desplay the ambiguity 
    #TODO: cosider if the LLM is needed for this
    #TODO: don't forget to go back to beggining of the state after getting the corresponding reponse
    if tool_result["status"] == "AMBIGUOUS":
        options = ", ".join(m["display_name"] for m in tool_result["matches"])
        assistant.content = f"I found multiple matches: {options}. Which one did you mean?"
        partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
        yield assistant.content, partial
        return

    #TODO: update to let the LLM know what happened and generate based on this context
    # NOT_FOUND → fall back to LLM streaming (general chat)
    for delta in stream_llm(req.message):
        assistant.content += delta
        partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
        yield delta, partial

    

       
