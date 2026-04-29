"""Cryptographic secret generation utilities.

This module provides low-level cryptographic primitives for generating
secure random strings, passwords, and signing secrets.

All methods are stateless and have no dependencies on I/O or storage.
"""

from __future__ import annotations

import secrets
import shutil
import subprocess
from enum import Enum
from pathlib import Path


class CharSet(Enum):
    """Character sets for secret generation."""

    BASE64 = "base64"
    HEX = "hex"
    ALPHANUMERIC = "alphanumeric"
    PASSWORD = "password"


# Standard alphabets
_ALPHANUMERIC = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_PASSWORD_CHARS = _ALPHANUMERIC + "!@#$%^&*()_+-=[]{}|;:,.<>?"
_BACKUP_PASSWORD_CHARS = _ALPHANUMERIC + "!@#$%^&*()_+-=[]{}|"


class SecretGenerator:
    """Generator for cryptographic secrets.

    Provides static methods for generating various types of secure random
    values using either OpenSSL or Python's secrets module.

    This class has no state and no dependencies on I/O, storage, or UI.
    All methods can be called without instantiation.
    """

    @staticmethod
    def check_dependencies() -> None:
        """Check that required dependencies are available.

        Raises:
            RuntimeError: If openssl is not found or /dev/urandom unavailable
        """
        if shutil.which("openssl") is None:
            raise RuntimeError(
                "openssl command not found. Please install OpenSSL to continue."
            )

        if not Path("/dev/urandom").exists():
            raise RuntimeError(
                "/dev/urandom not available. Cannot generate secure random values."
            )

    @staticmethod
    def _run_openssl_rand(length: int, encoding: str = "base64") -> str:
        """Run openssl rand command with specified encoding.

        Args:
            length: Number of bytes to generate
            encoding: Output encoding ("base64" or "hex")

        Returns:
            Generated random string
        """
        result = subprocess.run(
            ["openssl", "rand", f"-{encoding}", str(length)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    @staticmethod
    def _to_base64url(value: str) -> str:
        """Convert standard base64 to URL-safe base64url encoding.

        Replaces + with -, / with _, and removes trailing = padding.

        Args:
            value: Standard base64-encoded string

        Returns:
            URL-safe base64url-encoded string
        """
        return value.replace("+", "-").replace("/", "_").rstrip("=")

    @staticmethod
    def _random_string(length: int, alphabet: str) -> str:
        """Generate a random string from the given alphabet.

        Uses Python's secrets module for cryptographically secure randomness.

        Args:
            length: Length of string to generate
            alphabet: Characters to choose from

        Returns:
            Random string of specified length
        """
        return "".join(secrets.choice(alphabet) for _ in range(length))

    @classmethod
    def generate_secure_random(
        cls, length: int = 32, charset: CharSet = CharSet.BASE64
    ) -> str:
        """Generate a secure random string.

        Args:
            length: Length of the string (meaning depends on charset)
            charset: Character set to use

        Returns:
            Cryptographically secure random string
        """
        match charset:
            case CharSet.BASE64:
                return cls._run_openssl_rand(length, "base64")
            case CharSet.HEX:
                return cls._run_openssl_rand(length, "hex")
            case CharSet.ALPHANUMERIC:
                return cls._random_string(length, _ALPHANUMERIC)
            case CharSet.PASSWORD:
                return cls._random_string(length, _PASSWORD_CHARS)

    @classmethod
    def generate_jwt_secret(cls) -> str:
        """Generate a JWT signing secret (256-bit).

        Returns:
            Base64-encoded 32-byte (256-bit) secret
        """
        return cls._run_openssl_rand(32, "base64")

    @classmethod
    def generate_db_password(cls) -> str:
        """Generate a database password.

        Returns 24-character password with alphanumeric only (URL-safe).
        Avoids special characters that need URL encoding: / @ : ? # [ ] & = + $ , ; %

        Returns:
            24-character alphanumeric password
        """
        return cls._random_string(24, _ALPHANUMERIC)

    @classmethod
    def generate_csrf_secret(cls) -> str:
        """Generate CSRF token secret.

        Returns 32 bytes (256 bits) for CSRF protection.
        Uses base64url encoding (URL-safe).

        Returns:
            URL-safe base64url-encoded 32-byte secret
        """
        raw = cls._run_openssl_rand(32, "base64")
        return cls._to_base64url(raw)

    @classmethod
    def generate_session_secret(cls) -> str:
        """Generate session signing secret.

        Returns 32 bytes (256 bits) for session signing.
        Uses base64url encoding (URL-safe).

        Returns:
            URL-safe base64url-encoded 32-byte secret
        """
        raw = cls._run_openssl_rand(32, "base64")
        return cls._to_base64url(raw)

    @classmethod
    def generate_backup_password(cls) -> str:
        """Generate backup encryption password.

        Returns 32-character strong password for backup encryption.

        Returns:
            32-character password with letters, numbers, and symbols
        """
        return cls._random_string(32, _BACKUP_PASSWORD_CHARS)
