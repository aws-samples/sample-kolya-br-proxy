"""Keep idle streaming responses alive.

Upstream models can go quiet for a long time mid-stream: Bedrock buffers
large tool_use arguments (a multi-thousand-word ``write`` call stalls for
30s+ between ``input_json_delta`` chunks). Heartbeats sent from inside the
``async for`` body only fire when an upstream event arrives, so during that
silence no bytes reach the client and any proxy with a 60s idle timeout
cuts the connection (clients see ``terminated``).

``with_heartbeat`` wraps the upstream iterator and yields ``HEARTBEAT``
whenever nothing arrived for ``interval`` seconds, without cancelling the
pending upstream read.
"""

import asyncio
import contextlib
from typing import AsyncIterable, AsyncIterator, TypeVar, Union

T = TypeVar("T")


class _Heartbeat:
    __slots__ = ()

    def __repr__(self) -> str:
        return "HEARTBEAT"


HEARTBEAT = _Heartbeat()


async def with_heartbeat(
    source: AsyncIterable[T], interval: float
) -> AsyncIterator[Union[T, _Heartbeat]]:
    """Yield items from ``source``, plus ``HEARTBEAT`` after each idle ``interval``."""
    it = source.__aiter__()
    if interval <= 0:
        async for item in it:
            yield item
        return
    pending: asyncio.Future = asyncio.ensure_future(it.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield HEARTBEAT
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            yield item
            pending = asyncio.ensure_future(it.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
            with contextlib.suppress(
                asyncio.CancelledError, StopAsyncIteration, Exception
            ):
                await pending
        aclose = getattr(it, "aclose", None)
        if aclose is not None:
            with contextlib.suppress(Exception):
                await aclose()
