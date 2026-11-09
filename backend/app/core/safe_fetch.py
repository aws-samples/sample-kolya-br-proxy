"""Fetch caller-supplied URLs without reaching internal addresses.

The gateway runs inside the VPC, so a URL taken from a request body could
otherwise target cluster services, VPC hosts or link-local metadata
endpoints. Every fetch here:

- accepts only http/https,
- resolves the host once and refuses unless every address is globally
  routable, then connects to that exact address (no DNS rebinding window),
- does not follow redirects,
- streams the body and stops at a byte cap, under one overall deadline.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx


class UnsafeURLError(ValueError):
    """The URL was refused or could not be fetched within limits."""


async def _resolve_public(host: str, port: int) -> str:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as e:
        raise UnsafeURLError("host does not resolve") from e
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise UnsafeURLError("host does not resolve")
    for addr in addresses:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UnsafeURLError("host resolves to a non-public address")
    # Prefer IPv4: not every node has IPv6 egress.
    return sorted(addresses, key=lambda a: (":" in a, a))[0]


async def fetch_public_url(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 20.0,
    content_type_prefix: str | None = None,
) -> tuple[bytes, str]:
    """Return (body, content_type) for a public http(s) URL."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UnsafeURLError("only http and https URLs are allowed")
    host = parts.hostname
    port = parts.port or (443 if parts.scheme == "https" else 80)

    async def _fetch() -> tuple[bytes, str]:
        ip = await _resolve_public(host, port)
        ip_host = f"[{ip}]" if ":" in ip else ip
        netloc = f"{ip_host}:{parts.port}" if parts.port else ip_host
        pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
        host_header = f"{host}:{parts.port}" if parts.port else host
        async with httpx.AsyncClient(follow_redirects=False, timeout=10) as client:
            async with client.stream(
                "GET",
                pinned,
                headers={"Host": host_header},
                # Certificate and SNI still use the original hostname.
                extensions={"sni_hostname": host},
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise UnsafeURLError(f"upstream returned {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if content_type_prefix and not content_type.startswith(
                    content_type_prefix
                ):
                    raise UnsafeURLError("unexpected content type")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise UnsafeURLError("response too large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise UnsafeURLError("response too large")
                return bytes(body), content_type

    try:
        return await asyncio.wait_for(_fetch(), timeout=timeout)
    except UnsafeURLError:
        raise
    except asyncio.TimeoutError as e:
        raise UnsafeURLError("fetch timed out") from e
    except httpx.HTTPError as e:
        raise UnsafeURLError("fetch failed") from e
