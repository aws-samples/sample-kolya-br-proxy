"""Shared pytest configuration.

Several application modules call ``get_settings()`` at *import* time (e.g.
``app.core.security`` builds a module-level ``settings`` object). ``Settings``
is a pydantic ``BaseSettings`` whose ``DATABASE_URL`` / ``JWT_SECRET_KEY`` are
required. Locally a ``.env`` / ``.env.local`` satisfies them, but CI ships
neither (``.env.local`` is git-ignored), so the first test that imports such a
module fails during import — before any fixture can run.

Set dummy-but-valid values here, at conftest import time, which pytest loads
before collecting any test module. NOTE: Settings uses ``env_prefix = "KBR_"``,
so the variables must be named ``KBR_DATABASE_URL`` / ``KBR_JWT_SECRET_KEY``.
``setdefault`` never overrides values a real environment already provides, so
this is a no-op locally and in deployed environments.
"""

import os

# Settings reads env vars with the KBR_ prefix. Valid Postgres URL + a 32+ char
# secret so the field validators pass.
os.environ.setdefault(
    "KBR_DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/test",  # pragma: allowlist secret
)
os.environ.setdefault("KBR_JWT_SECRET_KEY", "x" * 32)  # pragma: allowlist secret
