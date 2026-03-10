"""
Authentication service for user management.
Handles OAuth-based authentication via Microsoft.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class AuthService:
    """Service for handling authentication operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize authentication service.

        Args:
            db: Database session
        """
        self.db = db

    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """
        Get user by ID.

        Args:
            user_id: User UUID

        Returns:
            User object if found, None otherwise
        """
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email.

        Args:
            email: User email address

        Returns:
            User object if found, None otherwise
        """
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
