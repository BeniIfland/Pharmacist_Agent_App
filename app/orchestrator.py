from typing import Iterator, Tuple, Optional
from typing import Iterator, Tuple
from app.schemas import ChatRequest, ChatResponse, ChatMessage, FlowState, ToolCallRecord
from app.llm import stream_llm, extract_med_name
from app.flows import start_med_info_flow,start_stock_check_flow
from app.tools import get_medication_by_name, get_stock
from app.simple_detectors import detect_lang,extract_branch_name
from app.llm import extract_med_name, render_med_info_stream, render_ambiguous_stream, render_not_found_stream, render_ask_med_name_stream
from app.llm import detect_intent_llm, render_small_talk_stream
from app.llm import render_ask_branch_stream,render_ask_med_and_branch_stream,render_ambiguous_branch_stream,render_branch_not_found_stream
from app.safety import is_medical_advice_request
from app.llm import render_refusal_stream, render_stock_check_stream
from app.intent import IntentResult
from app.tools import get_branch_by_name


def _yield_stream(*,stream: Iterator[str],assistant: ChatMessage,history: list[ChatMessage],flow: FlowState,tool_calls: list[ToolCallRecord],) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Helper: consumes a delta stream, appends to assistant.content,
    yields (delta, partial_response) each time.
    """
    for delta in stream:
        assistant.content += delta
        partial = ChatResponse(
            answer=assistant.content,
            history=history,
            flow=flow,
            tool_calls=tool_calls,
        )
        yield delta, partial


def _finalize_flow(flow: FlowState) -> None:
    flow.done = True
    flow.step = "done"


def _route_or_continue_flow(
    req: ChatRequest,
    flow: FlowState,
    lang_heuristic: str,
    tool_calls: list[ToolCallRecord],) -> tuple[FlowState, Optional[IntentResult], str]:
    """
    Continue any active flow (stateless but client-owned state).
    Only route when there is no active flow.
    - Returns: (flow, intent_result, selected language)
    """
    intent_result: Optional[IntentResult] = None

    if flow and flow.name and not flow.done:
        tool_calls.append(
            ToolCallRecord(
                name="route_decision",
                args={"reason": "continue_active_flow", "flow": flow.name, "step": flow.step},
                result={"action": "continue"},
            ))
        print(f"[DBG] continuing active flow: {flow.name} step={flow.step}") #TODO: delete debug
        return flow, None, lang_heuristic

    intent_result = detect_intent_llm(req.message)
    tool_calls.append(
        ToolCallRecord(
            name="detect_intent",
            args={"text": req.message},
            result=intent_result.model_dump(),
        ))

    if intent_result.intent == "med_info":
        flow = start_med_info_flow()
        flow.step = "extract_med_name"

    elif intent_result.intent == "stock_check":
        flow = start_stock_check_flow()
    
    else:
        flow = FlowState(name="small_talk", step="reply", slots={}, done=False)

    st_lang = intent_result.lang if intent_result else lang_heuristic
    return flow, intent_result, st_lang

#TODO: add chat history for small talk
def run_small_talk_flow(
    *,
    req: ChatRequest,
    flow: FlowState,
    lang: str,
    assistant: ChatMessage,
    history: list[ChatMessage],
    tool_calls: list[ToolCallRecord],
) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Same behavior as your current small_talk branch:
    - stream response
    - mark flow done
    - return
    """
    tool_calls.append(
        ToolCallRecord(
            name="render_small_talk",
            args={"lang": lang},
            result={"note": "streamed"},
        )
    )

    assistant.content = ""
    yield from _yield_stream(
        stream=render_small_talk_stream(lang, req.message),
        assistant=assistant,
        history=history,
        flow=flow,
        tool_calls=tool_calls,
    )

    _finalize_flow(flow)
    # CRITICAL: send updated flow state to client
    yield from _yield_state_only(assistant=assistant,history=history,flow=flow,tool_calls=tool_calls,)

    # reset so the client stores "no active flow" for next turn
    flow_reset = FlowState()
    yield " ", ChatResponse(
        answer=assistant.content,
        history=history,
        flow=flow_reset,
        tool_calls=tool_calls,
    )
    return


