"""
UMA Platform — Credentials Encryption
Fernet symmetric encryption for connection credentials at rest.
All `Connection.credentials` JSON fields are encrypted before write and decrypted on read.

Key management:
- UMA_ENCRYPTION_KEY env var (base64-encoded Fernet key) is primary.
- Supports key rotation via UMA_ENCRYPTION_KEYS (comma-separated, newest first).
- Decryption tries each key in order; encryption always uses the first.
"""

import base64
import json
import logging
import os
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger("uma.security")


class CredentialCipher:
    """Wraps Fernet encryption with support for key rotation."""

    def __init__(self, keys: List[str]):
        if not keys:
            raise ValueError("At least one encryption key required")
        fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
        self._fernet = MultiFernet(fernets)

    @classmethod
    def from_env(cls) -> "CredentialCipher":
        """Load keys from env. Primary: UMA_ENCRYPTION_KEY. Rotation: UMA_ENCRYPTION_KEYS."""
        primary = os.getenv("UMA_ENCRYPTION_KEY", "").strip()
        rotation = os.getenv("UMA_ENCRYPTION_KEYS", "").strip()

        keys = []
        if primary:
            keys.append(primary)
        if rotation:
            keys.extend(k.strip() for k in rotation.split(",") if k.strip())

        if not keys:
            # Dev-only fallback: derive from SECRET_KEY (NOT secure for prod)
            secret = os.getenv("SECRET_KEY", "")
            if secret and len(secret) >= 32:
                import hashlib
                derived = base64.urlsafe_b64encode(
                    hashlib.sha256(secret.encode()).digest()
                ).decode()
                logger.warning(
                    "UMA_ENCRYPTION_KEY not set — deriving from SECRET_KEY. "
                    "SET UMA_ENCRYPTION_KEY in production!"
                )
                keys = [derived]
            else:
                raise RuntimeError(
                    "UMA_ENCRYPTION_KEY required in production. Generate one with:\n"
                    "  python3 -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\""
                )

        return cls(keys)

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            return ""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            logger.error("Credential decryption failed — key mismatch or corruption")
            raise

    def encrypt_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Encrypt a credentials dict. Each value becomes an encrypted string."""
        if not data:
            return {}
        return {
            "__encrypted__": True,
            "data": self.encrypt(json.dumps(data)),
        }

    def decrypt_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Decrypt a credentials dict. Accepts legacy plaintext data transparently."""
        if not data:
            return {}
        if isinstance(data, dict) and data.get("__encrypted__"):
            try:
                return json.loads(self.decrypt(data.get("data", "")))
            except Exception as e:
                logger.error(f"Failed to decrypt credentials: {e}")
                return {}
        # Legacy plaintext — log warning, return as-is
        if data:
            logger.warning(
                "Credentials stored in plaintext — will be encrypted on next write. "
                "Run scripts/encrypt_existing_credentials.py to migrate."
            )
        return data


# Singleton
_cipher: Optional[CredentialCipher] = None


def get_cipher() -> CredentialCipher:
    global _cipher
    if _cipher is None:
        _cipher = CredentialCipher.from_env()
    return _cipher


def mask_secret(value: str, visible: int = 4) -> str:
    """Return 'abc1****' — for displaying credentials in UI."""
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)
