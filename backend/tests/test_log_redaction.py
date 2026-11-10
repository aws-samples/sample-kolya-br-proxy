"""Log output never carries DSN passwords, API keys, JWTs or full emails."""

import json
import logging

from app.core.json_formatter import RedactingTextFormatter, StructuredJsonFormatter
from app.core.log_redaction import redact

SECRET_DSN = "redis://:s3cretpw@redis-master:6379/0"  # pragma: allowlist secret
PG_DSN = "postgresql+asyncpg://kbp:pgpass@db:5432/kbp"  # pragma: allowlist secret
API_KEY = "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWx1234"  # pragma: allowlist secret
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1In0.c2lnbmF0dXJl"  # pragma: allowlist secret


def test_dsn_password_masked():
    assert redact(SECRET_DSN) == "redis://***@redis-master:6379/0"
    assert "pgpass" not in redact(PG_DSN)
    assert redact("redis://redis-master:6379/0") == "redis://redis-master:6379/0"


def test_api_key_and_jwt_masked():
    out = redact(f"key={API_KEY} auth=Bearer {JWT}")
    assert API_KEY not in out and "sk-***1234" in out
    assert JWT not in out and "[jwt]" in out


def test_email_local_part_masked():
    assert redact("lookup failed for alice.smith@example.com") == (
        "lookup failed for a***@example.com"
    )


def test_non_strings_untouched():
    assert redact(None) is None
    assert redact(42) == 42


def _record(msg, *args, **extra):
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)
    for k, v in extra.items():
        setattr(rec, k, v)
    return rec


def test_json_formatter_redacts_message_and_extra():
    rec = _record("Redis connected: %s", SECRET_DSN, recipients=["bob@example.com"])
    obj = json.loads(StructuredJsonFormatter().format(rec))
    assert "s3cretpw" not in obj["message"]
    assert obj["recipients"] == ["b***@example.com"]


def test_json_formatter_redacts_exception():
    try:
        raise RuntimeError(f"cannot connect to {PG_DSN}")
    except RuntimeError:
        import sys

        rec = _record("boom")
        rec.exc_info = sys.exc_info()
    obj = json.loads(StructuredJsonFormatter().format(rec))
    assert "pgpass" not in obj["exception"]


def test_text_formatter_redacts():
    rec = _record("sent to %s", "carol@example.com", token_name="-")
    out = RedactingTextFormatter("%(message)s").format(rec)
    assert out == "sent to c***@example.com"


def test_migrate_keeps_its_logging():
    import inspect

    from scripts import migrate

    assert 'attributes["configure_logger"] = False' in inspect.getsource(migrate)
    env = open("alembic/env.py").read()
    assert 'config.attributes.get(\n    "configure_logger", True\n)' in env
