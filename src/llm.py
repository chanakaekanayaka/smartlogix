"""
Thin wrapper around the Groq LLM client shared by all agents.

Centralising this in one place means every agent uses the same model,
timeout, and logging behaviour, and it's the one function the "Prompt
Injection" assessment needs to understand to trace how user text reaches
the model.
"""

import json

from groq import BadRequestError, Groq

from src.config import GROQ_API_KEY, GROQ_MODEL

# The SDK retries 429 / 5xx / connection errors with exponential backoff
# (honouring Retry-After); the free Groq tier rate-limits quickly, so allow
# more retries than the default 2.
_client = Groq(api_key=GROQ_API_KEY, max_retries=5, timeout=60)


def call_llm(system_prompt: str, user_prompt: str, json_mode: bool = False, temperature: float = 0.2) -> str:
    """Sends one chat completion request to Groq and returns the text content."""
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = _client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=800,
        **kwargs,
    )
    return response.choices[0].message.content


def call_llm_json(system_prompt: str, user_prompt: str, attempts: int = 2) -> dict:
    """Calls the LLM expecting strict JSON back; falls back to an error dict on parse failure.

    Groq's JSON mode occasionally rejects its own generation with a 400
    "json_validate_failed" - that is a transient model failure, not a bad
    request, so it is retried and then reported as a parse error instead of
    crashing the agent.
    """
    raw = None
    for _ in range(attempts):
        try:
            raw = call_llm(system_prompt, user_prompt, json_mode=True)
        except BadRequestError as e:
            if "json_validate_failed" not in str(e):
                raise
            continue
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
    return {"parse_error": True, "raw_response": raw}
