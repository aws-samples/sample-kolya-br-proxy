"""
API Token management endpoints.
"""

from datetime import datetime
from decimal import Decimal
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_from_jwt, get_token_service
from app.core.database import get_db
from app.core.security import decrypt_token
from app.models.token import APIToken
from app.models.usage import UsageRecord
from app.models.user import User
from app.services.token import TokenService

router = APIRouter()


ALLOWED_METADATA_KEYS = {"prompt_cache_enabled", "prompt_cache_ttl"}
ALLOWED_CACHE_TTL_VALUES = {"5m", "1h"}


def validate_token_metadata(meta: dict | None) -> dict | None:
    """Validate token_metadata keys and values."""
    if meta is None:
        return None
    unknown = set(meta.keys()) - ALLOWED_METADATA_KEYS
    if unknown:
        raise ValueError(
            f"Unknown token_metadata keys: {unknown}. Allowed: {ALLOWED_METADATA_KEYS}"
        )
    if "prompt_cache_enabled" in meta and not isinstance(
        meta["prompt_cache_enabled"], bool
    ):
        raise ValueError("prompt_cache_enabled must be a boolean")
    if "prompt_cache_ttl" in meta:
        if meta["prompt_cache_ttl"] not in ALLOWED_CACHE_TTL_VALUES:
            raise ValueError(
                f"prompt_cache_ttl must be one of {ALLOWED_CACHE_TTL_VALUES}"
            )
    return meta


class CreateTokenRequest(BaseModel):
    """Create token request."""

    name: str
    expires_at: datetime | None = None
    quota_usd: Decimal | None = None
    allowed_ips: List[str] | None = None
    token_metadata: dict | None = None


class BatchCreateTokenRequest(BaseModel):
    """Batch create tokens request.

    ``names`` is a comma-separated string of token names (e.g. "alice, bob, charlie").
    Whitespace around each name is automatically trimmed and empty entries are ignored.
    """

    names: str
    expires_at: datetime | None = None
    quota_usd: Decimal | None = None
    allowed_ips: List[str] | None = None
    token_metadata: dict | None = None
    model_names: List[str] | None = None

    def parsed_names(self) -> List[str]:
        """Parse comma-separated names. Supports ASCII comma, Chinese comma, semicolons, and newlines."""
        import re

        return [
            n for n in (s.strip() for s in re.split(r"[,，;；\n]+", self.names)) if n
        ]


class UpdateTokenRequest(BaseModel):
    """Update token request."""

    name: str | None = None
    expires_at: datetime | None = None
    quota_usd: Decimal | None = None
    allowed_ips: List[str] | None = None
    is_active: bool | None = None
    token_metadata: dict | None = None


class TokenResponse(BaseModel):
    """Token response model."""

    id: str
    name: str
    key_prefix: str = "sk-ant-api03"
    expires_at: datetime | None
    quota_usd: str | None
    used_usd: str
    remaining_quota: str | None
    allowed_ips: List[str]
    is_active: bool
    is_expired: bool
    is_quota_exceeded: bool
    created_at: datetime
    last_used_at: datetime | None
    token_metadata: dict | None = None

    class Config:
        from_attributes = True


class TokenWithKeyResponse(TokenResponse):
    """Token response with plain token key (only returned on creation)."""

    token: str


class BatchCreateTokenResponse(BaseModel):
    """Batch create tokens response."""

    created: List[TokenWithKeyResponse]
    total: int


# Helper functions
async def calculate_token_used_usd(token: APIToken, db: AsyncSession) -> Decimal:
    """Calculate total used amount for a token from usage records."""
    usage_query = select(
        func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00"))
    ).where(UsageRecord.token_id == token.id)

    result = await db.execute(usage_query)
    return result.scalar()


def _extract_key_prefix(token: APIToken) -> str:
    """Extract the key prefix from the encrypted token."""
    try:
        if token.encrypted_token:
            plain = decrypt_token(token.encrypted_token)
            if "_" in plain:
                return plain.split("_", 1)[0]
    except Exception:
        pass
    return "sk-ant-api03"


