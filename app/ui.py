import gradio as gr
from app.llm import stream_llm
from app.schemas import ChatRequest, ChatMessage, FlowState
from app.orchestrator import handle_turn
import time


def respond(message, history, flows_tate):
    # t0 = time.perf_counter() #!

    history = history or []
    # adding the user's message in the correct dict format
    history.append({"role": "user", "content": message})
    # Add an empty assistant message which will be filled while streaming
    history.append({"role": "assistant", "content": ""})


    # print("UI yield 0 at", time.perf_counter() - t0)#!
    yield history, "" # yield nothing imeddietly to overcome gradio's 'processing' delay

    #sreaming
    partial = ""
    for token in stream_llm(message):
        # print("UI yield token at", time.perf_counter() - t0)#!
        partial += token
        history[-1]["content"] = partial
        yield history, ""  # stream updates to the UI
        



#TODO: Add stop button / cancel  & Add safety gating mid-stream

def build_ui():
    with gr.Blocks(title="Agent Chat") as demo: #creates a gradio UI page
        gr.Markdown("# Pharmacist Assistant Chat") #title
        chatbot = gr.Chatbot() ##chat component
        msg = gr.Textbox(placeholder="Type a message...", label="Message")
        send = gr.Button("Send")

        send.click(respond, inputs=[msg, chatbot], outputs=[chatbot, msg])
        msg.submit(respond, inputs=[msg, chatbot], outputs=[chatbot, msg])

    return demo

if __name__ == "__main__":
    build_ui().launch(server_name="0.0.0.0", server_port=7860)


