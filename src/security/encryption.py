"""
Field-level encryption for customer PII (phone numbers, addresses) before
they are written to logs or the case history file. Uses Fernet (AES-128
under the hood) with a key that config.py generates once and stores in .env.
"""

from cryptography.fernet import Fernet

from src.config import FERNET_KEY

_fernet = Fernet(FERNET_KEY.encode())


def encrypt_field(plain_text: str) -> str:
    if not plain_text:
        return plain_text
    return _fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_field(token: str) -> str:
    if not token:
        return token
    return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
