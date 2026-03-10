"""
OAuth state management service.
Handles generation and validation of OAuth state parameters for CSRF protection.
"""

import secrets
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.oauth_state import OAuthState


class OAuthService:
    """Service for managing OAuth state parameters."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_state(self, provider: str) -> str:
        """
        Generate and store a new OAuth state parameter.

        Args:
            provider: OAuth provider name (e.g., "microsoft")

        Returns:
            Generated state string
        """
        # Generate a cryptographically secure random state
        state = secrets.token_urlsafe(32)

        # Store in database
        oauth_state = OAuthState(state=state, provider=provider)
        self.db.add(oauth_state)
        await self.db.commit()

        return state

    async def validate_state(self, state: str, provider: str) -> bool:
        """
        Validate and consume an OAuth state parameter.

        Args:
            state: State parameter to validate
            provider: OAuth provider name

        Returns:
            True if state is valid and not expired, False otherwise
        """
        if not state:
            return False

        # Query for the state
        query = select(OAuthState).where(
            OAuthState.state == state, OAuthState.provider == provider
        )
        result = await self.db.execute(query)
        oauth_state = result.scalar_one_or_none()

        if not oauth_state:
            return False

        # Check if expired
        if oauth_state.is_expired():
            # Delete expired state
            await self.db.delete(oauth_state)
            await self.db.commit()
            return False

        # Delete the state (one-time use)
        await self.db.delete(oauth_state)
        await self.db.commit()

        return True

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
