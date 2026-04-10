"""
Security utilities for authentication and authorization.
Provides password hashing, API token generation, JWT token management, and validation.
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
import jwt
from jwt.exceptions import InvalidTokenError as JWTError
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# JWT algorithm whitelist for security
ALLOWED_JWT_ALGORITHMS = ["HS256", "HS384", "HS512"]

# Encryption key for token storage (should be in settings in production)
# For now, we'll use a derived key from JWT_SECRET_KEY


def _get_encryption_key() -> bytes:
    """Derive a Fernet-compatible encryption key from the JWT secret.

    Uses PBKDF2-HMAC-SHA256 for key derivation — satisfies CodeQL
    requirement for computationally expensive hashing of sensitive data.
    """
    key_material = settings.JWT_SECRET_KEY.encode()
    key = hashlib.pbkdf2_hmac(
        "sha256", key_material, b"kolya-br-proxy-enc", iterations=100_000, dklen=32
    )
    return base64.urlsafe_b64encode(key)


_fernet = Fernet(_get_encryption_key())

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain password against a hashed password.

    Args:
        plain_password: Plain text password
        hashed_password: Bcrypt hashed password

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Generate a bcrypt hash for a password.

    Args:
        password: Plain text password

    Returns:
        Bcrypt hashed password
    """
    return pwd_context.hash(password)


def generate_api_token(prefix: str = "sk-ant-api03") -> str:
    """
    Generate a secure API token.

    Format: {prefix}_{random_string}
    Example: sk-ant-api03_abc123def456...

    Args:
        prefix: Token prefix for identification

    Returns:
        Generated API token string
    """
    # Generate 32 bytes of random data, encode as URL-safe base64
    random_part = secrets.token_urlsafe(32)
    return f"{prefix}_{random_part}"


def hash_token(token: str) -> str:
    """
    Hash an API token for secure storage and fast lookup.

    Uses SHA256 for deterministic hashing (same input = same output).
    This allows us to query by hash efficiently with database indexes.

    Args:
        token: Plain API token

    Returns:
        SHA256 hash of token (hex string)
    """
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(plain_token: str, hashed_token: str) -> bool:
    """
    Verify a plain API token against a hashed token.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        plain_token: Plain API token
        hashed_token: Keyed hash from database

    Returns:
        True if token matches, False otherwise
    """
    computed_hash = hash_token(plain_token)
    return secrets.compare_digest(computed_hash, hashed_token)


def encrypt_token(plain_token: str) -> str:
    """
    Encrypt an API token for secure storage.

    Args:
        plain_token: Plain API token

    Returns:
        Encrypted token string
    """
    encrypted = _fernet.encrypt(plain_token.encode())
    return encrypted.decode()


def decrypt_token(encrypted_token: str) -> str:
    """
    Decrypt an encrypted API token.

    Args:
        encrypted_token: Encrypted token from database

    Returns:
        Plain API token

    Raises:
        Exception: If decryption fails
    """
    decrypted = _fernet.decrypt(encrypted_token.encode())
    return decrypted.decode()


# ============================================================================
# JWT Token Management (for Web Dashboard Login)
# ============================================================================


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create JWT access token for web dashboard authentication.

    Args:
        data: Token payload data (should include 'sub' with user_id)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "access"})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    return encoded_jwt


def create_refresh_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create JWT refresh token for web dashboard authentication.

    Args:
        data: Token payload data (should include 'sub' with user_id)
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT refresh token string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )

    to_encode.update({"exp": expire, "iat": datetime.utcnow(), "type": "refresh"})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

    return encoded_jwt


def decode_jwt_token(token: str) -> Dict[str, Any]:
    """
    Decode and verify JWT token with algorithm whitelist validation.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        JWTError: If token is invalid, expired, or uses disallowed algorithm
    """
    # Validate algorithm is in whitelist
    if settings.JWT_ALGORITHM not in ALLOWED_JWT_ALGORITHMS:
        raise JWTError(f"JWT algorithm {settings.JWT_ALGORITHM} not in whitelist")

    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    return payload


# ============================================================================
# Refresh Token Management (for Token Rotation)
# ============================================================================


def hash_refresh_token(token: str) -> str:
    """
    Hash a refresh token for secure storage.

    Uses PBKDF2-HMAC-SHA256 with 100 000 iterations for deterministic
    hashing to allow efficient lookup while preventing offline attacks.

    Args:
        token: Plain refresh token (JWT string)

    Returns:
        PBKDF2 hash of token (hex string)
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        token.encode(),
        settings.JWT_SECRET_KEY.encode(),
        iterations=100_000,
    ).hex()


def generate_token_family_id() -> UUID:
    """
    Generate a new token family ID.

    Token families are used to track token rotation chains and detect theft.
    All tokens in the same rotation chain share the same family_id.

    Returns:
        New UUID for token family
    """
    return uuid4()


# NOTE: JWT Key Rotation Considerations
#
# For production systems requiring JWT key rotation:
#
# 1. Multi-key support:
#    - Store multiple JWT secret keys with key IDs (kid)
#    - Include "kid" in JWT header to identify which key signed it
#    - Maintain list of active keys (current + previous for grace period)
#
# 2. Rotation process:
#    - Generate new key and add to active keys list
#    - Start signing new tokens with new key
#    - Keep old key(s) active for verification during grace period
#    - Remove old keys after all tokens signed with them expire
#
# 3. Implementation:
#    - Add JWT_SECRET_KEYS dict to settings: {kid: key}
#    - Update JWT_CURRENT_KEY_ID setting
#    - Modify create_*_token to include kid in header
#    - Modify decode_jwt_token to lookup key by kid
#
# 4. Storage:
#    - Store keys in secure secret manager (AWS Secrets Manager, HashiCorp Vault)
#    - Rotate via automated process
#    - Audit all key operations
