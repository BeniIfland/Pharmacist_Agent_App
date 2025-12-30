# Evaluation Plan - Pharmacist Assistant Agent

## Evaluation Purpose

The goal of this evaluation is to verify that the agentic assitant app bahaves in a correct, safe and predictable manner.
The evaluation was focused on: 
- Correct execution of multi-step conversational flows with predictable tool calls
- Proper enforcement of safety constraints (no medical advice)
- Robust handling of incomplete, ambiguous, or changing user inputs
- Clear separation between deterministic tool logic and LLM-based phrasing and decisision making 

This evaluation is qualitative and behavior-based, reflecting how the agent would be tested as a POC or internal review rather than large-scale production deployment.

---
## Methodology


The agent was evaluated manually through interactive conversations using the Gradio user interface.
The evaluation process consisted of:
- Executing predefined conversation scripts (see [Demo Journeys](demo_inputs.md)).
- Observing the agent’s responses, follow-up questions, and flow progression.
- Verifying that the correct tools and flows were triggered using the tracing panel.
- Capturing screenshots as evidence of correct behavior.
- Deviating from the scripts with unexpected inputs.
- Observing behavior and iteratively refining its responses and re-evaluating.

All evaluations were performed with the agent running in a stateless configuration, with no server-side memory.

---
## Evaluation Verticals

### Flow Correctness
Each multi-step flow was evaluated to ensure that:
- The agent correctly identifies the user’s intent.
- Required information is collected (slot filling).
- The flow progresses only when sufficient information is available.
- Ambiguous or missing inputs result in clarification questions rather than guesses\hallucinations.

Flows evaluated:
- Medication information lookup
- Stock availability check
- Prescription verification

### Safety Enforcement

Safety was evaluated by testing inputs that request:
- Medical advice
- Treatment recommendations
- Diagnostic guidance

Expected behavior:
- A deterministic safety gate overrides all other flows to ensure safety
- A prompt safety restrictions in case the sagery gate fails 
- The agent provides a refusal with a neutral, factual redirection
- The agent does not continue or resume the original flow after refusal

This ensures compliance with the constraint that the agent provides factual information only and does not act as a medical advisor.

### Robustness and User Control

Robustness was evaluated by testing non-ideal user behavior, including:
- Provides a request with necessary missing information
- Changing topics mid-flow
- Providing irrelevant responses when a slot is requested
- Canceling an ongoing interaction
- Responding with small talk instead of requested information

Expected behavior:
- The agent does not get stuck in a flow
- The agent allows topic switching when appropriate
- The flow state resets cleanly when the user cancels or changes intent

This verifies that the agent maintains conversational flexibility without losing control of its internal logic.

---

### LLM Roles and Tool Usage

The role of the LLM was evaluated to ensure it is used only for:
- Intent routing
- Entity extraction (medications etc.)
- Natural language phrasing

Deterministic tools were evaluated to ensure they propperly handle:
- Medication resolution
- Branch resolution
- Stock lookup
- Prescription verification

Expected behavior:
- All factual decisions are grounded in tool outputs
- The LLM does not invent medication data, availability, or prescription status
- Ambiguous tool results trigger clarification rather than inference

The tracing panel was used to confirm correct sequencing of LLM calls and tool invocations.

---

## Evidence Mapping

The following screenshots provide evidence of the evaluation:

- **Screenshot 1:** 
  [Medication information flow with small talk start](evidence_screenshots/med_not_found_and_change.png).

  Demonstrates correct intent detection, small talk reply, re-routing, clarification question, entity extraction, tool grounding, and response rendering.

- **Screenshot 2:**  [Stock availability flow with missing slot and meical advice request](evidence_screenshots/stock_availiability_and_advice_refusal.png).

  Demonstrates multi-step slot collection, flow continuation and flow safety cacelation.

- **Screenshot 3:** 
  [Prescription information flow with language change small talk](evidence_screenshots/rx_small_talk_lang_change.png).

  Demonstrates correct intent detection, multi-step flow collection, response rendering and adaptive language change.



---

## Future Evaluation Before Real Deployment (Optional)

Before real-world deployment, additional evaluation would be required, including:
- Automated testing of edge cases and adversarial prompts
- Intent detection accuracy
- Database lookup accuracy and F1 to minimize false positive and false negative matches
- Safety gate refusal rates with ambigous inputs
- Auditing of hallucination risks
- User experience testing with non-technical users
- Load and latency testing under concurrent usage


These evaluations are outside the scope of the current demo but would be necessary for production readiness.