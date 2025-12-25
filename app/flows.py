from app.schemas import FlowState, ToolCallRecord

def start_med_info_flow() -> FlowState:
    return FlowState(name="med_info", step="collect_med_name", slots={}, done=False)

def is_med_info_flow(flow: FlowState) -> bool:
    return flow is not None and flow.name == "med_info" and not flow.done
