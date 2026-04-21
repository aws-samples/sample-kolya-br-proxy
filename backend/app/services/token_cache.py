"""Token validation with Redis caching."""

import logging
from typing import Optional
from uuid import UUID

from app.core.redis import RedisCache
from app.models.token import APIToken
from app.services.token import TokenService

logger = logging.getLogger(__name__)


class CachedTokenService:
    """Token service with Redis caching for improved performance."""

    CACHE_TTL = 300  # 5 minutes
    CACHE_KEY_PREFIX = "token:"

    def __init__(self, token_service: TokenService, cache: RedisCache):
        self.cache = cache
        self.token_service = token_service

    def _get_cache_key(self, token_hash: str) -> str:
        """Generate cache key for token."""
        return f"{self.CACHE_KEY_PREFIX}{token_hash}"

    async def validate_token_cached(
        self,
        plain_token: str,
        client_ip: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[APIToken]:
        """
        Validate token with caching.

        Args:
            plain_token: Plain API token
            client_ip: Client IP for validation
            model: Model name for validation

        Returns:
            APIToken if valid, None otherwise
        """
        from app.core.security import hash_token

        token_hash = hash_token(plain_token)
        cache_key = self._get_cache_key(token_hash)

        # Try to get from cache
        cached_data = await self.cache.get(cache_key)

        if cached_data:
            # Reconstruct token from cache
            token = await self._token_from_cache(cached_data)
            if token:
                # Still need to check dynamic conditions
                if token.is_expired or token.is_quota_exceeded:
                    await self.cache.delete(cache_key)
                    return None

                if client_ip and token.allowed_ips:
                    if not self.token_service._is_ip_allowed(
                        client_ip, token.allowed_ips
                    ):
                        return None

                logger.debug(f"Token cache hit: {token.id}")
                return token

        # Cache miss - validate from database
        token = await self.token_service.validate_token(plain_token, client_ip, model)

        if token:
            # Cache the token data
            await self._cache_token(cache_key, token)
            logger.debug(f"Token cached: {token.id}")

        return token

    async def _cache_token(self, cache_key: str, token: APIToken):
        """Cache token data."""
        token_data = {
            "id": str(token.id),
            "user_id": str(token.user_id),
            "name": token.name,
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "quota_usd": str(token.quota_usd) if token.quota_usd else None,
            "allowed_ips": token.allowed_ips,
            "is_active": token.is_active,
        }
        await self.cache.set(cache_key, token_data, expire=self.CACHE_TTL)

    async def _token_from_cache(self, cached_data: dict) -> Optional[APIToken]:
        """Reconstruct token from cached data."""
        try:
            from datetime import datetime
            from decimal import Decimal

            # Create a minimal token object for validation
            # Note: This is not a full ORM object, just for validation
            token = APIToken()
            token.id = UUID(cached_data["id"])
            token.user_id = UUID(cached_data["user_id"])
            token.name = cached_data["name"]
            token.expires_at = (
                datetime.fromisoformat(cached_data["expires_at"])
                if cached_data["expires_at"]
                else None
            )
            token.quota_usd = (
                Decimal(cached_data["quota_usd"]) if cached_data["quota_usd"] else None
            )
            token.allowed_ips = cached_data["allowed_ips"]
            token.is_active = cached_data["is_active"]

            return token
        except Exception as e:
            logger.error(f"Error reconstructing token from cache: {e}")
            return None

    async def invalidate_token_cache(self, token_hash: str):
        """Invalidate cached token."""
        cache_key = self._get_cache_key(token_hash)
        await self.cache.delete(cache_key)
