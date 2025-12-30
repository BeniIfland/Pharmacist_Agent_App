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
    Stream helper.

    Consumes a text-delta iterator, appends each delta to the assistant message,
    and yields (delta, ChatResponse) so the UI can update incrementally.
    """
    for delta in stream:
        assistant.content += delta
        partial = ChatResponse(
            answer=assistant.content,
            history=history,
            flow=flow,
            tool_calls=tool_calls, )
        yield delta, partial


def _finalize_flow(flow: FlowState) -> None:
    """
    Mark the current flow as completed.
    """
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
        # print(f"[DBG] continuing active flow: {flow.name} step={flow.step}") 
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


def run_med_info_flow(*,req: ChatRequest,flow: FlowState,lang: str,assistant: ChatMessage,history: list[ChatMessage],tool_calls: list[ToolCallRecord],
) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Tool/flow runner for the **med_info** intent.

    This generator implements a small state machine (via ``flow.step`` and ``flow.slots``)
    that collects a medication name from the user, performs a deterministic lookup in the
    synthetic DB, and streams back factual medication label information.

    The function yields incremental assistant output via ``_yield_stream(...)`` (token/segment
    streaming), and ensures the client receives an updated ``FlowState`` at the end so the
    next user turn starts with no active flow.

    Flow steps
    ----------
    1) ``extract_med_name``
        - Try to extract a medication name from the current user message using ``extract_med_name``.
        - If extraction fails:
            - If we *explicitly* asked the user for a med name (``flow.slots["_awaiting"] == "med_name"``),
              treat the raw user message as the candidate (user might respond with only the name).
            - Otherwise, ask the user to provide a medication name and stay on this step.
        - On success, store ``flow.slots["med_name"]`` and advance to ``lookup``.

    2) ``lookup``
        - Call ``get_medication_by_name(med_name)`` and record the tool call.
        - Handle outcomes:
            - ``OK``: stream medication facts with ``render_med_info_stream(...)`` then finalize/reset flow.
              If a ``match_info`` payload exists (e.g., alias match), pass it to the renderer so the
              assistant can transparently explain the match.
            - ``AMBIGUOUS``: ask the user to choose from options, clear the stored name, and go back to
              ``extract_med_name`` while setting ``_awaiting="med_name"``.
            - ``NOT_FOUND``: ask the user for a different name and return to ``extract_med_name``.

    3) Fallback (last resort)
        - If the flow is in an unexpected step, render a constrained small-talk style response
          (useful as a safety net for misrouted turns).

    Parameters
    ----------
    req : ChatRequest
        Current request object holding the user's message (``req.message``) plus prior conversation
        state (history, user_id, etc.).
    flow : FlowState
        Mutable flow state for the current session/turn. Uses:
        - ``flow.step``: current step name (e.g., ``"extract_med_name"``, ``"lookup"``)
        - ``flow.slots``: dict of collected values and internal flags:
            - ``"med_name"``: the candidate medication name
            - ``"_awaiting"``: internal guard flag set to ``"med_name"`` when the UI asked the user
              to provide a medication name explicitly.
    lang : str
        Detected language code (typically ``"he"`` or ``"en"``). Passed to rendering helpers so all
        user-facing prompts are localized/consistent with the agent's supported languages.
    assistant : ChatMessage
        Mutable assistant message object. Its ``content`` is progressively built/streamed by
        the renderer helpers.
    history : list[ChatMessage]
        Conversation history, mutated by streaming helpers so that the client can display the
        evolving assistant message.
    tool_calls : list[ToolCallRecord]
        Per-turn trace list for debugging/review. Each tool invocation (extract/lookup) is appended
        here so you can render a timeline (e.g., via ``trace_markdown``).

    Returns
    -------
    Iterator[Tuple[str, ChatResponse]]
        A streaming iterator yielding ``(delta_text, ChatResponse)`` tuples.
        - ``delta_text`` is the incremental chunk to append in the UI.
        - ``ChatResponse`` is the full envelope containing the current assistant answer, updated
          history, updated flow state, and the list of tool call records.

    Notes
    -----
    - This flow is designed to be *factual* and *non-prescriptive*: it surfaces label-like info and
      a brief safety note, but should not provide diagnosis/treatment recommendations.
    - To avoid confusion in brand/generic resolution, pass ``match_info`` into the renderer when
      lookup succeeds (e.g., “You asked for Advil; the record is Ibuprofen.”).
    - The ``_awaiting`` slot is used as a guard so that raw user text is only treated as a med-name
      candidate after we asked for it explicitly (prevents random sentences being misinterpreted as
      medication names).
    """
    if flow.step == "extract_med_name":
        user_text = req.message.strip()
        awaiting = flow.slots.get("_awaiting")  # may be "med_name" or None
        extracted = extract_med_name(user_text)
        tool_calls.append(
            ToolCallRecord(name="extract_med_name",args={"text": user_text},result={"extracted": extracted},))
        
        candidate = extracted.strip() if extracted else None #Only accept raw user_text as candidate if we explicitly asked for a med name
        if not candidate and awaiting == "med_name": #if no med in the message (but we are in the flow 
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
        tool_calls=tool_calls,)
    return



