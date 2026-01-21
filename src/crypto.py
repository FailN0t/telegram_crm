"""
Cryptography utilities for secure data storage.

Provides encryption/decryption for sensitive data like session strings.
Uses Fernet symmetric encryption (AES 128 in CBC mode).
"""

import base64
import hashlib
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

# Use standard logging to avoid circular import (logger -> config -> crypto -> logger)
logger = logging.getLogger(__name__)


class SessionEncryption:
    """
    Encryption/decryption for Telegram session strings.

    Uses Fernet (symmetric encryption) with key derived from environment variable.
    If no encryption key is configured, falls back to plain text storage with warnings.

    Security Notes:
        - SESSION_ENCRYPTION_KEY must be 32 bytes (base64-encoded 44 chars)
        - Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        - Store in .env or Docker secrets
        - Rotate keys periodically in production
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize encryption handler.

        Args:
            encryption_key: Base64-encoded 32-byte key (optional)
                           If None, encryption is disabled (development mode)
        """
        self._enabled = False
        self._fernet: Optional[Fernet] = None

        if encryption_key:
            try:
                # Validate and create Fernet instance
                key_bytes = encryption_key.encode('utf-8')
                self._fernet = Fernet(key_bytes)
                self._enabled = True
                logger.info("✅ Session encryption enabled (Fernet AES-128)")
            except Exception as e:
                logger.error(
                    f"❌ Invalid SESSION_ENCRYPTION_KEY: {e}. "
                    f"Falling back to plain text storage!"
                )
                self._enabled = False
        else:
            logger.warning(
                "⚠️ SESSION_ENCRYPTION_KEY not configured. "
                "Session strings will be stored in PLAIN TEXT! "
                "This is a SECURITY RISK in production."
            )
            self._enabled = False

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypt session string.

        Args:
            plaintext: Session string to encrypt (can be None)

        Returns:
            Encrypted string (base64-encoded) or plaintext if encryption disabled
        """
        if not plaintext:
            return plaintext

        if not self._enabled or not self._fernet:
            # Encryption disabled - return plaintext
            return plaintext

        try:
            encrypted_bytes = self._fernet.encrypt(plaintext.encode('utf-8'))
            return encrypted_bytes.decode('utf-8')
        except Exception as e:
            logger.error(f"❌ Encryption failed: {e}. Storing in plain text!")
            return plaintext

    def decrypt(self, ciphertext: Optional[str]) -> Optional[str]:
        """
        Decrypt session string.

        Args:
            ciphertext: Encrypted session string (can be None)

        Returns:
            Decrypted string or ciphertext if encryption disabled/failed
        """
        if not ciphertext:
            return ciphertext

        if not self._enabled or not self._fernet:
            # Encryption disabled - return as-is
            return ciphertext

        try:
            # Try to decrypt
            decrypted_bytes = self._fernet.decrypt(ciphertext.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except InvalidToken:
            # Not encrypted data or wrong key - return as-is (backward compatibility)
            logger.warning(
                "⚠️ Failed to decrypt session string (wrong key or plain text data). "
                "Returning as-is for backward compatibility."
            )
            return ciphertext
        except Exception as e:
            logger.error(f"❌ Decryption failed: {e}. Returning as-is.")
            return ciphertext

    @property
    def is_enabled(self) -> bool:
        """Check if encryption is enabled."""
        return self._enabled


def derive_key_from_secret(secret: str) -> str:
    """
    Derive Fernet-compatible key from arbitrary secret string.

    Uses SHA-256 hash to derive 32-byte key, then base64-encodes it.
    This allows using any secret string as encryption key.

    Args:
        secret: Any secret string (e.g., from API_SECRET_KEY)

    Returns:
        Base64-encoded 32-byte key suitable for Fernet

    Example:
        >>> key = derive_key_from_secret("my-secret-key-123")
        >>> encryptor = SessionEncryption(key)
    """
    # SHA-256 produces 32 bytes (256 bits)
    hash_bytes = hashlib.sha256(secret.encode('utf-8')).digest()
    # Base64-encode for Fernet
    return base64.urlsafe_b64encode(hash_bytes).decode('utf-8')


# Singleton instance (will be initialized in config.py)
_session_encryption: Optional[SessionEncryption] = None


def init_session_encryption(encryption_key: Optional[str] = None) -> SessionEncryption:
    """
    Initialize global session encryption instance.

    Should be called once during application startup from config.py.

    Args:
        encryption_key: Base64-encoded 32-byte key (optional)

    Returns:
        SessionEncryption instance
    """
    global _session_encryption
    _session_encryption = SessionEncryption(encryption_key)
    return _session_encryption


def get_session_encryption() -> SessionEncryption:
    """
    Get global session encryption instance.

    Returns:
        SessionEncryption instance (must be initialized first)

    Raises:
        RuntimeError: If not initialized yet
    """
    global _session_encryption
    if _session_encryption is None:
        raise RuntimeError(
            "Session encryption not initialized. "
            "Call init_session_encryption() first."
        )
    return _session_encryption
