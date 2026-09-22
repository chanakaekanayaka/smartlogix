"""
Structured audit logging for every agent action.

Each call appends one JSON line to logs/agent_activity.log. This is the
built-in evidence trail: it doubles as the explainability record for the
group assignment and as the screenshot/log evidence the individual
vulnerability-assessment report requires for every test case.
"""

import json
import datetime
from pathlib import Path

from src.config import LOG_DIR

LOG_FILE = LOG_DIR / "agent_activity.log"


def log_agent_event(agent_name: str, event_type: str, payload: dict, session_id: str = "-") -> dict:
    """Writes one structured log entry and returns it (so the UI can also show it)."""
    entry = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "session_id": session_id,
        "agent": agent_name,
        "event": event_type,
        "payload": payload,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def read_recent_events(limit: int = 50) -> list[dict]:
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    entries = [json.loads(line) for line in lines[-limit:]]
    return entries
