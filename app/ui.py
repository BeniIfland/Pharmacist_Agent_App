import gradio as gr
from app.llm import stream_llm
from app.schemas import ChatRequest, ChatMessage, FlowState
from app.orchestrator import handle_turn
import time


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

def respond(message, history, flow_state):
    # Convert Gradio history list of dicts to ChatMessage list
    msg_history = []
    for m in history or []:
        msg_history.append(ChatMessage(role=m["role"], content=normalize_content(m["content"])))

    req = ChatRequest(
        message=message,
        history=msg_history,
        flow=FlowState(**(flow_state or {})), #unpacking the dict
        user_id=None,)

    # Start by echoing the user message in the UI immediately good for UX
    ui_history = (history or []) + [{"role": "user", "content": message}, {"role": "assistant", "content": ""}]
    yield ui_history, "", flow_state

    # Stream orchestrator updates
    last_flow = flow_state or {"name": None, "step": None, "slots": {}, "done": False}
    for _delta, partial in handle_turn(req):
        ui_history = [{"role": m.role, "content": m.content} for m in partial.history] #back to UI history format
        #update flow state
        last_flow = partial.flow.model_dump() #dump to convert back to normal dict for the UI
        yield ui_history, "", last_flow
        



#TODO: Add stop button / cancel  & Add safety gating mid-stream

def build_ui():
    with gr.Blocks(title="Agent Chat") as demo: #creates a gradio UI page
        gr.Markdown("# Pharmacist Assistant Chat") #title
        chatbot = gr.Chatbot() ##chat component
        msg = gr.Textbox(placeholder="Type a message...", label="Message")
        send = gr.Button("Send")

        flow_state = gr.State({"name": None, "step": None, "slots": {}, "done": False})

        send.click(respond, inputs=[msg, chatbot, flow_state], outputs=[chatbot, msg, flow_state])
        msg.submit(respond, inputs=[msg, chatbot, flow_state], outputs=[chatbot, msg, flow_state])
        

    return demo

if __name__ == "__main__":
    build_ui().launch(server_name="0.0.0.0", server_port=7860)


