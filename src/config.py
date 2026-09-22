"""
Central configuration. Loads secrets from .env and auto-generates the ones
that don't need to be picked by a human (JWT signing secret, encryption key,
internal service API key) so a new team member only has to supply the Groq
API key to get the whole system running.
"""

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv, set_key
from cryptography.fernet import Fernet

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
DATA_DIR = ROOT_DIR / "data"
LOG_DIR = ROOT_DIR / "logs"

load_dotenv(ENV_PATH)


def _ensure_env_value(key_name: str, generator) -> str:
    """Return os.environ[key_name], generating and persisting it to .env if missing."""
    value = os.getenv(key_name)
    if value:
        return value
    value = generator()
    set_key(str(ENV_PATH), key_name, value)
    os.environ[key_name] = value
    return value


# --- Required from the user ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")

# --- Auto-generated on first run, then reused from .env every run after ---
JWT_SECRET = _ensure_env_value("JWT_SECRET", lambda: secrets.token_hex(32))
FERNET_KEY = _ensure_env_value("FERNET_KEY", lambda: Fernet.generate_key().decode())
POLICY_API_KEY = _ensure_env_value("POLICY_API_KEY", lambda: secrets.token_hex(16))
UI_STORAGE_SECRET = _ensure_env_value("UI_STORAGE_SECRET", lambda: secrets.token_hex(32))

POLICY_SERVICE_URL = os.getenv("POLICY_SERVICE_URL", "http://127.0.0.1:8001")

# --- Behaviour tuning ---
JWT_EXPIRY_MINUTES = 60
INVESTIGATION_CONFIDENCE_THRESHOLD = 0.6  # below this, escalate to a human
MAX_INPUT_LENGTH = 1000

LOG_DIR.mkdir(exist_ok=True)

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Copy .env.example to .env and add your key "
        "from https://console.groq.com"
    )