def build_token_response(token: APIToken, used_usd: Decimal) -> TokenResponse:
    """Build TokenResponse with calculated used_usd."""
    token.calculate_used_usd(used_usd)

    return TokenResponse(
        id=str(token.id),
        name=token.name,
        key_prefix=_extract_key_prefix(token),
        expires_at=token.expires_at,
        quota_usd=str(token.quota_usd) if token.quota_usd else None,
        used_usd=str(used_usd),
        remaining_quota=str(token.remaining_quota) if token.remaining_quota else None,
        allowed_ips=token.allowed_ips or [],
        is_active=token.is_active,
        is_expired=token.is_expired,
        is_quota_exceeded=token.is_quota_exceeded,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        token_metadata=token.token_metadata,
    )


@router.post(
    "", response_model=TokenWithKeyResponse, status_code=status.HTTP_201_CREATED
)
async def create_token(
    request: CreateTokenRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new API token.

    - **name**: Token name/description
    - **expires_at**: Optional expiration datetime
    - **quota_usd**: Optional usage quota in USD
    - **allowed_ips**: Optional list of allowed IP addresses/CIDR ranges
    - **allowed_models**: Optional list of allowed model names

    Returns the created token with the plain token key.
    **Important**: The plain token is only shown once. Save it securely.
    """
    # Validate token_metadata
    try:
        validated_meta = validate_token_metadata(request.token_metadata)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    token, plain_token = await token_service.create_token(
        user_id=current_user.id,
        name=request.name,
        expires_at=request.expires_at,
        quota_usd=request.quota_usd,
        allowed_ips=request.allowed_ips,
        token_metadata=validated_meta,
    )

    # New tokens have no usage records yet, skip the query
    used_usd = Decimal("0.00")
    response = build_token_response(token, used_usd)

    return TokenWithKeyResponse(token=plain_token, **response.model_dump())


@router.post(
    "/batch",
    response_model=BatchCreateTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def batch_create_tokens(
    request: BatchCreateTokenRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Batch create API tokens with optional shared model list.

    - **names**: Comma-separated token names (e.g. "alice, bob, charlie")
    - **model_names**: Optional list of model names to assign to all tokens
    """
    names = request.parsed_names()
    if not names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid names provided",
        )
    if len(names) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many names ({len(names)}), maximum is 100",
        )

    try:
        validated_meta = validate_token_metadata(request.token_metadata)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    results = await token_service.create_tokens_batch(
        user_id=current_user.id,
        names=names,
        expires_at=request.expires_at,
        quota_usd=request.quota_usd,
        allowed_ips=request.allowed_ips,
        token_metadata=validated_meta,
        model_names=request.model_names,
    )

    used_usd = Decimal("0.00")
    created = []
    for token, plain_token in results:
        response = build_token_response(token, used_usd)
        resp_dict = response.model_dump()
        # Override key_prefix from plain_token directly (avoid redundant Fernet decrypt)
        resp_dict["key_prefix"] = (
            plain_token.split("_", 1)[0] if "_" in plain_token else "sk-ant-api03"
        )
        created.append(TokenWithKeyResponse(token=plain_token, **resp_dict))

    return BatchCreateTokenResponse(created=created, total=len(created))


