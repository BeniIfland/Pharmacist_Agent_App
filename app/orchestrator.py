from typing import Iterator, Tuple, Optional
from typing import Iterator, Tuple
from app.schemas import ChatRequest, ChatResponse, ChatMessage, FlowState, ToolCallRecord
from app.llm import extract_med_name,render_user_rx_list_stream
# from app.flows import start_med_info_flow,start_stock_check_flow
from app.tools import get_medication_by_name, get_stock,verify_prescription,get_prescriptions_for_user
from app.simple_detectors import detect_lang,extract_branch_name,extract_user_id,extract_rx_id
from app.llm import extract_med_name, render_med_info_stream, render_ambiguous_stream, render_not_found_stream, render_ask_med_name_stream,render_rx_verify_stream,render_user_not_found_stream
from app.llm import detect_intent_llm, render_small_talk_stream, render_ask_rx_or_user_stream,render_rx_not_found_stream
from app.llm import render_ask_branch_stream,render_ask_med_and_branch_stream,render_ambiguous_branch_stream,render_branch_not_found_stream
from app.safety import is_medical_advice_request, plausible_branch_name,plausible_med_name,is_smalltalk_or_meta, plausible_rx_id,plausible_user_id
from app.llm import render_refusal_stream, render_stock_check_stream
from app.intent import IntentResult
from app.tools import get_branch_by_name
from typing import Optional
from app.safety import is_cancel



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
        # tool_calls.append(ToolCallRecord(name="active_flow_continuation",args={"reason": "continue_active_flow", "flow": flow.name, "step": flow.step},result={"action": "continue"},))
        print(f"[DBG] continuing active flow: {flow.name} step={flow.step}") #TODO: delete debug
        return flow, None, lang_heuristic

    intent_result = detect_intent_llm(req.message)
    tool_calls.append(ToolCallRecord( name="detect_intent", args={"text": req.message}, result=intent_result.model_dump(),))

    if intent_result.intent == "med_info":
        flow = FlowState(name="med_info", step="extract_med_name", slots={}, done=False)
        flow.step = "extract_med_name"

    elif intent_result.intent == "stock_check":
        flow = FlowState(name="stock_check", step="collect", slots={},done=False)

    elif intent_result.intent == "rx_verify":
        flow = FlowState(name="rx_verify", step="collect", slots={}, done=False) 
    
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
    tool_calls.append(ToolCallRecord(name="render_small_talk",args={"lang": lang},result={"note": "streamed"},))

    assistant.content = ""
    yield from _yield_stream(
        stream=render_small_talk_stream(lang, req.message),
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
    #TODO: DOCUMENTATION POR FAVOR
    if flow.step == "extract_med_name":
        user_text = req.message.strip()
        awaiting = flow.slots.get("_awaiting")  # may be "med_name" or None
        extracted = extract_med_name(user_text)
        tool_calls.append(
            ToolCallRecord(name="extract_med_name",args={"text": user_text},result={"extracted": extracted},))
        
        candidate = extracted.strip() if extracted else None #Only accept raw user_text as candidate if we explicitly asked for a med name
        if not candidate and awaiting == "med_name": #if no med in the message (but we are in the flow #TODO: think if we ended up in the flow mistakenly
            candidate = user_text
        # If we still don't have a candidate, ask for med name
        if not candidate:
            flow.slots["_awaiting"] = "med_name" #safety mechanism
            assistant.content = ""
            # flow.step = "extract_med_name"  # stay here
            yield from _yield_stream(
                stream=render_ask_med_name_stream(lang),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,)
            return

        flow.slots["med_name"] = candidate
        if awaiting == "med_name":
            flow.slots.pop("_awaiting", None) #waiting resolved
        flow.step = "lookup"

    if flow.step == "lookup":
        med_name = (flow.slots.get("med_name") or "").strip()
        tool_result = get_medication_by_name(med_name)
        tool_calls.append(ToolCallRecord(name="get_medication_by_name", args={"name": med_name},result=tool_result,))

        if tool_result["status"] == "OK":
            med = tool_result["medication"]
            match_info = tool_result.get("match_info")
            flow.slots.pop("_awaiting", None) #waiting resolved
            
            assistant.content = ""
            yield from _yield_stream(
                stream=render_med_info_stream(lang, med, match_info = match_info),
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
            flow.slots.pop("med_name", None)
            flow.slots["_awaiting"] = "med_name" #safety mechanism
            assistant.content = ""
            yield from _yield_stream(
                stream=render_ambiguous_stream(lang, options),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,)
            return

        # NOT_FOUND
        flow.step = "extract_med_name"
        flow.slots.pop("med_name", None)
        flow.slots["_awaiting"] = "med_name" #safety mechanism
        assistant.content = ""
        yield from _yield_stream(
            stream=render_not_found_stream(lang),
            assistant=assistant,
            history=history,
            flow=flow,
            tool_calls=tool_calls,)
        return

    # Last-resort fallback 
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
        awaiting = flow.slots.get("_awaiting") # "med_name" | "branch_name" | None
        # 1) med_name
        if not flow.slots.get("med_name"):
            extracted = extract_med_name(req.message.strip())
            tool_calls.append(ToolCallRecord(name="extract_med_name", args={"text": req.message.strip()}, result={"extracted": extracted},))
            candidate = extracted.strip() if extracted else None
            if not candidate and awaiting == "med_name":
                # only when we explicitly asked for a med name
                candidate = req.message.strip()
            if candidate:
                flow.slots["med_name"] = candidate
                if awaiting == "med_name":
                    flow.slots.pop("_awaiting", None)

        # 2) branch_name (deterministic)
        if not flow.slots.get("branch_name"):
            br = extract_branch_name(req.message)
            tool_calls.append(ToolCallRecord(name="extract_branch_name", args={"text": req.message}, result={"extracted": br},))
            candidate_br = br.strip() if br else None
            if not candidate_br and awaiting == "branch_name":
            # only when we explicitly asked for a branch
                candidate_br = req.message.strip()
            if candidate_br:
                flow.slots["branch_name"] = candidate_br
                if awaiting == "branch_name":
                    flow.slots.pop("_awaiting", None)
                 
                

        # Ask for what’s missing (minimal)
        missing_med = not flow.slots.get("med_name")
        missing_branch = not flow.slots.get("branch_name")
        print(f"missing_med:{missing_med} missing_branch:{missing_branch}") #TODO: debug delete
        print(f"flow slots: med: {flow.slots.get("med_name","____")}, branch: {flow.slots.get("branch_name","____")}")
        if missing_med and missing_branch:
            flow.slots["_awaiting"] = "med_name" # safety mechanism #TODO: we may want to put a label of both_missing and address it in should_escape_flow
            assistant.content = ""
            # You can make a dedicated renderer; for now reuse verbalizer approach or a deterministic string streamer
            for delta in render_ask_med_and_branch_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if missing_med:
            flow.slots["_awaiting"] = "med_name"
            assistant.content = ""
            for delta in render_ask_med_name_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if missing_branch:
            flow.slots["_awaiting"] = "branch_name"
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
            flow.slots["_awaiting"] = "med_name"
            assistant.content = ""
            for delta in render_ambiguous_stream(lang, options):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if med_res["status"] != "OK":
            #NOT_FOUND
            flow.slots["_awaiting"] = "med_name"
            flow.step = "collect"
            flow.slots.pop("med_name", None)
            flow.slots.pop("med", None)
            assistant.content = ""
            for delta in render_not_found_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        flow.slots["med"] = med_res["medication"]  
        flow.slots["med_match_info"] = med_res.get("match_info")
        flow.step = "resolve_branch"

    # Step: resolve_branch 
    if flow.step == "resolve_branch":
        branch_name = flow.slots["branch_name"]
        br_res = get_branch_by_name(branch_name)
        tool_calls.append(ToolCallRecord(name="get_branch_by_name", args={"name": branch_name}, result=br_res,))

        if br_res["status"] == "AMBIGUOUS":
            options = [b["display_name"] for b in br_res["matches"]]
            flow.step = "collect"
            flow.slots["_awaiting"] = "branch_name" #safety mechanism
            flow.slots.pop("branch_name", None)
            assistant.content = ""
            for delta in render_ambiguous_branch_stream(lang, options):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        if br_res["status"] != "OK":
            #NOT_FOUND
            flow.step = "collect"
            flow.slots["_awaiting"] = "branch_name" #safety mechanism
            flow.slots.pop("branch_name", None)
            flow.slots.pop("branch", None)
            assistant.content = ""
            for delta in render_branch_not_found_stream(lang):
                assistant.content += delta
                yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)
            return

        flow.slots["branch"] = br_res["branch"] #save correct value after it was resolved (status == OK)
        flow.slots.pop("_awaiting", None)  # waiting resolved
        flow.step = "stock"

    #Step: stock 
    if flow.step == "stock":
        med = flow.slots["med"] 
        branch = flow.slots["branch"]
        stock_res = get_stock(branch["branch_id"], med["med_id"])
        tool_calls.append(ToolCallRecord(name="get_stock",args={"branch_id": branch["branch_id"], "med_id": med["med_id"]},result=stock_res,))

        # Always OK in the simple tool, allows expension if time allows
        stock_status = stock_res.get("stock_status", "UNKNOWN")

        assistant.content = ""
        match_info = flow.slots.get("med_match_info")
        for delta in render_stock_check_stream(lang, med, branch, stock_status, match_info=match_info):
            assistant.content += delta
            yield delta, ChatResponse(answer=assistant.content, history=history, flow=flow, tool_calls=tool_calls)

        flow.slots.pop("_awaiting", None)  # waiting resolved
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



def handle_turn(req: ChatRequest) -> Iterator[Tuple[str, ChatResponse]]:
    """ Stateless orchestrator. Yields (delta_text, partial_response) for streaming UI. """

    lang = detect_lang(req.message) #simple heuristic that using encoding to detect hebrew\english

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
        flow.slots.pop("_awaiting", None) #aborting, should stop eaiting #TODO: hope it won't cause a bug

        assistant.content = ""
        yield from _yield_stream(
            stream=render_refusal_stream(lang, req.message),
            assistant=assistant,
            history=history,
            flow=FlowState(),   # reset flow (same as before)
            tool_calls=tool_calls,)
        return

    # safety mechanism gate to escape flow if we are stuck on waiting and user wants to proceed or not co-operating
    reason = should_escape_flow(flow, req.message)
    if reason:
        print(f"Escaping flow because: {reason}") #TODO: delete debugging
        # tool_calls.append(ToolCallRecord( name="flow_escape", args={"flow": flow.name, "text": req.message}, result={"action": "reset_and_reroute", "reason": reason},))
        flow = FlowState()  # reset so router will route and not continue the current flow
    # IMPORTANT: now proceed to normal routing (LLM intent detector)

    # --- Route / Continue flow 
    flow, intent_result, st_lang = _route_or_continue_flow(req=req,flow=flow,lang_heuristic=lang,tool_calls=tool_calls,)

    print(f"[DBG] flow={flow.name} step={flow.step} lang={lang} intent={getattr(intent_result,'intent',None)}") #TODO: delete

    # Dispatch by flow name 
    if flow.name == "small_talk" and not flow.done:
        yield from run_small_talk_flow(req=req,flow=flow,lang=st_lang,assistant=assistant,history=history,tool_calls=tool_calls,)
        return

    if flow.name =="rx_verify" and not flow.done:
        yield from run_rx_verify_flow(req=req,flow=flow,lang=lang,assistant=assistant,history=history,tool_calls=tool_calls,)
        return

    if flow.name == "stock_check" and not flow.done:
        yield from run_stock_check_flow(req = req,flow = flow, lang = lang, assistant=assistant, history = history,tool_calls=tool_calls)
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

    
    # Last-resort fallback
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
        tool_calls=tool_calls,)

