# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
"""Data-plane fixes from the code review.

- image_url fetches refuse non-public addresses, redirects and big bodies
- request bodies are capped before handlers buffer them
- per-key allowed_ips is enforced using the ALB-appended client IP
- revoke/delete drop the auth cache only after the DB write
"""

import socket
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api import deps
from app.core import safe_fetch
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.services.token import TokenService

# --- safe_fetch -------------------------------------------------------------


def _fake_dns(monkeypatch, addresses):
    async def _getaddrinfo(host, port, type=0):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses
        ]

    class _Loop:
        getaddrinfo = staticmethod(_getaddrinfo)

    monkeypatch.setattr(safe_fetch.asyncio, "get_running_loop", lambda: _Loop())


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.1.5",
        "172.20.0.10",
        "192.168.1.1",
        "169.254.169.254",
        "169.254.170.23",
        "100.64.0.1",
        "::1",
        "fd00::1",
        "::ffff:10.0.0.1",
    ],
)
@pytest.mark.asyncio
async def test_non_public_addresses_refused(monkeypatch, address):
    _fake_dns(monkeypatch, [address])
    with pytest.raises(safe_fetch.UnsafeURLError, match="non-public"):
        await safe_fetch.fetch_public_url("http://evil.example/x.png", max_bytes=10)


@pytest.mark.asyncio
async def test_mixed_public_and_private_answers_refused(monkeypatch):
    _fake_dns(monkeypatch, ["93.184.216.34", "10.0.0.1"])
    with pytest.raises(safe_fetch.UnsafeURLError):
        await safe_fetch.fetch_public_url("http://evil.example/x.png", max_bytes=10)


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "gopher://x/", "ftp://x/a", "http:///nohost"]
)
@pytest.mark.asyncio
async def test_bad_schemes_refused(url):
    with pytest.raises(safe_fetch.UnsafeURLError):
        await safe_fetch.fetch_public_url(url, max_bytes=10)


def _mock_upstream(monkeypatch, handler):
    seen = {}
    real_client = httpx.AsyncClient

    def _client(**kwargs):
        seen.update(kwargs)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(safe_fetch.httpx, "AsyncClient", _client)
    return seen


@pytest.mark.asyncio
async def test_connects_to_resolved_ip_with_original_host(monkeypatch):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "image/png"}, content=b"img"
        )

    seen = _mock_upstream(monkeypatch, handler)
    body, ctype = await safe_fetch.fetch_public_url(
        "https://cdn.example/a.png?x=1", max_bytes=100, content_type_prefix="image/"
    )
    assert (body, ctype) == (b"img", "image/png")
    assert seen["follow_redirects"] is False
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "cdn.example"
    assert requests[0].extensions["sni_hostname"] == "cdn.example"


@pytest.mark.asyncio
async def test_redirect_not_followed(monkeypatch):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    _mock_upstream(
        monkeypatch,
        lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/"}),
    )
    with pytest.raises(safe_fetch.UnsafeURLError, match="302"):
        await safe_fetch.fetch_public_url("http://cdn.example/a", max_bytes=100)


@pytest.mark.asyncio
async def test_body_over_cap_refused(monkeypatch):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    _mock_upstream(
        monkeypatch,
        lambda r: httpx.Response(
            200, headers={"content-type": "image/png"}, content=b"x" * 1000
        ),
    )
    with pytest.raises(safe_fetch.UnsafeURLError, match="too large"):
        await safe_fetch.fetch_public_url("http://cdn.example/a", max_bytes=100)


@pytest.mark.asyncio
async def test_non_image_refused(monkeypatch):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    _mock_upstream(
        monkeypatch,
        lambda r: httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"<html>"
        ),
    )
    with pytest.raises(safe_fetch.UnsafeURLError, match="content type"):
        await safe_fetch.fetch_public_url(
            "http://cdn.example/a", max_bytes=100, content_type_prefix="image/"
        )


@pytest.mark.asyncio
async def test_translator_surfaces_refusal_as_value_error(monkeypatch):
    from app.services.translator import RequestTranslator

    _fake_dns(monkeypatch, ["10.0.0.1"])
    with pytest.raises(ValueError):
        await RequestTranslator._fetch_and_encode_image("http://internal.svc/x.png")


# --- body size limit --------------------------------------------------------


