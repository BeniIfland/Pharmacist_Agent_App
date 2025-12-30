# AI-powered pharmacist assistant App by Beni Ifland Repository

An LLM-based bilingual AI assistant for a retail pharmacy chain that is capable of providing factual information about medications, stock availability, prescriptions etc, based on data from the pharmacy's internal systems (synthetic database in this case).
The agent complies with strict restrictions not to provide medical advice and has corresponding safety mechanisms.

The project demonstrates the combination of LLM routing and verbalization with deterministic flows and tools (e.g. database lookups), which creates user-safe multi-step assistance flows. The agent is stateless meaning the server keeps no session memory, and the client (UI) sends the flow's state on each request and receives updated flow states back. Implemented using OpenAI API without dedicated agentic frameworks.

---
### Key Features

- Multi-step medical information assistance flows.
- LLM-based intent routing.
- Safety mechanisms to prevent supplying medical advices.
- Deterministic flows with exit and re-routing mechanisms.
- LLM streaming and tool call visibility for UX and transparency.
- Bilingual support for Hebrew/English with the ability to switch language each message.
- Clarification mechanisms for partial user inputs and missing information.
- Simple and aesthetic user interface implemented with Gradio.

---
### Multi-step flows:
All flows include intermediate clarification steps for missing or ambiguous information and re-routing based on user intents.
1. **Med info flow:** collects a medication name from the user, performs a deterministic lookup in the
    synthetic DB, and streams back factual medication information.

    Flow steps: extract_med_name → lookup → reply 

2. **Stock check flow:** collects a medication name and a branch name, resolves each to a canonical record
    via deterministic lookup tools, and queries branch stock status for that medication.

    Flow steps: collect → resolve_med → resolve_branch → stock → reply

3. **Prescription verification flow:** verify a single prescription by rx_id *or* list prescriptions for a user by user_id.

    Flow steps: collect → verify_rx OR list_user_rx → reply

4. **Small talk fallback flow:** all other behavior except from the flows mentioned above is redirected to a safety restricted small talk contextual responses.
---

### Agent tools:

1. `get_medication_by_name` - Resolves a user-provided medication name to a single medication record
    from the synthetic database, with explicit match metadata.
2. `get_branch_by_name` - Resolves a user-provided pharmacy branch name to a single branch record
    from the synthetic database.
3. `get_stock` - Resolves the stock availability of a specific medication at a specific
    pharmacy branch using a deterministic lookup.
4. `verify_prescription` - Resolves and validates a prescription record using a deterministic lookup.

5. `get_prescriptions_for_user` - Resolves and lists all prescriptions associated with a specific user ID
    using a deterministic lookup while also validating perscription validity (date-wise).

6. `detect_intent_llm` - Classifies the user's latest message into a single supported flow using
    an LLM-based router.

---
### Project Architecture
- `orchestrator.py` - stateless routing of user messages and managing multi-step flows
- `llm.py` - llm verbalization and streaming, and predefined policy message rendering
- `tools.py` - a set of deterministic functions the agent uses
- `ui.py` simple Gradio-based user interface for demonstration
- `safety.py` - safety mechanisms to avoid medical advices and re-routing user messages
- `simple_detecrots.py` - deterministic information extraction mechaisms
- `db.py` - synthetic database and indices

---
### Tech requirments
- Python 
- OpenAI API
- Pydantic
- Gradio
- Docker

--- 
### Quick Start Through Docker

1. Build the Docker image from the repo:

```
docker build -t pharmacist-agent .
```

2. Run the Docker container and pass your `OPENAI_API_KEY`:

```
docker run --rm -p 7860:7860 -e OPENAI_API_KEY="sk-..." pharmacist-agent
```

3. Open the UI with `http://localhost:7860` in your browser.
---

### User journeys demonstration and evaluation plan

- Evidence screenshots are provided in [Evidence Screenshots](evidence_screenshots).

- Demo multi-step flows and user inputs with expected behavior are depicted in [Demo Journeys](demo_inputs.md).

- Evaluation plan is described in [Evaluation Plan](evaluation_plan.md).

