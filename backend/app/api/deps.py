"""
API dependencies for authentication and authorization.
Provides dependency injection for database sessions, current user, and token validation.
"""

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError as JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_jwt_token
from app.models.token import APIToken
from app.models.user import User
from app.services.audit_log import AuditLogService
from app.services.auth import AuthService
from app.services.refresh_token import RefreshTokenService
from app.services.token import TokenService

# HTTP Bearer token scheme
security = HTTPBearer()
# Optional bearer for endpoints that support both JWT and API tokens
optional_security = HTTPBearer(auto_error=False)


async def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """
    Get authentication service instance.

    Args:
        db: Database session

    Returns:
        AuthService instance
    """
    return AuthService(db)


async def get_token_service(db: AsyncSession = Depends(get_db)) -> TokenService:
    """
    Get token service instance.

    Args:
        db: Database session

    Returns:
        TokenService instance
    """
    return TokenService(db)


async def get_refresh_token_service(
    db: AsyncSession = Depends(get_db),
) -> RefreshTokenService:
    """
    Get refresh token service instance.

    Args:
        db: Database session

    Returns:
        RefreshTokenService instance
    """
    return RefreshTokenService(db)


async def get_audit_log_service(db: AsyncSession = Depends(get_db)) -> AuditLogService:
    """
    Get audit log service instance.

    Args:
        db: Database session

    Returns:
        AuditLogService instance
    """
    return AuditLogService(db)


async def get_oauth_service(db: AsyncSession = Depends(get_db)):
    """
    Get OAuth service instance.

    Args:
        db: Database session

    Returns:
        OAuthService instance
    """
    from app.services.oauth import OAuthService

    return OAuthService(db)


async def get_current_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    token_service: TokenService = Depends(get_token_service),
) -> APIToken:
    """
    Validate API token and return token object.

    Uses Redis caching if available for improved performance.

    Checks:
    - Token exists and is active
    - Token is not expired
    - Token quota is not exceeded

    Args:
        credentials: HTTP Bearer credentials
        token_service: Token service instance

    Returns:
        Valid APIToken object

    Raises:
        HTTPException: If token is invalid or access is denied
    """
    plain_token = credentials.credentials

    # Try to use cached validation if Redis is available
    try:
        from app.core.redis import get_redis, RedisCache
        from app.services.token_cache import CachedTokenService

        redis_client = await get_redis()
        cache = RedisCache(redis_client)
        cached_service = CachedTokenService(token_service.db, cache)

        token = await cached_service.validate_token_cached(
            plain_token=plain_token,
        )
    except Exception:
        # Fallback to non-cached validation if Redis unavailable
        token = await token_service.validate_token(
            plain_token=plain_token,
        )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token


async def get_current_token_flexible(
    request: Request,
    token_service: TokenService = Depends(get_token_service),
) -> APIToken:
    """
    Validate API token from either Authorization: Bearer or x-api-key header.

    Supports both OpenAI-style (Bearer) and Anthropic-style (x-api-key) auth,
    enabling endpoints like /v1/models to work with both clients.
    """
    # Try x-api-key first (Anthropic SDK / Claude Code)
    api_key = request.headers.get("x-api-key")
    if not api_key:
        # Fall back to Authorization: Bearer (OpenAI SDK)
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            api_key = auth_header[7:]

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide via Authorization: Bearer or x-api-key header.",
        )

    # Validate token (same logic as other auth deps)
    try:
        from app.core.redis import get_redis, RedisCache
        from app.services.token_cache import CachedTokenService

        redis_client = await get_redis()
        cache = RedisCache(redis_client)
        cached_service = CachedTokenService(token_service.db, cache)
        token = await cached_service.validate_token_cached(plain_token=api_key)
    except Exception:
        token = await token_service.validate_token(plain_token=api_key)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    return token


async def get_current_token_from_api_key(
    x_api_key: str = Header(..., alias="x-api-key"),
    token_service: TokenService = Depends(get_token_service),
) -> APIToken:
    """
    Validate API token from x-api-key header (Anthropic SDK format).

    Anthropic SDK sends the token via x-api-key header instead of
    Authorization: Bearer.

    Args:
        x_api_key: API key from x-api-key header
        token_service: Token service instance

    Returns:
        Valid APIToken object

    Raises:
        HTTPException: If token is invalid or access is denied
    """
    plain_token = x_api_key

    # Try to use cached validation if Redis is available
    try:
        from app.core.redis import get_redis, RedisCache
        from app.services.token_cache import CachedTokenService

        redis_client = await get_redis()
        cache = RedisCache(redis_client)
        cached_service = CachedTokenService(token_service.db, cache)

        token = await cached_service.validate_token_cached(
            plain_token=plain_token,
        )
    except Exception:
        # Fallback to non-cached validation if Redis unavailable
        token = await token_service.validate_token(
            plain_token=plain_token,
        )

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    return token


async def get_current_token_from_gemini_key(
    request: Request,
    token_service: TokenService = Depends(get_token_service),
) -> APIToken:
    """
    Validate API token from Gemini SDK conventions.

    The Gemini SDK sends the API key via either:
    - Query parameter ``key`` (e.g. ``?key=TOKEN``)
    - Header ``x-goog-api-key``

    In the proxy context the "API key" is actually a proxy token.

    Args:
        request: FastAPI Request object
        token_service: Token service instance

    Returns:
        Valid APIToken object

    Raises:
        HTTPException: If token is invalid or access is denied
    """
    # Try query param first, then header
    plain_token = request.query_params.get("key")
    if not plain_token:
        plain_token = request.headers.get("x-goog-api-key")

    if not plain_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide via ?key= query parameter or x-goog-api-key header.",
        )

    # Validate (same logic as other auth deps)
    try:
        from app.core.redis import get_redis, RedisCache
        from app.services.token_cache import CachedTokenService

        redis_client = await get_redis()
        cache = RedisCache(redis_client)
        cached_service = CachedTokenService(token_service.db, cache)
        token = await cached_service.validate_token_cached(plain_token=plain_token)
    except Exception:
        token = await token_service.validate_token(plain_token=plain_token)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    return token


async def get_current_user_from_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """
    Get current user from JWT token (for web dashboard).

    Args:
        credentials: HTTP Bearer credentials with JWT token
        auth_service: Authentication service

    Returns:
        User object

    Raises:
        HTTPException: If token is invalid or user not found
    """
    token = credentials.credentials

    try:
        payload = decode_jwt_token(token)

        # Verify token type
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Get user ID
        user_id = UUID(payload.get("sub"))

    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user from database
    user = await auth_service.get_user_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return user


async def get_current_user(
    token: APIToken = Depends(get_current_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """
    Get current user from validated API token.

    Args:
        token: Validated API token
        auth_service: Authentication service

    Returns:
        User object

    Raises:
        HTTPException: If user not found or inactive
    """
    user = await auth_service.get_user_by_id(token.user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )

    return user


async def validate_token_for_model(
    model: str,
    token: APIToken = Depends(get_current_token),
    token_service: TokenService = Depends(get_token_service),
) -> APIToken:
    """
    Validate that token has access to specified model.

    Args:
        model: Model name to check
        token: Current API token
        token_service: Token service instance

    Returns:
        Validated token

    Raises:
        HTTPException: If token doesn't have access to model
    """
    if token.allowed_models and model not in token.allowed_models:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Token does not have access to model: {model}",
        )

    return token
