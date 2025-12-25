# app/orchestrator.py
from typing import Iterator, Tuple
from app.schemas import ChatRequest, ChatResponse, ChatMessage, FlowState, ToolCallRecord
from app.llm import stream_llm

def handle_turn(req: ChatRequest) -> Iterator[Tuple[str, ChatResponse]]:
    """
    Stateless orchestrator.
    Yields (delta_text, partial_response) so the UI can stream.
    """
    # Copy flow-state from request (client-owned)
    history = list(req.history)
    flow = req.flow or FlowState()

    # Add the new user message to history
    history.append(ChatMessage(role="user", content=req.message))

    # Prepare an empty assistant message and stream into it
    assistant = ChatMessage(role="assistant", content="")
    history.append(assistant)

    tool_calls: list[ToolCallRecord] = []  # empty at the moment

    # Stream from the model and update the assistant message incrementally
    for delta in stream_llm(req.message):
        assistant.content += delta

        # Build a partial response (what we would return “so far” ) (for the sake of streaming?)
        partial = ChatResponse(
            answer=assistant.content,
            history=history,
            flow=flow,
            tool_calls=tool_calls,)
        yield delta, partial

    # End: final response is just the last yielded partial
