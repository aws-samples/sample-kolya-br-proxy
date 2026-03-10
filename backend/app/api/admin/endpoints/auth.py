"""
Authentication endpoints for user registration and login.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_audit_log_service,
    get_auth_service,
    get_current_user_from_jwt,
    get_refresh_token_service,
)
from app.core.database import get_db
from app.core.security import create_access_token, decode_jwt_token
from app.models.user import User
from app.services.audit_log import AuditLogService
from app.services.auth import AuthService
from app.services.cognito_oauth import get_cognito_oauth_service
from app.services.microsoft_oauth import get_microsoft_oauth_service
from app.services.refresh_token import RefreshTokenService

router = APIRouter()
logger = logging.getLogger(__name__)


class UserResponse(BaseModel):
    """User response model."""

    id: str
    email: str
    first_name: str | None
    last_name: str | None
    is_active: bool
    is_admin: bool
    email_verified: bool
    current_balance: str

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Login response with JWT tokens."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    """Refresh token request."""

    refresh_token: str


class RevokeTokenRequest(BaseModel):
    """Revoke refresh token request."""

    refresh_token: str


@router.post("/refresh", response_model=LoginResponse)
async def refresh_access_token(
    request_body: RefreshTokenRequest,
    http_request: Request,
    refresh_token_service: RefreshTokenService = Depends(get_refresh_token_service),
    audit_log_service: AuditLogService = Depends(get_audit_log_service),
):
    """
    Refresh access token using refresh token with automatic rotation.

    - **refresh_token**: JWT refresh token

    Returns new access token and refresh token.
    Implements token rotation - old token is invalidated, new one issued.
    """
    # Get client info for audit
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    try:
        # Verify token type from JWT
        payload = decode_jwt_token(request_body.refresh_token)

        if payload.get("type") != "refresh":
            await audit_log_service.log_token_refresh_failed(
                ip_address=ip_address,
                user_agent=user_agent,
                error_message="Invalid token type",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )

        # Validate and rotate token (with theft detection)
        (
            new_refresh_token,
            user,
            error,
        ) = await refresh_token_service.validate_and_rotate_token(
            jwt_token=request_body.refresh_token,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        if error:
            await audit_log_service.log_token_refresh_failed(
                ip_address=ip_address,
                user_agent=user_agent,
                error_message=error,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error,
            )

        # Log successful refresh
        await audit_log_service.log_token_refresh_success(
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Create new access token
        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email}
        )

        return LoginResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            user=UserResponse(
                id=str(user.id),
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                is_active=user.is_active,
                is_admin=user.is_admin,
                email_verified=user.email_verified,
                current_balance=str(user.current_balance),
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        await audit_log_service.log_token_refresh_failed(
            ip_address=ip_address,
            user_agent=user_agent,
            error_message=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )


@router.post("/revoke")
async def revoke_refresh_token(
    request_body: RevokeTokenRequest,
    refresh_token_service: RefreshTokenService = Depends(get_refresh_token_service),
):
    """
    Revoke a specific refresh token.

    - **refresh_token**: JWT refresh token to revoke

    This invalidates the specific token. Use /revoke-all to logout from all devices.
    """
    from app.core.security import hash_refresh_token

    try:
        token_hash = hash_refresh_token(request_body.refresh_token)
        revoked = await refresh_token_service.revoke_token(
            token_hash, reason="User requested revocation"
        )

        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Refresh token not found",
            )

        return {"message": "Refresh token revoked successfully"}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to revoke refresh token",
        )


@router.post("/revoke-all")
async def revoke_all_refresh_tokens(
    http_request: Request,
    current_user: User = Depends(get_current_user_from_jwt),
    refresh_token_service: RefreshTokenService = Depends(get_refresh_token_service),
    audit_log_service: AuditLogService = Depends(get_audit_log_service),
):
    """
    Revoke all refresh tokens for current user (logout from all devices).

    Requires valid JWT access token in Authorization header.
    This invalidates all refresh tokens, forcing re-authentication on all devices.
    """
    count = await refresh_token_service.revoke_all_user_tokens(
        current_user.id, reason="User requested logout from all devices"
    )

    # Log the logout from all devices
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")
    await audit_log_service.log_logout_all_devices(
        user=current_user,
        token_count=count,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return {"message": f"Revoked {count} refresh tokens successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user_from_jwt),
):
    """
    Get current user information from JWT token.

    Requires valid JWT access token in Authorization header.
    """
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        is_active=current_user.is_active,
        is_admin=current_user.is_admin,
        email_verified=current_user.email_verified,
        current_balance=str(current_user.current_balance),
    )


class UpdateProfileRequest(BaseModel):
    """Update user profile request."""

    first_name: str | None = None
    last_name: str | None = None


@router.put("/me", response_model=UserResponse)
async def update_profile(
    request: UpdateProfileRequest,
    current_user: User = Depends(get_current_user_from_jwt),
    db: AsyncSession = Depends(get_db),
):
    """
    Update current user profile.

    - **first_name**: Optional first name
    - **last_name**: Optional last name

    Requires valid JWT access token.
    """
    # Update user fields
    if request.first_name is not None:
        current_user.first_name = request.first_name
    if request.last_name is not None:
        current_user.last_name = request.last_name

    await db.commit()
    await db.refresh(current_user)

    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        is_active=current_user.is_active,
        is_admin=current_user.is_admin,
        email_verified=current_user.email_verified,
        current_balance=str(current_user.current_balance),
    )


@router.get("/microsoft/login")
async def microsoft_login(
    redirect_uri: str,
    oauth_service_dep=None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get Microsoft OAuth login URL.

    - **redirect_uri**: Redirect URI after authorization

    Generates a secure state parameter and returns authorization URL.
    """
    from app.services.oauth import OAuthService

    oauth_service = get_microsoft_oauth_service()

    if not oauth_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Microsoft OAuth not configured",
        )

    # Generate and store state
    oauth_state_service = OAuthService(db)
    state = await oauth_state_service.generate_state("microsoft")

    auth_url = oauth_service.get_authorization_url(redirect_uri, state)
    return {"authorization_url": auth_url, "state": state}


