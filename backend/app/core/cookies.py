"""
Cookie utilities for secure refresh token storage.

Refresh tokens are stored in HttpOnly cookies to prevent XSS theft.
The cookie is scoped to /admin/auth paths only, so it does not pollute
other API requests (e.g., /v1/*).

Cross-origin setup (kbp.kolya.fun <-> api.kbp.kolya.fun) requires
SameSite=None + Secure. Local development uses SameSite=Lax over HTTP.
"""

import hmac
import os

from fastapi import Request
from fastapi.responses import Response

from app.core.config import get_settings

REFRESH_TOKEN_COOKIE = "kbr_refresh_token"
REFRESH_TOKEN_PATH = "/admin/auth"


def _is_local_env() -> bool:
    return os.getenv("KBR_ENV", "non-prod") == "local"


def set_refresh_token_cookie(response: Response, token: str) -> None:
    """Set the refresh token as an HttpOnly cookie on the response."""
    settings = get_settings()
    is_local = _is_local_env()

    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=not is_local,
        samesite="none" if not is_local else "lax",
        path=REFRESH_TOKEN_PATH,
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400,
    )


def clear_refresh_token_cookie(response: Response) -> None:
    """Clear the refresh token cookie."""
    is_local = _is_local_env()

    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path=REFRESH_TOKEN_PATH,
        httponly=True,
        secure=not is_local,
        samesite="none" if not is_local else "lax",
    )


def get_refresh_token_from_cookie(request: Request) -> str | None:
    """Read the refresh token from the request cookie."""
    return request.cookies.get(REFRESH_TOKEN_COOKIE)


# Ties an OAuth callback to the browser that started the login. The state
# row in the database proves the state was issued; this cookie proves it was
# issued to *this* browser, so a page on another site cannot replay a state
# (and code) minted for someone else - login CSRF.
OAUTH_STATE_COOKIE = "kbr_oauth_state"
OAUTH_STATE_MAX_AGE = 600  # matches the OAuthState row lifetime


def set_oauth_state_cookie(response: Response, state: str) -> None:
    is_local = _is_local_env()
    response.set_cookie(
        key=OAUTH_STATE_COOKIE,
        value=state,
        httponly=True,
        secure=not is_local,
        samesite="none" if not is_local else "lax",
        path=REFRESH_TOKEN_PATH,
        max_age=OAUTH_STATE_MAX_AGE,
    )


def clear_oauth_state_cookie(response: Response) -> None:
    is_local = _is_local_env()
    response.delete_cookie(
        key=OAUTH_STATE_COOKIE,
        path=REFRESH_TOKEN_PATH,
        httponly=True,
        secure=not is_local,
        samesite="none" if not is_local else "lax",
    )


def oauth_state_matches_cookie(request: Request, state: str) -> bool:
    cookie = request.cookies.get(OAUTH_STATE_COOKIE) or ""
    return bool(cookie) and hmac.compare_digest(cookie, state)