def run_stock_check_flow(*, req: ChatRequest, flow: FlowState, lang: str, assistant: ChatMessage, history: list[ChatMessage], tool_calls: list[ToolCallRecord],) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Tool/flow runner for the **stock_check** intent.

    This generator implements a multi-step state machine (via ``flow.step`` and ``flow.slots``)
    that (1) collects a medication name and a branch name, (2) resolves each to a canonical record
    via deterministic lookup tools, and (3) queries branch stock status for that medication.

    The function yields incremental assistant output (streaming) as ``(delta_text, ChatResponse)``
    tuples. It also appends structured ``ToolCallRecord`` entries to ``tool_calls`` for audit/debug
    (e.g., timeline rendering in the UI).

    Flow steps
    ----------
    1) ``collect`` (also used when ``flow.step`` is ``None``/``""``)
        Goal: ensure ``flow.slots["med_name"]`` and ``flow.slots["branch_name"]`` exist.

        - Medication collection:
            - Attempt LLM extraction via ``extract_med_name(req.message)``.
            - If extraction fails but we explicitly asked for it
              (``flow.slots["_awaiting"] == "med_name"``), treat raw user message as the candidate.
            - On success, store ``flow.slots["med_name"]``.

        - Branch collection:
            - Attempt deterministic extraction via ``extract_branch_name(req.message)``.
            - If extraction fails but we explicitly asked for it
              (``flow.slots["_awaiting"] == "branch_name"``), treat raw user message as the candidate.
            - On success, store ``flow.slots["branch_name"]``.

        - If either field is missing after extraction, the flow asks *only for what’s missing*:
            - both missing: ``render_ask_med_and_branch_stream(lang)``
            - only med missing: ``render_ask_med_name_stream(lang)``
            - only branch missing: ``render_ask_branch_stream(lang)``
          In these cases the flow sets ``flow.slots["_awaiting"]`` appropriately and returns,
          staying in ``collect`` for the next turn.

        - If both are present, advance to ``resolve_med``.

    2) ``resolve_med``
        Goal: resolve ``flow.slots["med_name"]`` to a canonical medication record.

        - Calls ``get_medication_by_name(med_name)`` and records the tool call.
        - Outcomes:
            - ``AMBIGUOUS``: ask the user to clarify via ``render_ambiguous_stream(...)``,
              clear ``med_name`` and return to ``collect`` with ``_awaiting="med_name"``.
            - ``NOT_FOUND``: ask again via ``render_not_found_stream(...)``, clear ``med_name`` and
              return to ``collect`` with ``_awaiting="med_name"``.
            - ``OK``: store:
                - ``flow.slots["med"]`` (the canonical medication record)
                - ``flow.slots["med_match_info"]`` (optional, e.g., alias match metadata)
              then advance to ``resolve_branch``.

    3) ``resolve_branch``
        Goal: resolve ``flow.slots["branch_name"]`` to a canonical branch record.

        - Calls ``get_branch_by_name(branch_name)`` and records the tool call.
        - Outcomes:
            - ``AMBIGUOUS``: ask the user to clarify via ``render_ambiguous_branch_stream(...)``,
              clear ``branch_name`` and return to ``collect`` with ``_awaiting="branch_name"``.
            - ``NOT_FOUND``: ask again via ``render_branch_not_found_stream(...)``, clear ``branch_name`` and
              return to ``collect`` with ``_awaiting="branch_name"``.
            - ``OK``: store ``flow.slots["branch"]`` (canonical branch record),
              clear ``_awaiting`` and advance to ``stock``.

    4) ``stock``
        Goal: query and present stock status for the resolved (branch, medication) pair.

        - Calls ``get_stock(branch_id, med_id)`` and records the tool call.
        - Extracts ``stock_status`` from the result (defaults to ``"UNKNOWN"`` if missing).
        - Streams the final answer via ``render_stock_check_stream(lang, med, branch, stock_status, match_info=...)``.
          Passes ``match_info`` (from ``med_match_info``) so the response can transparently explain
          brand/generic alias resolution if needed.

        - Finalizes and resets the flow:
            - ``_finalize_flow(flow)``
            - yield state-only update (so the client sees the final flow state)
            - yield a final response with ``flow=FlowState()`` so the next turn starts with no active flow.

    Parameters
    ----------
    req : ChatRequest
        Current request object holding the user's message (``req.message``) plus session metadata.
    flow : FlowState
        Mutable flow state for this multi-turn interaction. Uses:
        - ``flow.step``: current step (``collect``, ``resolve_med``, ``resolve_branch``, ``stock``)
        - ``flow.slots``: collected parameters and internal flags:
            - ``"med_name"``: user-provided or extracted medication name (pre-resolution)
            - ``"branch_name"``: user-provided or extracted branch name (pre-resolution)
            - ``"med"``: resolved medication record (post-resolution)
            - ``"branch"``: resolved branch record (post-resolution)
            - ``"med_match_info"``: optional metadata about how the medication name was matched
            - ``"_awaiting"``: internal guard flag indicating what the flow asked the user for next
              (``"med_name"`` / ``"branch_name"``)
    lang : str
        Detected language code (typically ``"he"`` or ``"en"``). Used by renderers.
    assistant : ChatMessage
        Mutable assistant message. Its content is built progressively during streaming.
    history : list[ChatMessage]
        Conversation history, updated as the assistant streams output.
    tool_calls : list[ToolCallRecord]
        Per-turn execution trace list. Each extractor/lookup call is appended for debugging/review.

    Returns
    -------
    Iterator[Tuple[str, ChatResponse]]
        Streaming iterator yielding ``(delta_text, ChatResponse)`` tuples, where:
        - ``delta_text`` is the incremental chunk to append in the UI
        - ``ChatResponse`` includes the current assistant answer, updated history, updated flow,
          and the list of tool call records.

    Notes
    -----
    - The ``_awaiting`` slot is a critical guard: it ensures that raw user text is only treated as a
      medication/branch candidate when the user is responding to a direct prompt for that value.
    - This flow is meant to be factual: it reports stock availability/status but should not provide
      medical advice or treatment recommendations.
    - If you want consistent streaming behavior across flows, consider migrating the places where you
      manually yield from renderers (``for delta in ...``) to the shared ``_yield_stream(...)`` helper.
      (Not required for correctness, but helps keep response envelopes uniform.)
    """
    # Steps:
    #   - collect: ensure med_name + branch_name in slots
    #   - resolve_med: get_medication_by_name
    #   - resolve_branch: get_branch_by_name
    #   - stock: get_stock
    #   - done


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
        # print(f"missing_med:{missing_med} missing_branch:{missing_branch}") 
        # print(f"flow slots: med: {flow.slots.get("med_name","____")}, branch: {flow.slots.get("branch_name","____")}")
        if missing_med and missing_branch:
            flow.slots["_awaiting"] = "med_name" # safety mechanism 
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
    """
    Stateless turn orchestrator for the streaming UI.

    - Detects language (he/en), appends the user message + an assistant placeholder to history.
    - Applies a safety override for medical-advice requests (refuse + reset flow).
    - Optionally escapes an in-progress flow if the user is not cooperating / wants to move on.
    - Routes to (or continues) the active flow using the LLM intent router.
    - Dispatches to the matching flow runner, which streams back (delta, ChatResponse).
    - Falls back to small-talk renderer if nothing matched.
    """

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
        flow.slots.pop("_awaiting", None) #aborting, should stop eaiting 

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
        # tool_calls.append(ToolCallRecord( name="flow_escape", args={"flow": flow.name, "text": req.message}, result={"action": "reset_and_reroute", "reason": reason},))
        flow = FlowState()  # reset so router will route and not continue the current flow

    # IMPORTANT: now proceed to normal routing (LLM intent detector)
    # --- Route / Continue flow 
    flow, intent_result, st_lang = _route_or_continue_flow(req=req,flow=flow,lang_heuristic=lang,tool_calls=tool_calls,)

    # print(f"[DBG] flow={flow.name} step={flow.step} lang={lang} intent={getattr(intent_result,'intent',None)}") 

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



def _yield_state_only(*,assistant: ChatMessage,history: list[ChatMessage],flow: FlowState,tool_calls: list[ToolCallRecord],
) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Yield a no-content update to propagate the latest FlowState to the client.

    Used at flow completion to ensure the UI receives the final flow state
    (e.g., marked as done) even when no additional text is streamed.
    """
    # Empty delta, but updated flow state reaches the UI and helps avoid not terminating flows
    yield " ", ChatResponse(
        answer=assistant.content,
        history=history,
        flow=flow,
        tool_calls=tool_calls,)

