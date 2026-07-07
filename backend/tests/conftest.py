"""Shared pytest configuration.

Several application modules call ``get_settings()`` at *import* time (e.g.
``app.core.security`` builds a module-level ``settings`` object). ``Settings``
is a pydantic ``BaseSettings`` whose ``DATABASE_URL`` / ``JWT_SECRET_KEY`` are
required. Locally a ``.env`` satisfies them, but CI provides neither, so the
first test that imports such a module fails during import — before any fixture
can run.

Set dummy-but-valid values here, at conftest import time, which pytest loads
before collecting any test module. ``setdefault`` never overrides values a real
environment (or ``.env`` via pydantic) already provides, so this is a no-op
locally and in deployed environments.
"""

import os

# Valid Postgres URL + a 32+ char secret so the Settings field validators pass.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://user:pass@localhost:5432/test",  # pragma: allowlist secret
)
os.environ.setdefault("JWT_SECRET_KEY", "x" * 32)  # pragma: allowlist secret