def _app(limit):
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request):
        return {"n": len(await request.body())}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=limit)
    return TestClient(app)


def test_body_under_limit_passes():
    assert _app(100).post("/echo", content=b"x" * 100).json() == {"n": 100}


def test_declared_body_over_limit_rejected():
    response = _app(100).post("/echo", content=b"x" * 101)
    assert response.status_code == 413
    assert response.json()["error"]["type"] == "request_too_large"


def test_chunked_body_over_limit_rejected():
    def chunks():
        for _ in range(5):
            yield b"x" * 50

    response = _app(100).post("/echo", content=chunks())
    assert response.status_code == 413


# --- client IP / allowed_ips ------------------------------------------------


def _request(xff=None, peer="10.0.0.9"):
    headers = {"x-forwarded-for": xff} if xff else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


def test_client_ip_is_alb_appended_entry():
    # Client forged the first entry; the ALB appended the real address.
    assert (
        deps.client_ip_from_request(_request("1.1.1.1, 203.0.113.7")) == "203.0.113.7"
    )


def test_client_ip_falls_back_to_peer():
    assert deps.client_ip_from_request(_request()) == "10.0.0.9"


class _OneToken:
    def __init__(self, token):
        self._token = token

    async def execute(self, _stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self._token)

    def add(self, _obj):
        pass


def _key(allowed_ips):
    return SimpleNamespace(
        id="t",
        allowed_ips=allowed_ips,
        is_expired=False,
        is_quota_exceeded=False,
        last_used_at=None,
    )


@pytest.mark.parametrize(
    "allowed,ip,ok",
    [
        ([], "198.51.100.1", True),
        (None, None, True),
        (["203.0.113.0/24"], "203.0.113.7", True),
        (["203.0.113.0/24"], "198.51.100.1", False),
        (["203.0.113.0/24"], None, False),
    ],
)
@pytest.mark.asyncio
async def test_allowed_ips_enforced_only_when_configured(allowed, ip, ok):
    service = TokenService(_OneToken(_key(allowed)))
    result = await service.validate_token("sk-x", client_ip=ip)
    assert (result is not None) is ok


@pytest.mark.asyncio
async def test_dependency_passes_client_ip(monkeypatch):
    captured = {}

    async def _validate(_service, _token, client_ip=None):
        captured["ip"] = client_ip
        return SimpleNamespace(name="n", id="i")

    monkeypatch.setattr(deps, "_validate_token_with_cache", _validate)
    request = _request("203.0.113.7")
    credentials = SimpleNamespace(credentials="sk-x")
    await deps.get_current_token(request, credentials, token_service=None)
    assert captured["ip"] == "203.0.113.7"


# --- cache invalidation order -----------------------------------------------


@pytest.mark.parametrize("op", ["revoke", "delete"])
@pytest.mark.asyncio
async def test_cache_dropped_after_db_write(monkeypatch, op):
    from app.api.admin.endpoints import tokens

    calls = []
    token = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        user_id="me",
        token_hash="h",
        name="n",
    )

    async def _invalidate(_h):
        calls.append("cache")

    async def _write(_id):
        calls.append("db")

    async def _get(_id):
        return token

    async def _not_team(*_a):
        return False

    async def _log(**_k):
        return None

    monkeypatch.setattr(tokens, "_invalidate_token_cache", _invalidate)
    monkeypatch.setattr(tokens, "_is_team_key", _not_team)

    async def _usage(*_a):
        return SimpleNamespace(total=0, monthly=0, daily=0)

    monkeypatch.setattr(tokens, "calculate_token_usage", _usage)
    monkeypatch.setattr(tokens, "build_token_response", lambda *a, **k: None)
    service = SimpleNamespace(
        get_token_by_id=_get, revoke_token=_write, delete_token=_write
    )
    user = SimpleNamespace(id="me", role=None, permissions={})
    audit = SimpleNamespace(log=_log)
    fn = tokens.revoke_token if op == "revoke" else tokens.delete_token
    kwargs = dict(
        token_id=token.id,
        current_user=user,
        token_service=service,
        audit_service=audit,
    )
    if "db" in fn.__code__.co_varnames[: fn.__code__.co_argcount]:
        kwargs["db"] = None
    await fn(**kwargs)
    assert calls == ["db", "cache"]