def run_med_info_flow(
    *,
    req: ChatRequest,
    flow: FlowState,
    lang: str,
    assistant: ChatMessage,
    history: list[ChatMessage],
    tool_calls: list[ToolCallRecord],
) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Same functionality as your current med_info section, just structured.
    """
    if flow.step == "extract_med_name":
        user_text = req.message.strip()
        extracted = extract_med_name(user_text)
        tool_calls.append(
            ToolCallRecord(
                name="extract_med_name",
                args={"text": user_text},
                result={"extracted": extracted},))
        
        candidate = (extracted or user_text).strip() #always produce a candidate
        if not candidate: #if no med in the message (but we are in the flow #TODO: think if we ended up in the flow mistakenly
            assistant.content = ""
            # flow.step = "extract_med_name"  # stay here
            yield from _yield_stream(
                stream=render_ask_med_name_stream(lang),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,
            )
            return

        flow.slots["med_name"] = candidate
        flow.step = "lookup"

    if flow.step == "lookup":
        med_name = (flow.slots.get("med_name") or "").strip()
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
            

            assistant.content = ""
            yield from _yield_stream(
                stream=render_med_info_stream(lang, med),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,)
            
            _finalize_flow(flow)

            # CRITICAL: send updated flow state to client
            yield from _yield_state_only(assistant=assistant,history=history,flow=flow,tool_calls=tool_calls,)
             # reset so the client stores "no active flow" for next turn
            flow_reset = FlowState()
            yield " ", ChatResponse(
                answer=assistant.content,
                history=history,
                flow=flow_reset,
                tool_calls=tool_calls,)
        
            return

        if tool_result["status"] == "AMBIGUOUS":
            options = [m["display_name"] for m in tool_result["matches"]]
            flow.step = "extract_med_name"

            assistant.content = ""
            yield from _yield_stream(
                stream=render_ambiguous_stream(lang, options),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,
            )
            return

        # NOT_FOUND
        flow.step = "extract_med_name"
        assistant.content = ""
        yield from _yield_stream(
            stream=render_not_found_stream(lang),
            assistant=assistant,
            history=history,
            flow=flow,
            tool_calls=tool_calls,
        )
        return

    # Last-resort fallback (unchanged behavior)
    assistant.content = ""
    yield from _yield_stream(
        stream=render_small_talk_stream(lang, req.message),
        assistant=assistant,
        history=history,
        flow=flow,
        tool_calls=tool_calls,
    )
    return



def run_stock_check_flow(*, req: ChatRequest, flow: FlowState, lang: str, assistant: ChatMessage, history: list[ChatMessage], tool_calls: list[ToolCallRecord],) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Steps:
      - collect: ensure med_name + branch_name in slots
      - resolve_med: get_medication_by_name
      - resolve_branch: get_branch_by_name
      - stock: get_stock
      - done
    """

    # Flow Step: collect 
    #collecting necessary information frm the reuest
    if flow.step in (None, "", "collect"): #safety for first step
        # 1) med_name
        if not flow.slots.get("med_name"):
            extracted = extract_med_name(req.message.strip())
            tool_calls.append(ToolCallRecord(name="extract_med_name", args={"text": req.message.strip()}, result={"extracted": extracted},))
            candidate = (extracted or req.message.strip()).strip()
            if candidate:
                flow.slots["med_name"] = extracted.strip()

        # 2) branch_name (deterministic)
        if not flow.slots.get("branch_name"):
            br = extract_branch_name(req.message)
            tool_calls.append(ToolCallRecord(name="extract_branch_name", args={"text": req.message}, result={"extracted": br},))
            candidate_br = (br or req.message.strip()).strip()
            if candidate_br:
                flow.slots["branch_name"] = candidate_br

        # Ask for what’s missing (minimal)
        missing_med = not flow.slots.get("med_name")
        missing_branch = not flow.slots.get("branch_name")
        print(f"missing_med:{missing_med} missing_branch:{missing_branch}") #TODO: debug delete
        if missing_med and missing_branch:
            assistant.content = ""
            # You can make a dedicated renderer; for now reuse verbalizer approach or a deterministic string streamer
            for delta in render_ask_med_and_branch_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if missing_med:
            assistant.content = ""
            for delta in render_ask_med_name_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if missing_branch:
            assistant.content = ""
            for delta in render_ask_branch_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        flow.step = "resolve_med"

    #  Step: resolve_med 
    if flow.step == "resolve_med":
        med_name = flow.slots["med_name"]
        med_res = get_medication_by_name(med_name)
        tool_calls.append(ToolCallRecord(name="get_medication_by_name",args={"name": med_name},result=med_res,))

        if med_res["status"] == "AMBIGUOUS":
            options = [m["display_name"] for m in med_res["matches"]]
            flow.step = "collect"
            flow.slots.pop("med_name", None)  # force user to clarify
            assistant.content = ""
            for delta in render_ambiguous_stream(lang, options):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if med_res["status"] != "OK":
            #NOT_FOUND
            flow.step = "collect"
            flow.slots.pop("med_name", None)
            flow.slots.pop("med", None)
            assistant.content = ""
            for delta in render_not_found_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        flow.slots["med"] = med_res["medication"]  # cache resolved med dict
        flow.step = "resolve_branch"

    # Step: resolve_branch 
    if flow.step == "resolve_branch":
        branch_name = flow.slots["branch_name"]
        br_res = get_branch_by_name(branch_name)
        tool_calls.append(ToolCallRecord(name="get_branch_by_name", args={"name": branch_name}, result=br_res,))

        if br_res["status"] == "AMBIGUOUS":
            options = [b["display_name"] for b in br_res["matches"]]
            flow.step = "collect"
            flow.slots.pop("branch_name", None)
            assistant.content = ""
            for delta in render_ambiguous_branch_stream(lang, options):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if br_res["status"] != "OK":
            flow.step = "collect"
            flow.slots.pop("branch_name", None)
            flow.slots.pop("branch", None)
            assistant.content = ""
            for delta in render_branch_not_found_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        flow.slots["branch"] = br_res["branch"] #save correct value after it was resolved (status == OK)
        flow.step = "stock"

    # ---- Step: stock ----
    if flow.step == "stock":
        med = flow.slots["med"] 
        branch = flow.slots["branch"]
        stock_res = get_stock(branch["branch_id"], med["med_id"])
        tool_calls.append(ToolCallRecord(name="get_stock",args={"branch_id": branch["branch_id"], "med_id": med["med_id"]},result=stock_res,))

        # Always OK in the simple tool; allows expension if time allows
        stock_status = stock_res.get("stock_status", "UNKNOWN")

        assistant.content = ""
        for delta in render_stock_check_stream(lang, med, branch, stock_status):
            assistant.content += delta
            yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)

        _finalize_flow(flow)
        # CRITICAL: send updated flow state to client
        yield from _yield_state_only(assistant=assistant,history=history,flow=flow,tool_calls=tool_calls,)
         # reset so the client stores "no active flow" for next turn
        flow_reset = FlowState()
        yield " ", ChatResponse(
            answer=assistant.content,
            history=history,
            flow=flow_reset,
            tool_calls=tool_calls,
        )   

        return



