from fastapi import FastAPI
from app.llm import qury_llm
from fastapi.responses import StreamingResponse
from app.llm import stream_llm

app = FastAPI() #creating the web-app instance (the object that uvicorn runs)

# with streaming enabled
@app.post("/chat/stream")
def chat_stream(input: dict):
    message = input.get("message", "")

    def event_generator():
        for token in stream_llm(message):
            yield token

    return StreamingResponse(event_generator(), media_type="text/plain")


# no streaming if needed
@app.post("/chat")
def chat(input: dict):
    message = input.get("message", "") # avoid crashes if no message using the get 
    answer = qury_llm(message)
    return {
        "answer": answer,
        "trace": {"mode": "llm_only"} #metadata for debugging and/or future flows
    }


