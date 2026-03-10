"""
Security middleware for CSRF and origin validation.
"""

import logging
from typing import List, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Security middleware for API protection.

    Provides:
    - Origin validation for state-changing operations
    - Referer checking
    - Custom header validation
    - Protection against CSRF attacks
    """

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: List[str],
        require_custom_header: bool = True,
        enforce_referer: bool = False,
    ):
        """
        Initialize security middleware.

        Args:
            app: ASGI application
            allowed_origins: List of allowed origins (domains)
            require_custom_header: Require X-Requested-With header for state-changing ops
            enforce_referer: Enforce referer checking (stricter, may break some clients)
        """
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)
        self.require_custom_header = require_custom_header
        self.enforce_referer = enforce_referer

        # Parse wildcard origins
        self.wildcard_origins = set()
        self.exact_origins = set()
        for origin in allowed_origins:
            if origin == "*":
                # Allow all origins
                self.exact_origins.add("*")
            elif "*" in origin:
                # Wildcard pattern (e.g., "*.example.com")
                self.wildcard_origins.add(origin.replace("*", ""))
            else:
                self.exact_origins.add(origin)

    def _is_origin_allowed(self, origin: Optional[str]) -> bool:
        """
        Check if origin is allowed.

        Args:
            origin: Origin header value

        Returns:
            True if origin is allowed
        """
        if not origin:
            return False

        # Allow all if "*" is configured
        if "*" in self.exact_origins:
            return True

        # Check exact match
        if origin in self.exact_origins:
            return True

        # Check wildcard match
        for wildcard in self.wildcard_origins:
            if origin.endswith(wildcard):
                return True

        return False

    def _is_safe_method(self, method: str) -> bool:
        """
        Check if HTTP method is safe (doesn't change state).

        Args:
            method: HTTP method

        Returns:
            True if method is safe
        """
        return method in ("GET", "HEAD", "OPTIONS")

    def _validate_referer(self, request: Request) -> bool:
        """
        Validate referer header.

        Args:
            request: FastAPI request

        Returns:
            True if referer is valid or not required
        """
        referer = request.headers.get("referer")

        if not referer:
            # No referer is OK if not enforcing
            return not self.enforce_referer

        # Extract origin from referer
        try:
            from urllib.parse import urlparse

            parsed = urlparse(referer)
            referer_origin = f"{parsed.scheme}://{parsed.netloc}"
            return self._is_origin_allowed(referer_origin)
        except Exception as e:
            logger.warning(f"Failed to parse referer: {e}")
            return False

    def _add_cors_headers(self, response: Response, origin: Optional[str]) -> Response:
        """
        Add CORS headers to response.

        Args:
            response: Response object
            origin: Origin header value

        Returns:
            Response with CORS headers
        """
        if origin and self._is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
        elif "*" in self.exact_origins:
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
        return response

    async def dispatch(self, request: Request, call_next) -> Response:
        """
        Process request through security checks.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response
        """
        method = request.method
        path = request.url.path

        # Skip security checks for health endpoints
        if path.startswith("/health"):
            return await call_next(request)

        # Skip security checks for OPTIONS (CORS preflight)
        if method == "OPTIONS":
            return await call_next(request)

        # Get origin header
        origin = request.headers.get("origin")

        # For state-changing operations (POST, PUT, DELETE, PATCH)
        if not self._is_safe_method(method):
            # 1. Check origin if present
            if origin and not self._is_origin_allowed(origin):
                logger.warning(
                    f"Blocked request from disallowed origin: {origin}",
                    extra={
                        "origin": origin,
                        "method": method,
                        "path": path,
                        "remote_addr": request.client.host if request.client else None,
                    },
                )
                response = JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "message": "Origin not allowed",
                            "type": "forbidden",
                            "code": "origin_not_allowed",
                        }
                    },
                )
                return self._add_cors_headers(response, origin)

            # 2. Validate referer if enforcing
            if self.enforce_referer and not self._validate_referer(request):
                logger.warning(
                    "Blocked request with invalid referer",
                    extra={
                        "referer": request.headers.get("referer"),
                        "method": method,
                        "path": path,
                    },
                )
                response = JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "message": "Invalid referer",
                            "type": "forbidden",
                            "code": "invalid_referer",
                        }
                    },
                )
                return self._add_cors_headers(response, origin)

            # 3. Check for custom header (CSRF protection for browser requests)
            # API clients using Bearer tokens don't need this
            # But browser-based requests should include X-Requested-With
            if self.require_custom_header and origin:
                # Only require custom header if Origin is present (browser request)
                has_auth_header = request.headers.get("authorization")
                has_custom_header = request.headers.get("x-requested-with")

                # Require either:
                # a) Authorization header (API client), OR
                # b) X-Requested-With header (AJAX request)
                if not has_auth_header and not has_custom_header:
                    logger.warning(
                        "Blocked browser request without CSRF protection header",
                        extra={
                            "origin": origin,
                            "method": method,
                            "path": path,
                        },
                    )
                    response = JSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "message": "Missing required header for browser requests",
                                "type": "forbidden",
                                "code": "missing_csrf_header",
                            }
                        },
                    )
                    return self._add_cors_headers(response, origin)

        # Add security headers to response
        response = await call_next(request)

        # Add security response headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Add CSP for API (restrictive)
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none';"
        )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple rate limiting middleware (placeholder for future implementation).

    For production, consider using:
    - slowapi (https://github.com/laurentS/slowapi)
    - fastapi-limiter (https://github.com/long2ice/fastapi-limiter)
    - Redis-based rate limiting
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request (currently pass-through)."""
        # TODO: Implement rate limiting
        # For now, just pass through
        return await call_next(request)
