"""Encryption helpers for provider credentials stored in SQLite."""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialEncryptionError(ValueError):
    """Raised when the host encryption key is missing or invalid."""


def load_encryption_key() -> bytes:
    encoded = os.getenv("AI_CREDENTIALS_ENCRYPTION_KEY", "")
    if not encoded:
        raise CredentialEncryptionError(
            "AI_CREDENTIALS_ENCRYPTION_KEY is not configured on the backend host."
        )
    try:
        key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (ValueError, base64.binascii.Error) as exc:
        raise CredentialEncryptionError(
            "AI_CREDENTIALS_ENCRYPTION_KEY must be URL-safe base64 encoded."
        ) from exc
    if len(key) != 32:
        raise CredentialEncryptionError(
            "AI_CREDENTIALS_ENCRYPTION_KEY must decode to exactly 32 bytes."
        )
    return key


def encrypt_api_key(api_key: str) -> tuple[bytes, bytes]:
    if not isinstance(api_key, str) or not api_key.strip():
        raise CredentialEncryptionError("API key cannot be empty.")
    key = load_encryption_key()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, api_key.encode("utf-8"), None)
    return ciphertext, nonce


def decrypt_api_key(ciphertext: bytes, nonce: bytes) -> str:
    key = load_encryption_key()
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise CredentialEncryptionError(
            "Stored API key could not be decrypted; check the host encryption key."
        ) from exc