"""
Deterministic decision rules for the Resolution Agent - no LLM in this file.

Every money-affecting outcome is looked up here from (issue_type, fault), and
each entry is traceable to a clause in data/policies/. Keeping it as plain
data makes the decision auditable, identical for every customer (fairness),
and unit-testable (tests/test_decision_rules.py).

The module also owns the guard that checks the LLM-written reply actually
states the decided outcome, plus the template reply used when it does not.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    action: str
    escalate_to_human: bool
    policy_basis: str


_ESCALATE = Decision("escalated_to_human", True,
                     "Damage Claims Policy - unclear fault is escalated for manual review")

# (issue_type, likely_fault) -> Decision
DECISION_MATRIX: dict[tuple[str, str], Decision] = {
    # Damage Claims Policy + Refund Policy "Full Refund" / "No Refund"
    ("damaged", "warehouse"): Decision("full_refund", False,
                                       "Damage Claims Policy - warehouse packaging fault"),
    ("damaged", "courier"): Decision("full_refund", False,
                                     "Damage Claims Policy - courier handling fault"),
    ("damaged", "weather"): Decision("no_refund", False,
                                     "Refund Policy - No Refund (severe weather / force majeure)"),
    ("damaged", "customer"): Decision("no_refund", False,
                                      "Refund Policy - No Refund (customer-caused)"),
    ("damaged", "unclear"): Decision("escalated_to_human", True,
                                     "Damage Claims Policy - unclear fault is escalated for manual review"),

    # Refund Policy "Partial Refund (50%)" + Delivery SLA. A delay is an
    # operational issue whoever caused it, so warehouse and courier both map
    # to the 50% delivery-fee refund - never a full refund.
    ("late", "courier"): Decision("partial_refund", False,
                                  "Refund Policy - Partial Refund (50% of delivery fee) for major delay"),
    ("late", "warehouse"): Decision("partial_refund", False,
                                    "Refund Policy - Partial Refund (50% of delivery fee) for major delay"),
    ("late", "weather"): Decision("no_refund", False,
                                  "Delivery SLA - weather delays are excluded from SLA penalties"),
    ("late", "customer"): Decision("no_refund", False,
                                   "Refund Policy - No Refund (customer-caused)"),
    ("late", "unclear"): Decision("escalated_to_human", True,
                                  "Delivery SLA - cause of delay unclear, escalated for manual review"),

    # Refund Policy "Full Refund" - lost in transit / wrong address
    ("lost", "courier"): Decision("full_refund", False,
                                  "Refund Policy - Full Refund (parcel lost in transit)"),
    ("lost", "warehouse"): Decision("full_refund", False,
                                    "Refund Policy - Full Refund (parcel lost in transit)"),
    ("lost", "customer"): Decision("no_refund", False,
                                   "Refund Policy - No Refund (customer-caused)"),
    ("wrong_address", "courier"): Decision("full_refund", False,
                                           "Refund Policy - Full Refund (wrong address, courier error)"),
    ("wrong_address", "warehouse"): Decision("full_refund", False,
                                             "Refund Policy - Full Refund (wrong address, warehouse error)"),
    ("wrong_address", "customer"): Decision("no_refund", False,
                                            "Refund Policy - No Refund (incorrect address provided)"),
}


def decide(issue_type: str | None, likely_fault: str | None) -> Decision:
    """Anything not explicitly covered by policy goes to a human."""
    if issue_type == "policy_question":
        return Decision("information_only", False, "Policy information request")
    return DECISION_MATRIX.get((issue_type or "other", likely_fault or "unclear"), _ESCALATE)


def decision_statement(issue_type: str | None, decision: Decision) -> str:
    """The exact outcome sentence the customer must be told - the LLM is asked
    to restate this, and the template reply uses it verbatim."""
    action = decision.action
    if action == "full_refund":
        extra = (" and a free replacement will be sent if the item is in stock"
                 if issue_type == "damaged" else "")
        return ("You will receive a full refund" + extra +
                ". Refunds are processed within 5-7 working days to your original payment method.")
    if action == "partial_refund":
        return ("You will receive a refund of 50% of the delivery fee. Refunds are processed "
                "within 5-7 working days to your original payment method.")
    if action == "no_refund":
        return "Under our policy, no refund applies in this case."
    if action == "escalated_to_human":
        extra = (" A temporary partial refund of 25% is offered while the review continues."
                 if issue_type == "damaged" else "")
        return ("Your case has been passed to a human support agent for manual review, "
                "and they will contact you with the outcome." + extra)
    return "This is general policy information; no refund decision was needed."


# --- Reply consistency guard -------------------------------------------------

# Phrases that would contradict each action if they appeared in the reply.
_FORBIDDEN = {
    "full_refund": [r"\bpartial refund", r"\b50\s*%", r"\b25\s*%", r"\bno refund"],
    "partial_refund": [r"\bfull refund", r"\b100\s*%", r"\b25\s*%", r"\bno refund",
                       r"free replacement"],
    "no_refund": [r"\bfull refund", r"\bpartial refund", r"\b\d+\s*%", r"free replacement"],
    "escalated_to_human": [r"\bfull refund", r"\b50\s*%", r"\bno refund"],
    "information_only": [],
}

# At least one of these must appear, so the decision is actually stated.
_REQUIRED = {
    "full_refund": [r"\bfull refund"],
    "partial_refund": [r"\b50\s*%"],
    "no_refund": [r"\bno refund", r"not (be )?eligible for a refund", r"not entitled to a refund",
                  r"unable to (offer|issue|provide) a refund"],
    "escalated_to_human": [r"\bhuman", r"support (agent|team)", r"manual review"],
    "information_only": [],
}

_ALLOWED_ESCALATION_25 = re.compile(r"\b25\s*%")

# The only processing time in the Refund Policy is "5-7 working days"; LLMs
# tend to invent their own ("3-5 business days"), so any other range is rejected.
_DAY_RANGE = re.compile(r"\b(\d+)\s*(?:-|to)\s*(\d+)\s*(?:working |business )?days?\b")
_POLICY_PROCESSING_DAYS = ("5", "7")


def _normalise(text: str) -> str:
    # LLMs often emit narrow/no-break spaces and non-ASCII hyphens ("50 %").
    for ch in "   ":
        text = text.replace(ch, " ")
    for ch in "‐‑‒–":
        text = text.replace(ch, "-")
    return text.lower()


def check_reply_consistency(action: str, issue_type: str | None, reply: str) -> list[str]:
    """Returns a list of problems; empty list means the reply matches the decision."""
    text = _normalise(reply or "")
    problems = []
    for pattern in _FORBIDDEN.get(action, []):
        if pattern == r"\b25\s*%" and action == "escalated_to_human":
            continue
        if re.search(pattern, text):
            problems.append(f"contradicting phrase: {pattern}")
    if action == "escalated_to_human" and issue_type != "damaged" and _ALLOWED_ESCALATION_25.search(text):
        problems.append("25% interim refund only applies to damage claims")
    for low, high in _DAY_RANGE.findall(text):
        if (low, high) != _POLICY_PROCESSING_DAYS:
            problems.append(f"timeline {low}-{high} days contradicts the 5-7 working day policy")
    required = _REQUIRED.get(action, [])
    if required and not any(re.search(p, text) for p in required):
        problems.append(f"decision '{action}' not stated")
    return problems


_FAULT_TEXT = {
    "warehouse": "the warehouse packaging record shows an error",
    "courier": "the courier's handling record points to a courier fault",
    "weather": "a severe weather warning affected this delivery",
    "customer": "the issue was caused by details provided on the order",
    "unclear": "the records do not clearly show what went wrong",
}


def template_reply(order_id: str | None, issue_type: str | None,
                   likely_fault: str | None, decision: Decision) -> str:
    """Deterministic fallback reply - always consistent with the decision."""
    order_part = f" for order {order_id}" if order_id else ""
    issue = (issue_type or "delivery").replace("_", " ")
    finding = _FAULT_TEXT.get(likely_fault or "unclear", _FAULT_TEXT["unclear"])
    return (
        f"Thank you for reporting the {issue} issue{order_part}. "
        f"We reviewed the order records and found that {finding}.\n\n"
        f"{decision_statement(issue_type, decision)}\n\n"
        f"This decision follows our {decision.policy_basis}. "
        "If you think something is missing from our records, reply here and a "
        "support agent will take another look."
    )
