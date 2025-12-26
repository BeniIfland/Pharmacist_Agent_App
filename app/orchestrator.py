from typing import Iterator, Tuple
from app.schemas import ChatRequest, ChatResponse, ChatMessage, FlowState, ToolCallRecord
from app.llm import stream_llm, extract_med_name
from app.flows import start_med_info_flow, is_med_info_flow
from app.tools import get_medication_by_name
from app.lang import detect_lang
from app.llm import extract_med_name, render_med_info_stream, render_ambiguous_stream, render_not_found_stream, render_ask_med_name_stream
from app.llm import detect_intent_llm, render_small_talk_stream
from app.safety import is_medical_advice_request
from app.llm import render_refusal_stream



#TODO: make the LLM use the info looked up on the medicine and generate a concrete response based on that
def handle_turn(req: ChatRequest) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Stateless orchestrator.
    Yields (delta_text, partial_response) based on app logic so the UI can stream.
    """
    lang = detect_lang(req.message)  # per-turn language detection
    
    # Copy flow-state from request (client-owned)
    history = list(req.history)
    flow = req.flow or FlowState()
    tool_calls: list[ToolCallRecord] = []

    # add user message to history
    history.append(ChatMessage(role="user", content=req.message))

    # Hard safety override: if user asks for advice/diagnosis, do NOT enter med_info flow
    # back up for when it is obvious that there's a medical advise reques -> we do not need the LLM
    if is_medical_advice_request(req.message):
        tool_calls.append(ToolCallRecord(
            name="safety_gate",
            args={"text": req.message},
            result={"action": "refuse_advice"}
        ))
        print("Safety gate activated")#TODO: delete
        assistant.content = ""
        for delta in render_refusal_stream(lang, req.message):
            assistant.content += delta
            partial = ChatResponse(answer=assistant.content, history=history, flow=FlowState(), tool_calls=tool_calls)
            yield delta, partial
        return



    # prepare assistant message, will be filled with content with the flow progression
    assistant = ChatMessage(role="assistant", content="")
    history.append(assistant)

    # --- 1) Decide / continue flow 
    intent_result = None

    if is_med_info_flow(flow):
        # continue existing med_info flow (do NOT re-route mid-flow)
        pass
    else:
        # Route using LLM (stateless)
        intent_result = detect_intent_llm(req.message)
        tool_calls.append(
            ToolCallRecord(
                name="detect_intent",
                args={"text": req.message},
                result=intent_result.model_dump(),))

        if intent_result.intent == "med_info":
            flow = start_med_info_flow()
            flow.step = "extract_med_name"   # flow starts with this step
        else:
            # everything else becomes small_talk fallback
            flow = FlowState(name="small_talk", step="reply", slots={}, done=False)



        # small_talk flow (fallback) 
        #TODO: add chat history for small talk
    if flow.name == "small_talk" and not flow.done:
        # per-turn language: prefer router lang if available, else heuristic
        st_lang = intent_result.lang if intent_result else lang #double check #TODO: think if I prefer to stay with the heuristic

        tool_calls.append(
            ToolCallRecord(name="render_small_talk",args={"lang": st_lang},result={"note": "streamed"},))

        assistant.content = ""
        for delta in render_small_talk_stream(st_lang, req.message):
            assistant.content += delta
            partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            yield delta, partial

        flow.done = True
        flow.step = "done"
        return
    print(f"[DBG] flow={flow.name} step={flow.step} lang={lang} intent={getattr(intent_result,'intent',None)}") #TODO: temp for debugging
    # --- 2) Run med_info flow if active ---
    if flow.name == "med_info" and not flow.done:
    
        if flow.step == "extract_med_name":
            user_text = req.message.strip()

            extracted = extract_med_name(user_text)  # LLM-call extractor
            tool_calls.append(
                    ToolCallRecord(name="extract_med_name",args={"text": user_text},result={"extracted": extracted},))

            if not extracted: #if no med in the message (but we are in the flow #TODO: think if we ended up in the flow mistakenly
                # ask user for medication name in the same language

                assistant.content = ""
                # remain in same step to collect a clean name next
                flow.step = "extract_med_name"

                for delta in render_ask_med_name_stream(lang):  #TODO: this part is repetative mayabe change to a function
                    assistant.content += delta
                    partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
                    yield delta, partial
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

                flow.done = True
                flow.step = "done"
                
                assistant.content = ""
                for delta in render_med_info_stream(lang, med):
                    assistant.content += delta
                    partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
                    yield delta, partial
                return

            if tool_result["status"] == "AMBIGUOUS":
                options = [m["display_name"] for m in tool_result["matches"]]

                # stay in same flow; ask again
                flow.step = "extract_med_name"

                assistant.content = ""
                for delta in render_ambiguous_stream(lang, options):
                    assistant.content += delta
                    partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
                    yield delta, partial

                
                return

            # NOT_FOUND
            assistant.content = ""
            flow.step = "extract_med_name"

            for delta in render_not_found_stream(lang):
                assistant.content += delta
                partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
                yield delta, partial
            return
        

        # Last resort fallback: treat as small talk 
    assistant.content = ""
    for delta in render_small_talk_stream(lang, req.message):
        assistant.content += delta
        partial = ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
        yield delta, partial
    return
