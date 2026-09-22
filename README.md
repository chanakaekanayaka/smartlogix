# SmartLogix - Agentic AI Delivery Exception & Resolution Assistant

A multi-agent AI assistant for a Sri Lankan logistics/courier business. Customers
describe a delivery issue or ask a policy question in plain English; four agents
work together to investigate what happened, retrieve the relevant policy, decide
a resolution, and reply with a clear, evidence-based explanation.

Built for IT3041 (Information Retrieval and Web Analytics) - Group Assignment.

## Architecture

```
Customer Message
      |
      v
[1] Intake Agent  ---- auth + input sanitize -> NLP (spaCy NER) + LLM -> structured request
      |
      +-----------------+
      v                 v
[2] Investigation      [3] Policy Agent (IR / RAG)
    Agent                   - separate FastAPI microservice
    (fault reasoning)       - ChromaDB vector search over policy docs
      |                 |
      +--------+--------+
               v
      [4] Resolution Agent (Coordinator)
               |
               v
      Final answer (explained) -> Customer
```

| Agent | File | Responsibility |
|---|---|---|
| Intake Agent | `src/agents/intake_agent.py` | Input sanitization, spaCy NER, LLM extraction of order id / issue type / entities |
| Investigation Agent | `src/agents/investigation_agent.py` | Looks up order/courier records, LLM reasoning over evidence to determine fault |
| Policy Agent (IR/RAG) | `src/policy_service/` | Own FastAPI microservice; ChromaDB + RAG retrieval over policy documents |
| Resolution Agent | `src/agents/resolution_agent.py` | Deterministic rule table decides the outcome; LLM writes the explanation |

Agents pass typed JSON messages defined in `src/agents/schemas.py`. The Policy
Agent is called over a real HTTP API (`POST /retrieve`, API-key authenticated)
rather than an in-process function call - this is the system's concrete
agent-to-agent communication protocol.

## Setup

1. Create and activate a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate        (Windows)
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   ```
3. Copy `.env.example` to `.env` and add your free Groq API key from
   https://console.groq.com (everything else in `.env` is generated
   automatically the first time the app runs).
4. Generate the synthetic Sri Lanka dataset:
   ```
   python data/generate_data.py
   ```
5. Build the policy knowledge base (RAG index):
   ```
   python -m src.policy_service.ingest
   ```
6. Start the Policy Agent microservice (keep this terminal open):
   ```
   uvicorn src.policy_service.main:app --port 8002
   ```
7. In a second terminal, start the app:
   ```
   python app.py
   ```
8. Open http://localhost:8080 and log in with the demo account: `demo` / `Demo@123`

## Data

All data in `data/` is synthetically generated (`data/generate_data.py`, fixed
random seed for reproducibility) - there is no real courier company data
behind this project. Policy documents in `data/policies/` are original text
written for this assignment.

## Security features

- JWT-based session authentication, bcrypt password hashing (`src/security/auth.py`)
- Input sanitization / prompt-injection pattern filter (`src/security/sanitize.py`)
- Fernet field-level encryption for stored customer PII (`src/security/encryption.py`)
- API-key authentication + basic rate limiting on the Policy Agent microservice
- Structured audit logging of every agent decision (`src/utils/logger.py`, `logs/agent_activity.log`)

## Responsible AI

- **Explainability**: every resolution states the reasoning behind it, grounded in the actual evidence looked up.
- **Fairness**: the refund/action decision is made by a fixed rule table applied identically to every case, not an LLM guess.
- **Transparency**: cost breakdowns and policy sources are shown, not just a final number.
- **Safety**: low-confidence fault determinations are escalated to a human instead of an automatic decision.
- **Privacy**: customer phone numbers are encrypted before being written to logs.
- **Domain risk**: all estimates and the final answer are approximate and clearly flagged as such.

## Relationship to the Individual Vulnerability Assessment assignment

Each of the 4 agents is the natural target for one of the 4 individual
specializations, so the same running system supports both assignments without
changes:

| Individual specialization | Tests this agent | Why |
|---|---|---|
| Prompt Injection & Jailbreak | Intake Agent | First point where raw user text reaches an LLM |
| Privacy & Data Leakage | Resolution Agent (+ auth) | Encryption, session memory, login |
| Responsible AI & Bias | Investigation Agent | Makes the judgment call; check reasoning vs. evidence_used for hallucination/bias |
| Information Retrieval & Security | Policy Agent | Own FastAPI service - retrieval accuracy, API auth, rate limiting |

`logs/agent_activity.log` records every agent call as a JSON line - use it as
evidence (screenshots/log excerpts) in the individual vulnerability report.

## Project structure

```
data/                  synthetic datasets + policy documents + generator script
src/config.py           env/secrets loading
src/llm.py              shared Groq client wrapper
src/security/           auth, input sanitization, encryption
src/utils/               logging, distance/cost calculation
src/agents/              Intake, Investigation, Resolution agents + shared schemas
src/policy_service/      Policy Agent FastAPI microservice + RAG pipeline
src/coordinator.py       orchestrates the 4-agent pipeline + session memory
app.py                   NiceGUI web UI
```

## Contributors

- (add team member names and which agent each owned)
