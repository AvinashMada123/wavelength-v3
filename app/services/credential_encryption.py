"""Fernet-based encryption for messaging provider credentials."""

import json
from cryptography.fernet import Fernet


def encrypt_credentials(creds: dict, key: str) -> str:
    """Encrypt a credentials dict to a Fernet token string."""
    f = Fernet(key.encode() if isinstance(key, str) else key)
    plaintext = json.dumps(creds).encode()
    return f.encrypt(plaintext).decode()


def decrypt_credentials(encrypted: str, key: str) -> dict:
    """Decrypt a Fernet token string back to a credentials dict."""
    f = Fernet(key.encode() if isinstance(key, str) else key)
    plaintext = f.decrypt(encrypted.encode() if isinstance(encrypted, str) else encrypted)
    return json.loads(plaintext)
