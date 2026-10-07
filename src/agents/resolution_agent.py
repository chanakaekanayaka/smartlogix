"""
Resolution Agent - decides the outcome and writes the final reply (Agent 4 of 4,
also acts as the Coordinator's composition step).

Deliberate design choice: the money-affecting decision (refund / no refund /
escalate) is made by a plain deterministic rule table keyed on BOTH the issue
type and the fault (src/agents/decision_rules.py), NOT by the LLM. The LLM's
only job here is to explain that decision in clear language, and its reply is
checked against the decision before it is sent - if it contradicts the
decision (e.g. promises a full refund when the policy gives 50%), the
deterministic template reply is sent instead. This keeps financial outcomes
consistent and auditable (Responsible AI: fairness + explainability).
"""

from src.llm import call_llm
from src.utils.logger import log_agent_event
from src.security.encryption import encrypt_field
from src.agents.decision_rules import (
    check_reply_consistency, decide, decision_statement, template_reply,
)
from src.agents.schemas import IntakeOutput, InvestigationOutput, PolicyOutput, ResolutionOutput

SYSTEM_PROMPT = """You are the Resolution Agent of a Sri Lankan logistics
assistant, writing the final reply to a customer. Be clear, polite, and
transparent: say what the investigation found and state the decision.

The decision has already been made and is final. Restate the DECISION
sentence faithfully. Do NOT mention any other refund type, percentage,
amount, replacement or timeline than the ones in the DECISION sentence, and
do not speculate about delivery dates. Do not invent policy details.
Keep it under 120 words."""


def run_resolution_agent(
    intake: IntakeOutput,
    investigation: InvestigationOutput,
    policy: PolicyOutput,
    session_id: str,
) -> ResolutionOutput:

    decision = decide(intake.issue_type, investigation.likely_fault)
    statement = decision_statement(intake.issue_type, decision)

    # Only the decided outcome and the policy *names* go to the LLM - not the
    # retrieved policy text, which lists every possible outcome and is what
    # previously led the LLM to promise a different refund than was decided.
    context = (
        f"Customer issue: {intake.issue_type} - {intake.summary}\n"
        f"Order ID: {intake.order_id}\n"
        f"Investigation finding: fault={investigation.likely_fault}, "
        f"reasoning={investigation.reasoning}\n"
        f"Policy basis: {decision.policy_basis}\n"
        f"Policy sources: {', '.join(policy.sources) or 'none'}\n"
        f"DECISION: {statement}"
    )

    reply_source = "llm"
    problems: list[str] = []
    try:
        final_answer = call_llm(SYSTEM_PROMPT, context, temperature=0.3)
        problems = check_reply_consistency(decision.action, intake.issue_type, final_answer)
    except Exception as e:  # network / rate-limit errors must not leave the customer without a reply
        final_answer = ""
        problems = [f"llm_error: {type(e).__name__}"]

    if problems:
        log_agent_event("resolution_agent", "reply_consistency_fallback",
                        {"order_id": intake.order_id, "action": decision.action,
                         "problems": problems, "rejected_reply": final_answer},
                        session_id=session_id)
        final_answer = template_reply(intake.order_id, intake.issue_type,
                                      investigation.likely_fault, decision)
        reply_source = "template"

    # Customer phone is encrypted before it ever touches the audit log -
    # this is the Resolution Agent's privacy responsibility.
    log_agent_event(
        "resolution_agent", "final_decision",
        {
            "order_id": intake.order_id,
            "issue_type": intake.issue_type,
            "likely_fault": investigation.likely_fault,
            "action": decision.action,
            "escalate_to_human": decision.escalate_to_human,
            "policy_basis": decision.policy_basis,
            "reply_source": reply_source,
            "customer_phone_encrypted": encrypt_field(investigation.customer_phone) if investigation.customer_phone else None,
            "final_answer": final_answer,
        },
        session_id=session_id,
    )

    return ResolutionOutput(
        action=decision.action,
        escalate_to_human=decision.escalate_to_human,
        final_answer=final_answer,
        policy_basis=decision.policy_basis,
        reply_source=reply_source,
    )
