"""
Intake Agent - the first stop for every customer message.

Responsibilities (Agent 1 of 4):
1. Security gate: sanitize the raw text and refuse to process it further if
   it looks like a prompt-injection / jailbreak attempt.
2. NLP: run spaCy NER over the message as a lightweight, non-LLM signal.
3. LLM: ask Groq to turn the free-text message into the structured
   IntakeOutput fields (order id, issue type, cities, item, urgency,
   sentiment, a one-line summary).
"""

import spacy

from src.llm import call_llm_json
from src.security.sanitize import sanitize_input
from src.utils.logger import log_agent_event
from src.agents.schemas import IntakeOutput

_nlp = spacy.load("en_core_web_sm")

SYSTEM_PROMPT = """You are the Intake Agent of a Sri Lankan logistics assistant.
Extract structured facts from the customer's message and return ONLY a JSON
object with these exact keys:
order_id (string like "ORD10001" or null if none mentioned),
issue_type (one of: "damaged", "late", "lost", "wrong_address",
"policy_question", "new_quote", "other"),
origin_city (string or null), destination_city (string or null),
item (string or null), urgency ("low", "medium", or "high"),
sentiment ("negative", "neutral", or "positive"),
summary (one short sentence summarising the request).
Only use information present in the message. Do not invent an order ID."""


def run_intake_agent(raw_text: str, session_id: str) -> IntakeOutput:
    clean_text, is_suspicious, reasons = sanitize_input(raw_text)

    if is_suspicious:
        log_agent_event(
            "intake_agent", "blocked_suspicious_input",
            {"raw_text": raw_text, "matched_patterns": reasons},
            session_id=session_id,
        )
        return IntakeOutput(
            status="blocked",
            block_reason="Message matched a prompt-injection pattern and was not processed.",
        )

    # NER pass - independent of the LLM, used mainly to log candidate
    # entities and as a NLP-technique building block the report can point to.
    doc = _nlp(clean_text)
    entities = [{"text": ent.text, "label": ent.label_} for ent in doc.ents]

    extracted = call_llm_json(SYSTEM_PROMPT, clean_text)

    log_agent_event(
        "intake_agent", "parsed_message",
        {"clean_text": clean_text, "ner_entities": entities, "llm_extraction": extracted},
        session_id=session_id,
    )

    if extracted.get("parse_error"):
        return IntakeOutput(status="ok", issue_type="other", summary=clean_text[:150])

    return IntakeOutput(
        status="ok",
        order_id=extracted.get("order_id"),
        issue_type=extracted.get("issue_type", "other"),
        origin_city=extracted.get("origin_city"),
        destination_city=extracted.get("destination_city"),
        item=extracted.get("item"),
        urgency=extracted.get("urgency", "medium"),
        sentiment=extracted.get("sentiment", "neutral"),
        summary=extracted.get("summary"),
    )
