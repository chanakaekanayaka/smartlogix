"""
The JSON message contract every agent uses to talk to the next one.

This is the documented "agent communication protocol" for the group
assignment: every agent takes a typed input and returns a typed output
built on this contract, and the Policy Agent additionally speaks it over
HTTP (see src/policy_service/main.py) instead of an in-process call.
"""

from typing import Literal, Optional
from pydantic import BaseModel


class IntakeOutput(BaseModel):
    status: Literal["ok", "blocked"]
    order_id: Optional[str] = None
    issue_type: Optional[Literal[
        "damaged", "late", "lost", "wrong_address",
        "policy_question", "new_quote", "other"
    ]] = None
    origin_city: Optional[str] = None
    destination_city: Optional[str] = None
    item: Optional[str] = None
    urgency: Optional[Literal["low", "medium", "high"]] = None
    sentiment: Optional[Literal["negative", "neutral", "positive"]] = None
    summary: Optional[str] = None
    block_reason: Optional[str] = None


class InvestigationOutput(BaseModel):
    order_id: Optional[str] = None
    order_found: bool
    likely_fault: Optional[Literal[
        "courier", "warehouse", "customer", "weather", "unclear"
    ]] = None
    confidence: float = 0.0
    reasoning: Optional[str] = None
    evidence_used: dict = {}
    # Carried through the pipeline for encryption/logging only - deliberately
    # NOT included in evidence_used, so it is never sent to the LLM.
    customer_phone: Optional[str] = None


class PolicyOutput(BaseModel):
    answer: str
    sources: list[str]
    chunks: list[str]


class ResolutionOutput(BaseModel):
    action: Literal[
        "full_refund", "partial_refund", "no_refund",
        "escalated_to_human", "information_only"
    ]
    escalate_to_human: bool
    final_answer: str
