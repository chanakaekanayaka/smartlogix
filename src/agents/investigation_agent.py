"""
Investigation Agent - the reasoning core (Agent 2 of 4).

Looks up the order's actual operational records (tracking status, warehouse
packaging label, courier track record) and asks the LLM to reason about who
is most likely at fault. The LLM is explicitly told to use ONLY the evidence
it is given, and to say "unclear" rather than guess - this is what the
Responsible AI / bias assessment (Student 3) will check: does the stated
reasoning actually match evidence_used, or does the model hallucinate facts
that aren't in the data?
"""

import pandas as pd

from src.config import DATA_DIR, INVESTIGATION_CONFIDENCE_THRESHOLD
from src.llm import call_llm_json
from src.utils.logger import log_agent_event
from src.agents.schemas import IntakeOutput, InvestigationOutput

_orders_df = None
_couriers_df = None
_inventory_df = None


def _load_data():
    global _orders_df, _couriers_df, _inventory_df
    if _orders_df is None:
        _orders_df = pd.read_csv(DATA_DIR / "orders.csv")
    if _couriers_df is None:
        _couriers_df = pd.read_csv(DATA_DIR / "couriers.csv")
    if _inventory_df is None:
        _inventory_df = pd.read_csv(DATA_DIR / "inventory.csv")
    return _orders_df, _couriers_df, _inventory_df


SYSTEM_PROMPT = """You are the Investigation Agent of a Sri Lankan logistics
assistant. You are given structured evidence about one delivery order. Decide
who is most likely at fault using ONLY the evidence provided - never invent
facts that are not present.

Rule of thumb: if item_requires_fragile_packaging is true and packaging_label
is not "Fragile", that is strong evidence of a warehouse packaging fault. If
packaging was correct but the courier has a high past_damage_count, that
points to a courier fault. If weather_flag is true, consider weather. If none
of these clearly apply, say "unclear".

Return ONLY a JSON object with keys:
likely_fault (one of "courier", "warehouse", "customer", "weather", "unclear"),
confidence (a number between 0 and 1),
reasoning (one or two sentences, referencing only the given evidence fields)."""


def run_investigation_agent(intake: IntakeOutput, session_id: str) -> InvestigationOutput:
    orders_df, couriers_df, inventory_df = _load_data()

    if not intake.order_id:
        return InvestigationOutput(order_found=False, likely_fault="unclear",
                                    confidence=0.0, reasoning="No order ID provided.")

    match = orders_df[orders_df["order_id"] == intake.order_id]
    if match.empty:
        log_agent_event("investigation_agent", "order_not_found",
                         {"order_id": intake.order_id}, session_id=session_id)
        return InvestigationOutput(order_id=intake.order_id, order_found=False,
                                    likely_fault="unclear", confidence=0.0,
                                    reasoning="Order ID not found in tracking records.")

    order = match.iloc[0].to_dict()
    courier_match = couriers_df[couriers_df["courier_id"] == order["courier_id"]]
    courier = courier_match.iloc[0].to_dict() if not courier_match.empty else {}
    item_match = inventory_df[inventory_df["item_id"] == order["item_id"]]
    item_requires_fragile = bool(item_match.iloc[0]["fragile"]) if not item_match.empty else False

    evidence = {
        "order_status": order.get("status"),
        "packaging_label": order.get("packaging_label"),
        "item_requires_fragile_packaging": item_requires_fragile,
        "weather_flag": bool(order.get("weather_flag")),
        "courier_past_delay_count": courier.get("past_delay_count"),
        "courier_past_damage_count": courier.get("past_damage_count"),
        "courier_rating": courier.get("rating"),
    }

    result = call_llm_json(SYSTEM_PROMPT, str(evidence))

    log_agent_event("investigation_agent", "fault_determination",
                     {"order_id": intake.order_id, "evidence": evidence, "llm_result": result},
                     session_id=session_id)

    if result.get("parse_error"):
        return InvestigationOutput(order_id=intake.order_id, order_found=True,
                                    likely_fault="unclear", confidence=0.0,
                                    reasoning="Could not determine fault automatically.",
                                    evidence_used=evidence)

    confidence = float(result.get("confidence", 0.0))
    fault = result.get("likely_fault", "unclear")
    if confidence < INVESTIGATION_CONFIDENCE_THRESHOLD:
        fault = "unclear"

    return InvestigationOutput(
        order_id=intake.order_id,
        order_found=True,
        likely_fault=fault,
        confidence=confidence,
        reasoning=result.get("reasoning"),
        evidence_used=evidence,
        customer_phone=str(order.get("customer_phone", "")),
    )
