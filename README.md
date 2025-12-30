# AI-powered pharmacist assistant App by Beni Ifland Repository

An LLM-based bilingual AI assistant for a retail pharmacy chain that is capable of providing factual information about medications, stock availability, prescriptions etc, based on data from the pharmacy's internal systems (synthetic database in this case).
The agent complies with strict restrictions not to provide medical advice and has corresponding safety mechanisms.

The project demonstrates the combination of LLM routing and verbalization with deterministic flows and tools (e.g. database lookups), which creates user-safe multi-step assistance flows. The agent is stateless meaning the server keeps no session memory, and the client (UI) sends the flow's state on each request and receives updated flow states back. Implemented using OpenAI API without dedicated agentic framework.

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
### Project Architecture
- orchestrator.py - stateless routing of user messages and managing multi-step flows
- llm.py - llm verbalization and streaming, and policy message rendering
- tools.py - a set of deterministic functions the agent uses
- ui.py simple Gradio interface for demonstration
- safety.py - safety mechanisms to constraint medical advices and re-routing user messages
- simple_detecrots.py - deterministic information extraction mechaisms
- db.py - synthetic database and indices

---
### Tech requirments
- Python 
- OpenAI API
- Pydantic
- Gradio
- Docker

--- 
### Quick Start Through Docker

After installing Docker:
1. Build the Docker image from the repo using:

```
docker build -t pharmacist-agent .
```

2. Run the Docker container and pass your `OPENAI_API_KEY` using:

```
docker run --rm -p 7860:7860 -e OPENAI_API_KEY="sk-..." pharmacist-agent
```

3. Open the UI with `http://localhost:7860` in your browser.
---

### User journeys demonstration and evaluation plan

- Evidence screenshots are provided in [Evidence Screenshots](evidence_screenshots).

- Demo multi-step flows and user inputs with expected behavior are depicted in [Demo Journeys](demo_inputs.md).

- Evaluation plan is described in [Evaluation Plan](evaluation_plan.md).

