import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *a, **k: Mock()))

from cryptography.fernet import Fernet

TEST_KEY = Fernet.generate_key().decode()


def test_encrypt_decrypt_roundtrip():
    from app.services.credential_encryption import encrypt_credentials, decrypt_credentials

    creds = {"api_url": "https://live-server-123.wati.io", "api_token": "Bearer abc123"}
    encrypted = encrypt_credentials(creds, TEST_KEY)
    assert isinstance(encrypted, str)
    assert "abc123" not in encrypted

    decrypted = decrypt_credentials(encrypted, TEST_KEY)
    assert decrypted == creds


def test_encrypt_empty_dict():
    from app.services.credential_encryption import encrypt_credentials, decrypt_credentials

    encrypted = encrypt_credentials({}, TEST_KEY)
    assert decrypt_credentials(encrypted, TEST_KEY) == {}


def test_decrypt_with_wrong_key_raises():
    from app.services.credential_encryption import encrypt_credentials, decrypt_credentials

    encrypted = encrypt_credentials({"key": "val"}, TEST_KEY)
    wrong_key = Fernet.generate_key().decode()
    try:
        decrypt_credentials(encrypted, wrong_key)
        assert False, "Should have raised"
    except Exception:
        pass
