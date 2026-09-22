"""
Input sanitization and a lightweight prompt-injection filter.

This is the piece the "Prompt Injection and Jailbreak" individual
assessment (Student 1's specialization) will red-team directly - it's a
keyword/pattern filter, not a trained guardrail model, so it WILL have real
gaps. That's expected: the individual report documents which attacks it
catches and which it misses.
"""

import re

from src.config import MAX_INPUT_LENGTH

# Phrases commonly used to try to override a system prompt or extract it.
SUSPICIOUS_PATTERNS = [
    r"ignore (all|any|the)? ?(previous|above|prior) instructions",
    r"disregard (all|any|the)? ?(previous|above|prior) instructions",
    r"you are now",
    r"act as (a |an )?(?!courier|customer)",
    r"reveal (your|the) (system prompt|instructions)",
    r"what (is|are) your (system prompt|instructions)",
    r"pretend (you are|to be)",
    r"jailbreak",
    r"do anything now",
    r"override (your|the) rules",
    r"give (me )?(full |admin )?access",
    r"<script",
    r"drop table",
    r"--\s*$",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in SUSPICIOUS_PATTERNS]


def sanitize_input(raw_text: str) -> tuple[str, bool, list[str]]:
    """
    Returns (clean_text, is_suspicious, matched_reasons).

    clean_text is length-capped and stripped of control characters.
    is_suspicious=True means the Intake Agent should refuse to act on the
    message and log the attempt rather than passing it to the LLM.
    """
    text = raw_text.strip()[:MAX_INPUT_LENGTH]
    # Strip non-printable control characters (keep normal whitespace).
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t ")

    matched_reasons = []
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            matched_reasons.append(pattern.pattern)

    return text, len(matched_reasons) > 0, matched_reasons
