"""
Pure ASGI observability middleware — streaming-safe.

Emits high-level HTTP metrics (duration, status code) for every request.
Does NOT use ``BaseHTTPMiddleware`` which would buffer ``StreamingResponse``.
"""

import time

from app.core.metrics import emit_http_metrics, is_metrics_enabled


class ObservabilityMiddleware:
    """ASGI middleware that emits HTTP-level metrics for all requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

        # Skip health checks — they are high-frequency noise
        if path.startswith("/health"):
            return await self.app(scope, receive, send)

        if not is_metrics_enabled():
            return await self.app(scope, receive, send)

        method = scope.get("method", "UNKNOWN")
        start = time.time()
        status_code = 200

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.time() - start
            try:
                await emit_http_metrics(
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_s=round(duration, 3),
                )
            except Exception:
                pass  # never let metrics fail a request
