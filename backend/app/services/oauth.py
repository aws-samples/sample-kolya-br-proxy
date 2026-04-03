"""
OAuth state management service.
Handles generation and validation of OAuth state parameters for CSRF protection.
Includes PKCE (Proof Key for Code Exchange) support for OAuth 2.1 best practices.
"""

import base64
import hashlib
import secrets
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oauth_state import OAuthState


class OAuthService:
    """Service for managing OAuth state parameters."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_state(self, provider: str) -> tuple[str, str]:
        """
        Generate and store a new OAuth state parameter with PKCE challenge.

        Args:
            provider: OAuth provider name (e.g., "microsoft")

        Returns:
            Tuple of (state, code_challenge)
        """
        # Generate a cryptographically secure random state
        state = secrets.token_urlsafe(32)

        # Generate PKCE code_verifier and code_challenge (S256)
        # SHA-256 is mandated by RFC 7636 §4.2 — not used for password hashing.
        code_verifier = secrets.token_urlsafe(96)  # ~128 chars
        digest = hashlib.sha256(
            code_verifier.encode("ascii")
        ).digest()  # CodeQL: false positive — PKCE S256 per RFC 7636
        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

        # Store in database
        oauth_state = OAuthState(
            state=state, provider=provider, code_verifier=code_verifier
        )
        self.db.add(oauth_state)
        await self.db.commit()

        return state, code_challenge

    async def validate_state(
        self, state: str, provider: str
    ) -> tuple[bool, str | None]:
        """
        Validate and consume an OAuth state parameter.

        Args:
            state: State parameter to validate
            provider: OAuth provider name

        Returns:
            Tuple of (is_valid, code_verifier)
        """
        if not state:
            return False, None

        # Query for the state
        query = select(OAuthState).where(
            OAuthState.state == state, OAuthState.provider == provider
        )
        result = await self.db.execute(query)
        oauth_state = result.scalar_one_or_none()

        if not oauth_state:
            return False, None

        # Check if expired
        if oauth_state.is_expired():
            # Delete expired state
            await self.db.delete(oauth_state)
            await self.db.commit()
            return False, None

        # Extract code_verifier before deletion
        code_verifier = oauth_state.code_verifier

        # Delete the state (one-time use)
        await self.db.delete(oauth_state)
        await self.db.commit()

        return True, code_verifier

    async def cleanup_expired_states(self) -> int:
        """
        Clean up expired OAuth states from database.

        Returns:
            Number of deleted states
        """
        query = delete(OAuthState).where(OAuthState.expires_at < datetime.utcnow())
        result = await self.db.execute(query)
        await self.db.commit()
        return result.rowcount
