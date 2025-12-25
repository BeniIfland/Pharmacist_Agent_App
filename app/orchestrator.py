from typing import Iterator, Tuple
from app.schemas import ChatRequest, ChatResponse, ChatMessage, FlowState, ToolCallRecord
from app.llm import stream_llm
from app.intent import detect_intent
from app.flows import start_med_info_flow, is_med_info_flow
from app.tools import get_medication_by_name


def handle_turn(req: ChatRequest) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Stateless orchestrator.
    Yields (delta_text, partial_response) based on app logic so the UI can stream.
    """
    # Copy flow-state from request (client-owned)
    history = list(req.history)
    flow = req.flow or FlowState()
    tool_calls: list[ToolCallRecord] = []

    # add user message to history
    history.append(ChatMessage(role="user", content=req.message))

    # prepare assistant message (we'll fill it)
    assistant = ChatMessage(role="assistant", content="")
    history.append(assistant)

    # --- 1) Decide / continue flow (stateless) ---
    if is_med_info_flow(flow):
        # continue existing med_info flow
        pass
    else:
        intent = detect_intent(req.message)
        if intent == "med_info":
            flow = start_med_info_flow()

    # --- 2) Run med_info flow if active ---
    if flow.name == "med_info" and not flow.done:
        if flow.step == "collect_med_name":
            # very simple slot extraction: assume the user's message contains the med name
            med_name = req.message.strip()
            flow.slots["med_name"] = med_name
            flow.step = "lookup"

        if flow.step == "lookup":
            med_name = flow.slots.get("med_name", "").strip()

            tool_result = get_medication_by_name(med_name)
            tool_calls.append(
                ToolCallRecord(
                    name="get_medication_by_name",
                    args={"name": med_name},
                    result=tool_result,
                )
            )

            if tool_result["status"] == "OK":
                med = tool_result["medication"]
                assistant.content = (
                    f'{med["display_name"]} (active ingredient: {med["active_ingredient"]}).\n'
                    f'Prescription required: {"Yes" if med["rx_required"] else "No"}.\n'
                    f'Info: {med["label_summary"]}\n\n'
                    "I can provide factual information, but I can’t give medical advice. "
                    "For personal guidance, consult a pharmacist or doctor."
                )
                flow.done = True
                flow.step = "done"

                partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
                yield assistant.content, partial
                return

            if tool_result["status"] == "AMBIGUOUS":
                options = ", ".join(m["display_name"] for m in tool_result["matches"])
                assistant.content = f"I found multiple matches: {options}. Which one did you mean?"
                # stay in same flow; ask again
                flow.step = "collect_med_name"

                partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
                yield assistant.content, partial
                return

            # NOT_FOUND
            assistant.content = (
                "I couldn't find that medication in my database. "
                "Please check the spelling or provide an alternative name (brand/generic)."
            )
            flow.step = "collect_med_name"

            partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            yield assistant.content, partial
            return

    #TODO: update to let the LLM know what happened and generate based on this context
    # NOT_FOUND → fall back to LLM streaming (general chat)
    # --- 3) Fallback: general chat (streamed) ---
    for delta in stream_llm(req.message):
        assistant.content += delta
        partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
        yield delta, partial
