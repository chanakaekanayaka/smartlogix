"""
Resolution Agent - decides the outcome and writes the final reply (Agent 4 of 4,
also acts as the Coordinator's composition step).

Deliberate design choice: the money-affecting decision (refund / no refund /
escalate) is made by a plain deterministic rule table, NOT by the LLM. The
LLM's only job here is to explain that decision in clear language. This
keeps financial outcomes consistent and auditable (Responsible AI: fairness +
explainability) and removes the LLM's ability to hallucinate a refund amount.
"""

from src.llm import call_llm
from src.utils.logger import log_agent_event
from src.security.encryption import encrypt_field
from src.agents.schemas import IntakeOutput, InvestigationOutput, PolicyOutput, ResolutionOutput

# fault -> (action, escalate)
FAULT_ACTION_TABLE = {
    "warehouse": ("full_refund", False),
    "courier": ("full_refund", False),
    "customer": ("no_refund", False),
    "weather": ("partial_refund", False),
    "unclear": ("escalated_to_human", True),
}

SYSTEM_PROMPT = """You are the Resolution Agent of a Sri Lankan logistics
assistant, writing the final reply to a customer. Be clear, polite, and
transparent: state what was decided, why (based on the investigation and
policy given to you), and flag that estimates are approximate where relevant.
Do not invent policy details that were not given to you. Keep it under 120 words."""


def run_resolution_agent(
    intake: IntakeOutput,
    investigation: InvestigationOutput,
    policy: PolicyOutput,
    session_id: str,
) -> ResolutionOutput:

    if intake.issue_type == "policy_question":
        action, escalate = "information_only", False
    else:
        action, escalate = FAULT_ACTION_TABLE.get(
            investigation.likely_fault or "unclear", ("escalated_to_human", True)
        )

    context = (
        f"Customer issue summary: {intake.summary}\n"
        f"Investigation finding: fault={investigation.likely_fault}, "
        f"confidence={investigation.confidence}, reasoning={investigation.reasoning}\n"
        f"Relevant policy: {policy.answer}\n"
        f"Decided action: {action}"
    )

    final_answer = call_llm(SYSTEM_PROMPT, context, temperature=0.4)

    # Customer phone is encrypted before it ever touches the audit log -
    # this is the Resolution Agent's privacy responsibility.
    log_agent_event(
        "resolution_agent", "final_decision",
        {
            "order_id": intake.order_id,
            "action": action,
            "escalate_to_human": escalate,
            "customer_phone_encrypted": encrypt_field(investigation.customer_phone) if investigation.customer_phone else None,
            "final_answer": final_answer,
        },
        session_id=session_id,
    )

    return ResolutionOutput(action=action, escalate_to_human=escalate, final_answer=final_answer)