def run_rx_verify_flow(*,req: ChatRequest,flow: FlowState,lang: str,assistant: ChatMessage,history: list[ChatMessage],tool_calls: list[ToolCallRecord],) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Steps:
      - collect: need rx_id OR user_id
      - verify_rx: verify_prescription
      - list_user_rx: get_prescriptions_for_user
      - done
    """
    if flow.step in (None, "", "collect"):
        awaiting = flow.slots.get("_awaiting")  # safety mechanism
        text = req.message.strip()

        # try to extract rx_id / user_id using the extractors (regex based) Optional: use an LLM to do it
        rx = extract_rx_id(text)
        uid = extract_user_id(text)

        tool_calls.append(ToolCallRecord(name="extract_rx_id",args={"text": text},result={"extracted": rx},))
        tool_calls.append(ToolCallRecord(name="extract_user_id",args={"text": text},result={"extracted": uid},))

        # Only accept raw text as candidate if we explicitly asked for that slot
        if not rx and awaiting == "rx_id":
            rx = text if text else None
        if not uid and awaiting == "user_id":
            uid = text if text else None

        # If awaiting either rx_or_user, only accept raw if it *looks* like one of them.
        if awaiting == "rx_or_user" and not (rx or uid):
            # avoiding setting raw text to either slot, just prompt again
            pass

        if rx:
            flow.slots["rx_id"] = rx
            if awaiting in ("rx_id", "rx_or_user"):
                flow.slots.pop("_awaiting", None)
            flow.step = "verify_rx"

        elif uid:
            flow.slots["user_id"] = uid
            if awaiting in ("user_id", "rx_or_user"):
                flow.slots.pop("_awaiting", None)
            flow.step = "list_user_rx"

        else:
            # Missing both → ask
            flow.slots["_awaiting"] = "rx_or_user"
            assistant.content = ""
            yield from _yield_stream(
                stream=render_ask_rx_or_user_stream(lang),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,)
            return

    if flow.step == "verify_rx":
        
        rx_id = (flow.slots.get("rx_id") or "").strip()
        
        res = verify_prescription(rx_id)
        # print(f"res is: {res}")
        tool_calls.append(ToolCallRecord(name="verify_prescription",args={"rx_id": rx_id},result=res,))

        if res["status"] != "OK":
            # NOT_FOUND: ask again, keep flow
            flow.step = "collect"
            flow.slots.pop("rx_id", None)
            flow.slots["_awaiting"] = "rx_id"
            assistant.content = ""
            yield from _yield_stream(
                stream=render_rx_not_found_stream(lang),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,)
            return

        #if "OK"
        rx = res["rx"]
        assistant.content = ""
        yield from _yield_stream(
            stream=render_rx_verify_stream(lang, rx),
            assistant=assistant,
            history=history,
            flow=flow,
            tool_calls=tool_calls,)

        flow.slots.pop("_awaiting", None)
        _finalize_flow(flow)
        # CRITICAL: send updated flow state to client
        yield from _yield_state_only(
            assistant=assistant, history=history, flow=flow, tool_calls=tool_calls)
        flow_reset = FlowState()
        # CRITICAL: send updated flow state to client
        yield " ", ChatResponse(answer=assistant.content, history=history, flow=flow_reset, tool_calls=tool_calls)
        return

    if flow.step == "list_user_rx":
        user_id = (flow.slots.get("user_id") or "").strip().lower()
        res = get_prescriptions_for_user(user_id)
        tool_calls.append(ToolCallRecord(name="get_prescriptions_for_user",args={"user_id": user_id},result=res,))

        if res["status"] != "OK":
            flow.step = "collect"
            flow.slots.pop("user_id", None)
            flow.slots["_awaiting"] = "user_id"
            assistant.content = ""
            yield from _yield_stream(stream=render_user_not_found_stream(lang),assistant=assistant,history=history,flow=flow,tool_calls=tool_calls,)
            return

        user = res["user"]
        items = res["prescriptions"]

        assistant.content = ""
        yield from _yield_stream(
            stream=render_user_rx_list_stream(lang, user, items), assistant=assistant, history=history, flow=flow, tool_calls=tool_calls,)

        flow.slots.pop("_awaiting", None)
        _finalize_flow(flow)

        yield from _yield_state_only(
            assistant=assistant, history=history, flow=flow, tool_calls=tool_calls)
        flow_reset = FlowState()
        yield " ", ChatResponse(answer=assistant.content, history=history, flow=flow_reset, tool_calls=tool_calls)
        return

    # Last-resort fallback 
    assistant.content = ""
    yield from _yield_stream(
        stream=render_small_talk_stream(lang, req.message),
        assistant=assistant,
        history=history,
        flow=flow,
        tool_calls=tool_calls,)
    return



# a safety mechanism which is in charge of not getting stuck inside flows when waiting for the user to fill missing slots

def should_escape_flow(flow: FlowState, user_text: str) -> Optional[str]:
    if not flow or not flow.name or flow.done:
        return None

    if is_cancel(user_text): # user wants to cancel and types a clear cancel pattern
        return "cancel"

    # If user is clearly doing small talk or meta, escape immediately
    if is_smalltalk_or_meta(user_text):
        return "smalltalk_or_meta"

    awaiting = flow.slots.get("_awaiting")

    # If we're awaiting a slot and user gave a plausible slot answer,
    # DO NOT escape and let the flow resolve it.
    if awaiting == "med_name" and plausible_med_name(user_text):
        return None #not to cancel and not to re-route
    if awaiting == "branch_name" and plausible_branch_name(user_text):
        return None #not to cancel and not to re-route
     # Rx flow await states
    if awaiting == "rx_id" and plausible_rx_id(user_text):
        return None
    if awaiting == "user_id" and plausible_user_id(user_text):
        return None
    if awaiting == "rx_or_user" and (plausible_rx_id(user_text) or plausible_user_id(user_text)):
        return None
    
    # Otherwise allow reroute (new topic / long message / not a slot answer)
    if awaiting in ("med_name", "branch_name", "rx_id", "user_id", "rx_or_user"):
        return f"awaiting_{awaiting}_but_not_plausible"

    return None