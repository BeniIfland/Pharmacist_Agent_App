import gradio as gr
from app.llm import stream_llm
from app.schemas import ChatRequest, ChatMessage, FlowState
from app.orchestrator import handle_turn
import time

TRACE_LABELS = {
    "safety_gate": "Safety gate activated (medical advice refusal)",
    # "flow_escape": "Escaped flow + rerouted",
    "detect_intent": "Intent routing",
    "extract_med_name": "Trying to exract medicine name",
    "extract_branch_name": "Trying to exract branch name",
    "get_medication_by_name": "DB lookup: medication",
    "get_branch_by_name": "DB lookup: branch",
    "get_stock": "DB lookup: inventory status",
    "verify_prescription": "DB lookup: prescription status",
    "get_prescriptions_for_user": "DB lookup: user prescriptions",
    "render_med_info": "Render medication info answer",
    "render_stock_check": "Render inventory info answer",
    "render_small_talk": "Render small talk",
    "render_refusal": "Render medical advice refusal",
    "extract_rx_id": "Trying to exract prescription",
    "extract_user_id" : "Trying to exract user ID",
    # "active_flow_continuation" : "Continued active flow"
}

def normalize_content(content) -> str:
    """
    This function is used to normalize the UIs messages into pure strings
    
    :param content: UIs message
    :return: normalized string
    :rtype: str
    """
    # If already a string, return it
    if isinstance(content, str):
        return content
    # If Gradio gives list of blocks like [{"type":"text","text":"..."}]
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    # Fallback
    return str(content)

def respond(message, history, flow_state,trace_state):
    """
    message: str
    history: list[dict]  (gr.Chatbot type="messages")
    flow_state: dict     (stored in gr.State)
    trace_state: list    (stored in gr.State)  <-- NEW
    """
    # Per-turn trace: clear at start of turn
    
    trace_table_rows = []
    trace_md = "_Waiting for input…_"
    # Convert Gradio history list of dicts to ChatMessage list
    msg_history = []
    for m in history or []:
        msg_history.append(ChatMessage(role=m["role"], content=normalize_content(m["content"])))

    req = ChatRequest(message=message,history=msg_history,flow=FlowState(**(flow_state or {})),) #unpacking the dictuser_id=None,)

    # Start by echoing the user message in the UI immediately good for UX
    ui_history = (history or []) + [{"role": "user", "content": message}, {"role": "assistant", "content": ""}]
    yield ui_history, "", flow_state, trace_md

    # yield cleared trace + unchanged flow
    # yield ui_history, "", flow_state, trace, trace

    # Stream orchestrator updates
    last_flow = flow_state or {"name": None, "step": None, "slots": {}, "done": False}
    for _delta, partial in handle_turn(req):
        ui_history = [{"role": m.role, "content": m.content} for m in partial.history] #back to UI history format
        #update flow state
        last_flow = partial.flow.model_dump() #dump to convert back to normal dict for the UI

        # Build trace table rows from partial.tool_calls
        trace_md = trace_markdown(partial.tool_calls)
        # #update trace from partial.tool_calls (current turn only)
        # trace_state = trace_table_rows

        # Yield chat, textbox, flow_state, trace markdown
        yield ui_history, "", last_flow, trace_md
        
# def _to_jsonable_tool_calls(tool_calls):
#     out = []
#     for tc in tool_calls or []:
#         if hasattr(tc, "model_dump"):
#             out.append(tc.model_dump())
#         else:
#             out.append(tc)
#     return out


#TODO: Add stop button / cancel  & Add safety gating mid-stream

def build_ui():
    with gr.Blocks(title="Agent Chat") as demo: #creates a gradio UI page
        gr.Markdown("# Pharmacist Assistant Chat") #title
        # history_state = gr.State([]) 
        flow_state = gr.State({"name": None, "step": None, "slots": {}, "done": False})
        trace_state = gr.State([])  

        with gr.Row(): 
             #chat interface
            with gr.Column(scale=3):
                chatbot = gr.Chatbot(height=350) ##chat component
                msg = gr.Textbox(placeholder="Type a message...", label="Message")
                send = gr.Button("Send")
                # send.click(respond, inputs=[msg, chatbot, flow_state], outputs=[chatbot, msg, flow_state])
                # msg.submit(respond, inputs=[msg, chatbot, flow_state], outputs=[chatbot, msg, flow_state])
            #trace tools and state interface
            with gr.Column(scale=2):
                gr.Markdown("Agent Tracing:")
                trace_panel = gr.Markdown(value="_Waiting for input…_")
        
        send.click(respond,inputs=[msg, chatbot, flow_state, trace_state],outputs=[chatbot, msg, flow_state, trace_panel],)
        msg.submit(respond,inputs=[msg, chatbot, flow_state, trace_state],outputs=[chatbot, msg, flow_state, trace_panel],)
    return demo


def trace_markdown(tool_calls) -> str:
    """
    Turn tool\ internal function calls into a clean per-turn execution timeline (Markdown).
    Shows each step once + a short description.
    """
    if not tool_calls:
        return "_Waiting for input…_"

    seen = set()
    lines = []
    for tc in tool_calls:
        name = getattr(tc, "name", None) or (tc.get("name") if isinstance(tc, dict) else str(tc))
        if not name or name in seen:
            continue
        seen.add(name)
        desc = TRACE_LABELS.get(name, "")
        # show name + description (name helps debugging, description helps reviewer)
        if desc:
            lines.append(f"- ✓ **{name}** — {desc}")
        else:
            lines.append(f"- ✓ **{name}**")

    return "\n".join(lines) if lines else "_Waiting for input…_"








if __name__ == "__main__":
    build_ui().launch(server_name="0.0.0.0", server_port=7860)


