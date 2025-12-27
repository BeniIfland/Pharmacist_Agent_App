from typing import Iterator, Tuple, Optional
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
from app.intent import IntentResult



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
    tool_calls: list[ToolCallRecord],
) -> tuple[FlowState, Optional[IntentResult], str]:
    """
    Preserves your current behavior:
    - If already in med_info, do NOT reroute mid-flow.
    - Else route with LLM; if not med_info => small_talk.
    - Returns: (flow, intent_result, selected_lang_for_smalltalk)
    """
    intent_result: Optional[IntentResult] = None

    if is_med_info_flow(flow):
        # continue existing med_info flow (do NOT re-route mid-flow)
        return flow, None, lang_heuristic

    intent_result = detect_intent_llm(req.message)
    tool_calls.append(
        ToolCallRecord(
            name="detect_intent",
            args={"text": req.message},
            result=intent_result.model_dump(),
        )
    )

    if intent_result.intent == "med_info":
        flow = start_med_info_flow()
        flow.step = "extract_med_name"
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
                result={"extracted": extracted},
            )
        )

        if not extracted: #if no med in the message (but we are in the flow #TODO: think if we ended up in the flow mistakenly
            assistant.content = ""
            flow.step = "extract_med_name"  # stay here
            yield from _yield_stream(
                stream=render_ask_med_name_stream(lang),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,
            )
            return

        flow.slots["med_name"] = extracted.strip()
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
            _finalize_flow(flow)

            assistant.content = ""
            yield from _yield_stream(
                stream=render_med_info_stream(lang, med),
                assistant=assistant,
                history=history,
                flow=flow,
                tool_calls=tool_calls,
            )
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

    # --- Route / Continue flow (unchanged behavior) ---
    flow, intent_result, st_lang = _route_or_continue_flow(
        req=req,
        flow=flow,
        lang_heuristic=lang,
        tool_calls=tool_calls,)

    print(f"[DBG] flow={flow.name} step={flow.step} lang={lang} intent={getattr(intent_result,'intent',None)}") #TODO: delete

    # --- Dispatch by flow name ---
    if flow.name == "small_talk" and not flow.done:
        yield from run_small_talk_flow(
            req=req,
            flow=flow,
            lang=st_lang,
            assistant=assistant,
            history=history,
            tool_calls=tool_calls,)
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
