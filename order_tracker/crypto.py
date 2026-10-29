"""Encrypting small secrets kept in the database, such as statement passwords."""

from cryptography.fernet import Fernet, InvalidToken

from .config import token_key


def encrypt(text: str) -> str:
    return Fernet(token_key()).encrypt(text.encode()).decode() if text else ""


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return Fernet(token_key()).decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
