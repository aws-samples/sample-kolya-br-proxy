"""Reject request bodies above a fixed size before handlers buffer them.

FastAPI reads the whole body into memory to parse JSON, so without a cap a
single request can exhaust a pod. Declared Content-Length is checked up
front; chunked bodies are counted as they stream in.
"""

import json

from app.core.config import get_settings


class RequestTooLarge(Exception):
    pass


async def _send_413(send, limit: int) -> None:
    body = json.dumps(
        {
            "error": {
                "message": f"Request body exceeds {limit} bytes",
                "type": "request_too_large",
            }
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    def __init__(self, app, max_bytes: int | None = None):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        limit = self.max_bytes or get_settings().MAX_REQUEST_BODY_BYTES
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > limit:
                    return await _send_413(send, limit)

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except RequestTooLarge:
            if not response_started:
                await _send_413(send, limit)
