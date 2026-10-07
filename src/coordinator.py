"""
Coordinator - wires the 4 agents together into one request/response cycle
and keeps a small per-session conversation memory.

Flow: Intake -> (Investigation + Policy) -> Resolution
The Policy Agent is called over HTTP (it's a separate FastAPI process);
every other agent is an in-process call using the same typed schema either
way (see src/agents/schemas.py).
"""

from datetime import datetime
from typing import Callable, Optional

import requests

from src.config import POLICY_SERVICE_URL, POLICY_API_KEY
from src.security.auth import verify_access_token
from src.utils.logger import log_agent_event
from src.agents.intake_agent import run_intake_agent
from src.agents.investigation_agent import run_investigation_agent
from src.agents.resolution_agent import run_resolution_agent
from src.agents.schemas import PolicyOutput

# Per-session in-memory history: {session_id: [ {role, text}, ... ]}
# Deliberately keyed by session_id so one user's history can never leak into
# another session's context - this is the exact boundary the "Conversation
# Memory Leakage" individual test (Student 2) will try to break.
_session_memory: dict[str, list[dict]] = {}
MAX_MEMORY_TURNS = 10

# Issue-specific retrieval queries - "late refund policy" alone matched the
# refund policy's heading chunk rather than the delay clause.
POLICY_QUERIES = {
    "damaged": "refund for item damaged in delivery, warehouse packaging or courier fault",
    "late": "refund when delivery is delayed more than 48 hours",
    "lost": "refund when parcel is lost in transit",
    "wrong_address": "refund when parcel is delivered to the wrong address",
}


def call_policy_agent(query: str, session_id: str = "-") -> PolicyOutput:
    """Public entry point to the Policy Agent (IR/RAG) - used internally by
    handle_request(), and also called directly by the UI's Help Center
    page so the RAG pipeline can be demoed/tested on its own, without going
    through the full exception-resolution flow."""
    return _call_policy_agent(query, session_id)


def _call_policy_agent(query: str, session_id: str) -> PolicyOutput:
    try:
        resp = requests.post(
            f"{POLICY_SERVICE_URL}/retrieve",
            json={"query": query, "session_id": session_id},
            headers={"X-API-Key": POLICY_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return PolicyOutput(**data)
    except requests.RequestException as e:
        return PolicyOutput(answer=f"Policy service unavailable: {e}", sources=[], chunks=[])


def handle_request(
    raw_text: str,
    session_id: str,
    auth_token: str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    on_progress, if given, is called with a short human-readable label each
    time the pipeline moves to the next agent - purely cosmetic (lets the UI
    show a live "Investigating... -> Checking policy... -> Deciding..." trail
    instead of a plain spinner). The pipeline logic itself never depends on
    it running.
    """
    def progress(stage: str) -> None:
        if on_progress:
            on_progress(stage)

    username = verify_access_token(auth_token)
    if not username:
        return {"error": "unauthorized", "final_answer": "Please log in again."}

    trace = {}

    progress("Reading your message...")
    intake = run_intake_agent(raw_text, session_id)
    trace["intake"] = intake.model_dump()

    if intake.status == "blocked":
        final_answer = "Sorry, that message could not be processed. Please rephrase your request."
        _append_memory(session_id, raw_text, final_answer)
        return {"final_answer": final_answer, "trace": trace}

    if intake.issue_type == "policy_question":
        # Policy questions are intentionally NOT answered here. The chat's
        # job is exception handling (damaged/late/lost orders); general
        # policy lookups are redirected to the dedicated Help Center page
        # so the Policy/IR agent has one clear, demoable entry point.
        final_answer = (
            "That looks like a policy question rather than a delivery issue. "
            "Please use the **Help Center** page to search our policies directly."
        )
        _append_memory(session_id, raw_text, final_answer)
        return {"final_answer": final_answer, "trace": trace, "redirect_to_knowledge": True}

    needs_order_id = intake.issue_type in ("damaged", "late", "lost", "wrong_address")
    if needs_order_id and not intake.order_id:
        # Don't run Investigation/Resolution on a case with nothing to
        # investigate - that produced a confusing "escalated to a human"
        # message for what's really just a missing order ID. Ask for it
        # directly instead, like a normal conversation would.
        final_answer = (
            "Could you share your order ID (e.g. ORD10017) so I can look into this for you?"
        )
        _append_memory(session_id, raw_text, final_answer)
        return {"final_answer": final_answer, "trace": trace}

    progress("Investigating order records...")
    investigation = run_investigation_agent(intake, session_id)
    trace["investigation"] = investigation.model_dump()

    progress("Checking applicable policy...")
    policy_query = POLICY_QUERIES.get(intake.issue_type, f"{intake.issue_type} refund policy")
    policy = _call_policy_agent(policy_query, session_id)
    trace["policy"] = policy.model_dump()

    progress("Deciding the resolution...")
    resolution = run_resolution_agent(intake, investigation, policy, session_id)
    trace["resolution"] = resolution.model_dump()

    log_agent_event("coordinator", "request_completed",
                     {"username": username, "action": resolution.action}, session_id=session_id)

    _append_memory(session_id, raw_text, resolution.final_answer)
    return {
        "final_answer": resolution.final_answer,
        "trace": trace,
        "action": resolution.action,
        "escalate_to_human": resolution.escalate_to_human,
    }


def _append_memory(session_id: str, user_text: str, assistant_text: str) -> None:
    now = datetime.now().strftime("%H:%M")
    history = _session_memory.setdefault(session_id, [])
    history.append({"role": "user", "text": user_text, "timestamp": now})
    history.append({"role": "assistant", "text": assistant_text, "timestamp": now})
    del history[:-MAX_MEMORY_TURNS * 2]


def get_session_history(session_id: str) -> list[dict]:
    return _session_memory.get(session_id, [])