@router.post("/microsoft/callback", response_model=LoginResponse)
async def microsoft_callback(
    code: str,
    redirect_uri: str,
    state: str,
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    refresh_token_service: RefreshTokenService = Depends(get_refresh_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle Microsoft OAuth callback.

    - **code**: Authorization code from Microsoft
    - **redirect_uri**: Redirect URI used in authorization
    - **state**: State parameter for CSRF protection

    Creates or logs in user with Microsoft account.
    """
    # Validate state parameter (CSRF protection)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing state parameter",
        )

    # Verify state against database
    from app.services.oauth import OAuthService

    oauth_state_service = OAuthService(db)
    if not await oauth_state_service.validate_state(state, "microsoft"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired state parameter",
        )

    oauth_service = get_microsoft_oauth_service()

    # Exchange code for token
    token_response = await oauth_service.exchange_code_for_token(code, redirect_uri)
    access_token = token_response.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get access token",
        )

    # Get user info from Microsoft
    user_info = await oauth_service.get_user_info(access_token)

    microsoft_id = user_info.get("id")
    email = user_info.get("mail") or user_info.get("userPrincipalName")
    first_name = user_info.get("givenName")
    last_name = user_info.get("surname")

    if not microsoft_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user information from Microsoft",
        )

    # Check if user exists with this Microsoft ID
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.microsoft_id == microsoft_id))
    user = result.scalar_one_or_none()

    if user:
        # Existing Microsoft user - log successful login
        client_ip = http_request.client.host if http_request.client else "unknown"
        logger.info(
            "MICROSOFT_LOGIN: Existing Microsoft user login",
            extra={
                "event_type": "microsoft_login",
                "user_id": str(user.id),
                "email": user.email,
                "microsoft_id": microsoft_id,
                "client_ip": client_ip,
                "user_agent": http_request.headers.get("user-agent", "unknown"),
            },
        )

    if not user:
        # Check if user exists with this email
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            # Link Microsoft account to existing user
            from app.models.user import AuthMethod

            # Log account linking for audit trail
            client_ip = http_request.client.host if http_request.client else "unknown"
            logger.warning(
                "ACCOUNT_LINKING: Microsoft account linked to existing user",
                extra={
                    "event_type": "account_linking",
                    "user_id": str(user.id),
                    "email": email,
                    "microsoft_id": microsoft_id,
                    "previous_auth_method": user.auth_method.value
                    if user.auth_method
                    else None,
                    "new_auth_method": "microsoft",
                    "client_ip": client_ip,
                    "user_agent": http_request.headers.get("user-agent", "unknown"),
                },
            )

            user.microsoft_id = microsoft_id
            user.auth_method = AuthMethod.MICROSOFT
            if not user.first_name:
                user.first_name = first_name
            if not user.last_name:
                user.last_name = last_name
            user.email_verified = True  # Microsoft accounts are pre-verified
            await db.commit()
            await db.refresh(user)

            logger.info(
                f"Microsoft account successfully linked to user {user.id} ({email})"
            )
        else:
            # Create new user
            from decimal import Decimal

            from app.core.config import get_settings
            from app.models.user import AuthMethod

            settings = get_settings()

            user = User(
                email=email,
                password_hash=None,  # No password for OAuth users
                auth_method=AuthMethod.MICROSOFT,
                microsoft_id=microsoft_id,
                first_name=first_name,
                last_name=last_name,
                current_balance=Decimal(str(settings.INITIAL_USER_BALANCE_USD)),
                is_active=True,
                email_verified=True,  # Microsoft accounts are pre-verified
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

            # Log new user registration
            client_ip = http_request.client.host if http_request.client else "unknown"
            logger.info(
                "NEW_USER_REGISTRATION: New user created via Microsoft OAuth",
                extra={
                    "event_type": "user_registration",
                    "user_id": str(user.id),
                    "email": email,
                    "microsoft_id": microsoft_id,
                    "auth_method": "microsoft",
                    "client_ip": client_ip,
                    "user_agent": http_request.headers.get("user-agent", "unknown"),
                },
            )

    # Update last login
    from datetime import datetime

    user.last_login_at = datetime.utcnow()
    await db.commit()

    # Get client info for audit
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    # Create JWT tokens with rotation support
    access_token_jwt = create_access_token(
        data={"sub": str(user.id), "email": user.email}
    )
    refresh_token_jwt, _ = await refresh_token_service.create_refresh_token(
        user=user, ip_address=ip_address, user_agent=user_agent
    )

    return LoginResponse(
        access_token=access_token_jwt,
        refresh_token=refresh_token_jwt,
        token_type="bearer",
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
            email_verified=user.email_verified,
            current_balance=str(user.current_balance),
        ),
    )


@router.get("/cognito/login")
async def cognito_login(
    redirect_uri: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Get AWS Cognito OAuth login URL.

    - **redirect_uri**: Redirect URI after authorization

    Generates a secure state parameter and returns authorization URL.
    """
    from app.services.oauth import OAuthService

    oauth_service = get_cognito_oauth_service()

    if not oauth_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Cognito OAuth not configured",
        )

    # Generate and store state
    oauth_state_service = OAuthService(db)
    state = await oauth_state_service.generate_state("cognito")

    auth_url = oauth_service.get_authorization_url(redirect_uri, state)
    return {"authorization_url": auth_url, "state": state}


@router.post("/cognito/callback", response_model=LoginResponse)
async def cognito_callback(
    code: str,
    redirect_uri: str,
    state: str,
    http_request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    refresh_token_service: RefreshTokenService = Depends(get_refresh_token_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Handle AWS Cognito OAuth callback.

    - **code**: Authorization code from Cognito
    - **redirect_uri**: Redirect URI used in authorization
    - **state**: State parameter for CSRF protection

    Creates or logs in user with Cognito account.
    """
    # Validate state parameter (CSRF protection)
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing state parameter",
        )

    # Verify state against database
    from app.services.oauth import OAuthService

    oauth_state_service = OAuthService(db)
    if not await oauth_state_service.validate_state(state, "cognito"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired state parameter",
        )

    oauth_service = get_cognito_oauth_service()

    # Exchange code for token
    token_response = await oauth_service.exchange_code_for_token(code, redirect_uri)
    access_token = token_response.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get access token",
        )

    # Get user info from Cognito
    user_info = await oauth_service.get_user_info(access_token)

    cognito_sub = user_info.get("sub")
    email = user_info.get("email")
    # Cognito might provide given_name/family_name or name
    first_name = (
        user_info.get("given_name") or user_info.get("name", "").split()[0]
        if user_info.get("name")
        else None
    )
    last_name = user_info.get("family_name") or (
        user_info.get("name", "").split()[1]
        if len(user_info.get("name", "").split()) > 1
        else None
    )

    if not cognito_sub or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to get user information from Cognito",
        )

    # Check if user exists with this email
    from sqlalchemy import select

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user:
        # Link Cognito account to existing user if not already linked
        from app.models.user import AuthMethod

        client_ip = http_request.client.host if http_request.client else "unknown"

        if user.auth_method != AuthMethod.COGNITO:
            # Log account linking for audit trail
            logger.warning(
                "ACCOUNT_LINKING: Cognito account linked to existing user",
                extra={
                    "event_type": "account_linking",
                    "user_id": str(user.id),
                    "email": email,
                    "cognito_sub": cognito_sub,
                    "previous_auth_method": user.auth_method.value
                    if user.auth_method
                    else None,
                    "new_auth_method": "cognito",
                    "client_ip": client_ip,
                    "user_agent": http_request.headers.get("user-agent", "unknown"),
                },
            )

            user.auth_method = AuthMethod.COGNITO
            if not user.first_name:
                user.first_name = first_name
            if not user.last_name:
                user.last_name = last_name
            user.email_verified = True  # Cognito accounts are pre-verified
            await db.commit()
            await db.refresh(user)

            logger.info(
                f"Cognito account successfully linked to user {user.id} ({email})"
            )
        else:
            # Existing Cognito user - log successful login
            logger.info(
                "COGNITO_LOGIN: Existing Cognito user login",
                extra={
                    "event_type": "cognito_login",
                    "user_id": str(user.id),
                    "email": email,
                    "cognito_sub": cognito_sub,
                    "client_ip": client_ip,
                    "user_agent": http_request.headers.get("user-agent", "unknown"),
                },
            )
    else:
        # Create new user
        from decimal import Decimal

        from app.core.config import get_settings
        from app.models.user import AuthMethod

        settings = get_settings()

        user = User(
            email=email,
            password_hash=None,  # No password for OAuth users
            auth_method=AuthMethod.COGNITO,
            first_name=first_name,
            last_name=last_name,
            current_balance=Decimal(str(settings.INITIAL_USER_BALANCE_USD)),
            is_active=True,
            email_verified=True,  # Cognito accounts are pre-verified
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        # Log new user registration
        client_ip = http_request.client.host if http_request.client else "unknown"
        logger.info(
            "NEW_USER_REGISTRATION: New user created via Cognito OAuth",
            extra={
                "event_type": "user_registration",
                "user_id": str(user.id),
                "email": email,
                "cognito_sub": cognito_sub,
                "auth_method": "cognito",
                "client_ip": client_ip,
                "user_agent": http_request.headers.get("user-agent", "unknown"),
            },
        )

    # Update last login
    from datetime import datetime

    user.last_login_at = datetime.utcnow()
    await db.commit()

    # Get client info for audit
    ip_address = http_request.client.host if http_request.client else None
    user_agent = http_request.headers.get("user-agent")

    # Create JWT tokens with rotation support
    access_token_jwt = create_access_token(
        data={"sub": str(user.id), "email": user.email}
    )
    refresh_token_jwt, _ = await refresh_token_service.create_refresh_token(
        user=user, ip_address=ip_address, user_agent=user_agent
    )

    return LoginResponse(
        access_token=access_token_jwt,
        refresh_token=refresh_token_jwt,
        token_type="bearer",
        user=UserResponse(
            id=str(user.id),
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            is_active=user.is_active,
            is_admin=user.is_admin,
            email_verified=user.email_verified,
            current_balance=str(user.current_balance),
        ),
    )
