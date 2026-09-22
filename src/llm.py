"""
Thin wrapper around the Groq LLM client shared by all agents.

Centralising this in one place means every agent uses the same model,
timeout, and logging behaviour, and it's the one function the "Prompt
Injection" assessment needs to understand to trace how user text reaches
the model.
"""

import json

from groq import Groq

from src.config import GROQ_API_KEY, GROQ_MODEL

_client = Groq(api_key=GROQ_API_KEY)


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


def call_llm_json(system_prompt: str, user_prompt: str) -> dict:
    """Calls the LLM expecting strict JSON back; falls back to an error dict on parse failure."""
    raw = call_llm(system_prompt, user_prompt, json_mode=True)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"parse_error": True, "raw_response": raw}
