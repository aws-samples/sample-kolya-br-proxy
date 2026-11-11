"""Treat requests the ALB received over HTTPS as HTTPS, and say so.

TLS ends at the ALB, so uvicorn sees plain HTTP and Starlette builds
absolute URLs - notably the trailing-slash 307 redirect - with ``http://``.
A client that follows that redirect re-sends its API key and body in
cleartext. The ALB always overwrites ``X-Forwarded-Proto`` with the scheme
it actually received, so only that header is trusted here; client
addresses are still taken from ``X-Forwarded-For`` by
``client_ip_from_request``, not rewritten.

HTTPS responses also carry HSTS so browsers never try plain HTTP again.
"""

HSTS_VALUE = b"max-age=31536000"


class HttpsSchemeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        proto = None
        for name, value in scope.get("headers", []):
            if name == b"x-forwarded-proto":
                # The ALB appends; the last hop's value is the one it saw.
                proto = value.decode("latin-1").split(",")[-1].strip().lower()
        if proto != "https":
            await self.app(scope, receive, send)
            return

        scope = dict(scope, scheme="https")

        async def send_with_hsts(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(
                    k.lower() == b"strict-transport-security" for k, _ in headers
                ):
                    headers.append((b"strict-transport-security", HSTS_VALUE))
                message = dict(message, headers=headers)
            await send(message)

        await self.app(scope, receive, send_with_hsts)