def run_rx_verify_flow(*,req: ChatRequest,flow: FlowState,lang: str,assistant: ChatMessage,history: list[ChatMessage],tool_calls: list[ToolCallRecord],) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Tool/flow runner for the **rx_verify** intent.

    This generator implements a small state machine that can verify a single prescription
    by rx_id *or* list prescriptions for a user by user_id. It streams assistant output and
    records all extractor/tool calls in ``tool_calls`` for debugging/audit.

    Steps
    -----
    - ``collect``:
        Extract ``rx_id`` and ``user_id`` from the user's message (regex-based extractors).
        If an rx_id is found -> go to ``verify_rx``.
        Else if a user_id is found -> go to ``list_user_rx``.
        Else prompt the user for either value and stay in ``collect``.
        Uses ``flow.slots["_awaiting"]`` as a guard to only accept raw user text as a candidate
        when the assistant explicitly asked for it.
    - ``verify_rx``:
        Call ``verify_prescription(rx_id)``.
        If NOT_FOUND -> ask again for rx_id and return to ``collect``.
        If OK -> stream verification result, finalize flow, then reset flow on the client.
    - ``list_user_rx``:
        Call ``get_prescriptions_for_user(user_id)``.
        If user not found -> ask again for user_id and return to ``collect``.
        If OK -> stream the user's prescription list, finalize flow, then reset flow on the client.
    - Fallback:
        If the flow reaches an unexpected step, respond via the constrained small-talk renderer.

    Parameters
    ----------
    req : ChatRequest
        Current request containing the user's message (``req.message``) and prior state.
    flow : FlowState
        Mutable flow state. Uses:
        - ``flow.step``: current step name (``collect``, ``verify_rx``, ``list_user_rx``)
        - ``flow.slots``: collected values and internal flags:
            - ``"rx_id"``: extracted or user-provided prescription id
            - ``"user_id"``: extracted or user-provided user id
            - ``"_awaiting"``: guard indicating what we asked the user for next
              (``"rx_id"``, ``"user_id"``, or ``"rx_or_user"``)
    lang : str
        Detected language code (e.g., ``"he"`` / ``"en"``), passed to renderers.
    assistant : ChatMessage
        Mutable assistant message that is built during streaming.
    history : list[ChatMessage]
        Conversation history updated as output is streamed.
    tool_calls : list[ToolCallRecord]
        Per-turn tool trace list populated with extractor calls and DB/tool calls.

    Returns
    -------
    Iterator[Tuple[str, ChatResponse]]
        Streaming iterator yielding ``(delta_text, ChatResponse)`` tuples.

    Notes
    -----
    - ``extract_rx_id`` / ``extract_user_id`` are regex-based; they are recorded in ``tool_calls``
      even if they return None for transparency.
    - The flow finalization pattern is:
        stream final content -> ``_finalize_flow(flow)`` -> ``_yield_state_only(...)`` -> yield a
        final response with ``flow=FlowState()`` so the next turn begins with no active flow.
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
    """
    Decide whether to abort the current flow and reroute.

    Returns a short reason string if the flow should be escaped,
    or None if the flow should continue.
    """

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