@router.get("", response_model=List[TokenResponse])
async def list_tokens(
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    List all tokens for current user.

    - **include_inactive**: Include inactive/revoked tokens

    Returns list of user's tokens (without plain token keys).
    """
    tokens = await token_service.get_user_tokens(
        user_id=current_user.id,
        include_inactive=include_inactive,
    )

    if not tokens:
        return []

    # Batch query: get usage for all tokens in one query
    token_ids = [token.id for token in tokens]
    usage_query = (
        select(
            UsageRecord.token_id,
            func.coalesce(func.sum(UsageRecord.cost_usd), Decimal("0.00")).label(
                "total_cost"
            ),
        )
        .where(UsageRecord.token_id.in_(token_ids))
        .group_by(UsageRecord.token_id)
    )

    result = await db.execute(usage_query)
    usage_map = {row.token_id: row.total_cost for row in result}

    # Build responses with usage data
    token_responses = []
    for token in tokens:
        used_usd = usage_map.get(token.id, Decimal("0.00"))
        token_responses.append(build_token_response(token, used_usd))

    return token_responses


@router.get("/{token_id}", response_model=TokenResponse)
async def get_token(
    token_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Get token details by ID.

    - **token_id**: Token UUID

    Returns token details (without plain token key).
    """
    from uuid import UUID

    try:
        token_uuid = UUID(token_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token ID format",
        )

    token = await token_service.get_token_by_id(token_uuid)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    # Verify token belongs to current user
    if token.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    used_usd = await calculate_token_used_usd(token, db)
    return build_token_response(token, used_usd)


@router.put("/{token_id}", response_model=TokenResponse)
async def update_token(
    token_id: str,
    request: UpdateTokenRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Update token settings.

    - **token_id**: Token UUID
    - **name**: New token name
    - **expires_at**: New expiration datetime
    - **quota_usd**: New usage quota
    - **allowed_ips**: New IP restrictions
    - **allowed_models**: New model restrictions
    - **is_active**: New active status

    Returns updated token details.
    """
    from uuid import UUID

    try:
        token_uuid = UUID(token_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token ID format",
        )

    # Verify token exists and belongs to user
    token = await token_service.get_token_by_id(token_uuid)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    if token.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Validate token_metadata if provided
    if request.token_metadata is not None:
        try:
            validate_token_metadata(request.token_metadata)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Update token fields directly (avoid redundant query)
    if request.name is not None:
        token.name = request.name
    if request.expires_at is not None:
        token.expires_at = request.expires_at
    if request.quota_usd is not None:
        token.quota_usd = request.quota_usd
    if request.allowed_ips is not None:
        token.allowed_ips = request.allowed_ips
    if request.is_active is not None:
        token.is_active = request.is_active
    if request.token_metadata is not None:
        token.token_metadata = request.token_metadata

    await db.commit()
    await db.refresh(token)

    # For quota-only updates (like recharge), skip expensive aggregation query
    # Frontend will refresh to get accurate used_usd
    if request.quota_usd is not None and all(
        v is None
        for v in [
            request.name,
            request.expires_at,
            request.allowed_ips,
            request.is_active,
        ]
    ):
        # Fast path: only quota changed
        used_usd = Decimal("0.00")
    else:
        # Calculate for other updates
        used_usd = await calculate_token_used_usd(token, db)

    return build_token_response(token, used_usd)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    token_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
):
    """
    Delete (revoke) a token permanently.

    - **token_id**: Token UUID

    Permanently deletes the token. This action cannot be undone.
    """
    from uuid import UUID

    try:
        token_uuid = UUID(token_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token ID format",
        )

    # Verify token exists and belongs to user
    token = await token_service.get_token_by_id(token_uuid)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    if token.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Invalidate cache before deleting
    try:
        from app.core.redis import get_redis, RedisCache
        from app.core.security import hash_token
        from app.services.token_cache import CachedTokenService

        # Get plain token to calculate hash
        plain_token = await token_service.get_plain_token(token_uuid)
        if plain_token:
            token_hash = hash_token(plain_token)
            redis_client = await get_redis()
            cache = RedisCache(redis_client)
            cached_service = CachedTokenService(token_service.db, cache)
            await cached_service.invalidate_token_cache(token_hash)
    except Exception:
        # Continue even if cache invalidation fails
        pass

    # Delete token
    await token_service.delete_token(token_uuid)

    return None


@router.post("/{token_id}/revoke", response_model=TokenResponse)
async def revoke_token(
    token_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Revoke (deactivate) a token.

    - **token_id**: Token UUID

    Deactivates the token. Can be reactivated later via update endpoint.
    """
    from uuid import UUID

    try:
        token_uuid = UUID(token_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token ID format",
        )

    # Verify token exists and belongs to user
    token = await token_service.get_token_by_id(token_uuid)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    if token.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Revoke token
    await token_service.revoke_token(token_uuid)

    # Return updated token
    token = await token_service.get_token_by_id(token_uuid)
    used_usd = await calculate_token_used_usd(token, db)
    return build_token_response(token, used_usd)


@router.get("/{token_id}/plain", response_model=dict)
async def get_plain_token(
    token_id: str,
    current_user: User = Depends(get_current_user_from_jwt),
    token_service: TokenService = Depends(get_token_service),
):
    """
    Get the plain (decrypted) token value.

    - **token_id**: Token UUID

    Returns the decrypted token value for copying.
    """
    from uuid import UUID

    try:
        token_uuid = UUID(token_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token ID format",
        )

    # Verify token exists and belongs to user
    token = await token_service.get_token_by_id(token_uuid)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    if token.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    # Get plain token
    plain_token = await token_service.get_plain_token(token_uuid)
    if not plain_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to decrypt token",
        )

    return {"token": plain_token}
