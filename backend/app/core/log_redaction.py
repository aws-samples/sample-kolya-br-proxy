"""Scrub secrets and personal identifiers from log output.

Applied by the root log handler's formatter, so every logger (ours and
third-party) goes through it:

- credentials embedded in URLs / DSNs (the ``user:password@`` part)
- gateway API keys (``sk-...``) and JWTs
- email addresses: the local part is masked, the domain kept for debugging
"""

import re
from typing import Any

_URL_CREDENTIALS = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^\s/@:]*:[^\s/@]+@"
)
_API_KEY = re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_EMAIL = re.compile(
    r"\b([A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]*@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"
)


def redact(text: Any) -> Any:
    """Return ``text`` with secrets masked; non-strings are returned as-is."""
    if not isinstance(text, str) or not text:
        return text
    text = _URL_CREDENTIALS.sub(r"\g<scheme>***@", text)
    text = _JWT.sub("[jwt]", text)
    text = _API_KEY.sub(lambda m: f"sk-***{m.group(0)[-4:]}", text)
    text = _EMAIL.sub(r"\1***@\2", text)
    return text


def redact_value(value: Any, depth: int = 0) -> Any:
    """Redact strings inside the ``extra={}`` values of a log record."""
    if depth > 5:
        return value
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v, depth + 1) for v in value]
    return value
