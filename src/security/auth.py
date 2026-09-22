"""
Authentication: password hashing (bcrypt) + session tokens (JWT).

This is the piece the "Privacy and Data Leakage" individual assessment
(Student 2's specialization) will red-team - e.g. weak passwords accepted,
token expiry not enforced, no lockout after repeated failed logins, etc.
Keep it real rather than decorative so there's something genuine to test.
"""

import datetime
import json

import bcrypt
import jwt

from src.config import DATA_DIR, JWT_SECRET, JWT_EXPIRY_MINUTES

USERS_FILE = DATA_DIR / "users.json"


def _load_users() -> dict:
    if not USERS_FILE.exists():
        return {}
    return json.loads(USERS_FILE.read_text(encoding="utf-8"))


def _save_users(users: dict) -> None:
    USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def seed_demo_user() -> None:
    """Creates a demo login (demo / Demo@123) the first time the app runs."""
    users = _load_users()
    if "demo" not in users:
        users["demo"] = hash_password("Demo@123")
        _save_users(users)


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_credentials(username: str, plain_password: str) -> bool:
    users = _load_users()
    stored_hash = users.get(username)
    if not stored_hash:
        return False
    return bcrypt.checkpw(plain_password.encode("utf-8"), stored_hash.encode("utf-8"))


def create_access_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": datetime.datetime.utcnow(),
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_access_token(token: str) -> str | None:
    """Returns the username if the token is valid and not expired, else None."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