def handle_turn(req: ChatRequest) -> Iterator[Tuple[str, ChatResponse]]:
    """ Stateless orchestrator. Yields (delta_text, partial_response) for streaming UI. """

    lang = detect_lang(req.message)

    history = list(req.history)
    flow = req.flow or FlowState()
    tool_calls: list[ToolCallRecord] = []

    # add user message
    history.append(ChatMessage(role="user", content=req.message))

    # assistant message placeholder
    assistant = ChatMessage(role="assistant", content="")
    history.append(assistant)

    # --- Safety override (unchanged functionality) ---
    if is_medical_advice_request(req.message):
        tool_calls.append(ToolCallRecord(name="safety_gate", args={"text": req.message}, result={"action": "refuse_advice"},))
        print("Safety gate activated") #TODO: delete

        assistant.content = ""
        yield from _yield_stream(
            stream=render_refusal_stream(lang, req.message),
            assistant=assistant,
            history=history,
            flow=FlowState(),   # reset flow (same as before)
            tool_calls=tool_calls,)
        return

    # --- Route / Continue flow 
    flow, intent_result, st_lang = _route_or_continue_flow(req=req,flow=flow,lang_heuristic=lang,tool_calls=tool_calls,)

    print(f"[DBG] flow={flow.name} step={flow.step} lang={lang} intent={getattr(intent_result,'intent',None)}") #TODO: delete

    # Dispatch by flow name 
    if flow.name == "small_talk" and not flow.done:
        yield from run_small_talk_flow(
            req=req,
            flow=flow,
            lang=st_lang,
            assistant=assistant,
            history=history,
            tool_calls=tool_calls,)
        return

    if flow.name == "stock_check" and not flow.done:
        yield from run_stock_check_flow(req = req,
           flow = flow, 
           lang = lang, 
           assistant=assistant, 
           history = history,
           tool_calls=tool_calls)
        return


    if flow.name == "med_info" and not flow.done:
        yield from run_med_info_flow( #yield everyting from this iterator function
            req=req,
            flow=flow,
            lang=lang,
            assistant=assistant,
            history=history,
            tool_calls=tool_calls,
        )
        return

    
    # Default fallback (kept identical to your last-resort behavior)
    assistant.content = ""
    yield from _yield_stream(
        stream=render_small_talk_stream(lang, req.message),
        assistant=assistant,
        history=history,
        flow=flow,
        tool_calls=tool_calls,
    )
    return



def _yield_state_only(
    *,
    assistant: ChatMessage,
    history: list[ChatMessage],
    flow: FlowState,
    tool_calls: list[ToolCallRecord],
) -> Iterator[Tuple[str, ChatResponse]]:
    # Empty delta, but updated flow state reaches the UI and helps avoid not terminating flows
    yield " ", ChatResponse(
        answer=assistant.content,
        history=history,
        flow=flow,
        tool_calls=tool_calls,
    )