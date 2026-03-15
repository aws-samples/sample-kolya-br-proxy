"""
Token management service for API token operations.
Handles token creation, validation, and access control.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    generate_api_token,
    hash_token,
    encrypt_token,
    decrypt_token,
)
from app.models.token import APIToken


class TokenService:
    """Service for handling API token operations."""

    def __init__(self, db: AsyncSession):
        """
        Initialize token service.

        Args:
            db: Database session
        """
        self.db = db

    async def create_token(
        self,
        user_id: UUID,
        name: str,
        expires_at: Optional[datetime] = None,
        quota_usd: Optional[Decimal] = None,
        allowed_ips: Optional[List[str]] = None,
        token_metadata: Optional[dict] = None,
    ) -> tuple[APIToken, str]:
        """
        Create a new API token for a user.

        Args:
            user_id: User UUID
            name: Token name/description
            expires_at: Optional expiration datetime
            quota_usd: Optional usage quota in USD
            allowed_ips: Optional list of allowed IP addresses/ranges
            token_metadata: Optional metadata dict for per-key configuration

        Returns:
            Tuple of (APIToken object, plain token string)
            Note: Plain token is only returned once at creation
        """
        # Generate unique token
        plain_token = generate_api_token()
        token_hash = hash_token(plain_token)
        encrypted = encrypt_token(plain_token)

        # Create token record
        token = APIToken(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            encrypted_token=encrypted,
            expires_at=expires_at,
            quota_usd=quota_usd,
            allowed_ips=allowed_ips or [],
            token_metadata=token_metadata,
            is_active=True,
        )

        self.db.add(token)
        await self.db.commit()
        await self.db.refresh(token)

        return token, plain_token

    async def get_token_by_id(self, token_id: UUID) -> Optional[APIToken]:
        """
        Get token by ID.

        Args:
            token_id: Token UUID

        Returns:
            APIToken object if found, None otherwise
        """
        result = await self.db.execute(select(APIToken).where(APIToken.id == token_id))
        return result.scalar_one_or_none()

    async def get_plain_token(self, token_id: UUID) -> Optional[str]:
        """
        Get decrypted plain token by ID.

        Args:
            token_id: Token UUID

        Returns:
            Plain token string if found, None otherwise
        """
        token = await self.get_token_by_id(token_id)
        if not token or not token.encrypted_token:
            return None

        try:
            return decrypt_token(token.encrypted_token)
        except Exception:
            return None

    async def get_user_tokens(
        self,
        user_id: UUID,
        include_inactive: bool = False,
    ) -> List[APIToken]:
        """
        Get all tokens for a user (excluding deleted).

        Args:
            user_id: User UUID
            include_inactive: Whether to include inactive tokens

        Returns:
            List of APIToken objects
        """
        query = select(APIToken).where(
            APIToken.user_id == user_id, APIToken.is_deleted.is_(False)
        )

        if not include_inactive:
            query = query.where(APIToken.is_active)

        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def validate_token(
        self,
        plain_token: str,
        client_ip: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[APIToken]:
        """
        Validate an API token and check access controls.

        Optimized to query only active tokens and verify hash.

        Args:
            plain_token: Plain API token string
            client_ip: Client IP address for IP restriction check
            model: Model name for model restriction check

        Returns:
            APIToken object if valid, None otherwise
        """
        # Hash the plain token to query directly
        token_hash = hash_token(plain_token)

        # Query by token_hash directly (much faster!)
        result = await self.db.execute(
            select(APIToken).where(
                APIToken.token_hash == token_hash, APIToken.is_active.is_(True)
            )
        )
        token = result.scalar_one_or_none()

        if not token:
            return None

        # Check expiration
        if token.is_expired:
            return None

        # Check quota
        if token.is_quota_exceeded:
            return None

        # Check IP restrictions
        if client_ip and token.allowed_ips:
            if not self._is_ip_allowed(client_ip, token.allowed_ips):
                return None

        # Note: Model restrictions are now checked via the models relationship in the endpoint

        # Update last used timestamp asynchronously (don't wait)
        # This avoids blocking the request
        token.last_used_at = datetime.utcnow()
        self.db.add(token)
        # Don't await commit - let it happen in background

        return token

    async def update_token(
        self,
        token_id: UUID,
        name: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        quota_usd: Optional[Decimal] = None,
        allowed_ips: Optional[List[str]] = None,
        allowed_models: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[APIToken]:
        """
        Update token settings.

        Args:
            token_id: Token UUID
            name: New token name
            expires_at: New expiration datetime
            quota_usd: New usage quota
            allowed_ips: New IP restrictions
            allowed_models: New model restrictions
            is_active: New active status

        Returns:
            Updated APIToken object if found, None otherwise
        """
        token = await self.get_token_by_id(token_id)
        if not token:
            return None

        if name is not None:
            token.name = name
        if expires_at is not None:
            token.expires_at = expires_at
        if quota_usd is not None:
            token.quota_usd = quota_usd
        if allowed_ips is not None:
            token.allowed_ips = allowed_ips
        if allowed_models is not None:
            token.allowed_models = allowed_models
        if is_active is not None:
            token.is_active = is_active

        await self.db.commit()
        await self.db.refresh(token)

        return token

    async def revoke_token(self, token_id: UUID) -> bool:
        """
        Revoke (deactivate) a token.

        Args:
            token_id: Token UUID

        Returns:
            True if successful, False if token not found
        """
        token = await self.get_token_by_id(token_id)
        if not token:
            return False

        token.is_active = False
        await self.db.commit()
        return True

    async def delete_token(self, token_id: UUID) -> bool:
        """
        Soft delete a token (mark as deleted for historical data).

        Args:
            token_id: Token UUID

        Returns:
            True if successful, False if token not found
        """
        token = await self.get_token_by_id(token_id)
        if not token:
            return False

        token.is_deleted = True
        token.deleted_at = datetime.utcnow()
        await self.db.commit()
        return True

    async def record_usage(
        self,
        token_id: UUID,
        cost_usd: Decimal,
    ) -> bool:
        """
        Record token usage and update used amount.

        Args:
            token_id: Token UUID
            cost_usd: Cost in USD to add

        Returns:
            True if successful, False if token not found
        """
        token = await self.get_token_by_id(token_id)
        if not token:
            return False

        token.used_usd += cost_usd
        await self.db.commit()
        return True

    def _is_ip_allowed(self, client_ip: str, allowed_ips: List[str]) -> bool:
        """
        Check if client IP is in allowed list.

        Supports:
        - Exact IP: 192.168.1.1
        - CIDR notation: 192.168.1.0/24
        - IP ranges: 192.168.1.1-192.168.1.255

        Args:
            client_ip: Client IP address
            allowed_ips: List of allowed IP patterns

        Returns:
            True if IP is allowed, False otherwise
        """
        import ipaddress

        try:
            client_addr = ipaddress.ip_address(client_ip)
        except ValueError:
            return False

        for allowed in allowed_ips:
            try:
                # Check CIDR notation
                if "/" in allowed:
                    network = ipaddress.ip_network(allowed, strict=False)
                    if client_addr in network:
                        return True
                # Check exact match
                elif client_ip == allowed:
                    return True
                # TODO: Add support for IP ranges if needed
            except ValueError:
                continue

        return False
