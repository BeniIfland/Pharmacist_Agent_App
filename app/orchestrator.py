from typing import Iterator, Tuple
from app.schemas import ChatRequest, ChatResponse, ChatMessage, FlowState, ToolCallRecord
from app.llm import stream_llm, extract_med_name
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

    # prepare assistant message, will be filled with content with the flow progression
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
            # if we are in the med_info flow we need to extract the name out of the message
            user_text = req.message.strip()   
            #if user message is very short it is probably already the name and we
            #will proceed to lookup rather than wasting time on an LLM call
            
            if 1 <= len(user_text.split()) < 2: #one word only is accepted, to avoid the "What's Advil" problem
                flow.slots["med_name"] = user_text
                flow.step = "lookup"
            else:
                flow.step = "extract_med_name"


        if flow.step == "extract_med_name":
            user_text = req.message.strip()

            extracted = extract_med_name(user_text)  # LLM-call extractor
            tool_calls.append(
                    ToolCallRecord(name="extract_med_name",args={"text": user_text},result={"extracted": extracted},))

            if not extracted: #if no med in the message (but we are in the flow #TODO: think if we ended up in the flow mistakenly
                assistant.content = "Which medication name should I look up? (Brand or generic name is fine.)" #a predefined clarification message is ok here - an llm call would be a waste of time
                # remain in same step to collect a clean name next
                flow.step = "collect_med_name"
                partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
                yield assistant.content, partial
                return
            #sucess and continue
            flow.slots["med_name"] = extracted.strip()
            flow.step = "lookup"



        if flow.step == "lookup":
            med_name = flow.slots.get("med_name", "").strip()

            tool_result = get_medication_by_name(med_name)
            tool_calls.append(
                ToolCallRecord(name="get_medication_by_name", args={"name": med_name}, result=tool_result,))

            if tool_result["status"] == "OK":
                med = tool_result["medication"]
                assistant.content = (
                    f'{med["display_name"]} (active ingredient: {med["active_ingredient"]}).\n'
                    f'Prescription required: {"Yes" if med["rx_required"] else "No"}.\n'
                    f'Info: {med["label_summary"]}\n\n'
                    "I can provide factual information, but I can’t give medical advice. "
                    "For personal guidance, consult a pharmacist or doctor.")
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
