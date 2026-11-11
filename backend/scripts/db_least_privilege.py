"""Create the least-privilege database roles and hand the schema to them.

Run once per environment with the cluster's master credentials (idempotent;
re-running rotates the two role passwords to the ones given):

    KBR_MASTER_DATABASE_URL  master connection (postgresql[+asyncpg]://...)
    KBR_MIGRATE_DATABASE_URL URL whose user/password become the migrator role
    KBR_APP_DATABASE_URL     URL whose user/password become the app role

Roles:
  migrator  owns every object in schema public (tables, sequences, views,
            enum types) and may create new ones - used only by db-migrate.
  app       SELECT/INSERT/UPDATE/DELETE on tables, USAGE/SELECT on sequences;
            no DDL. Default privileges make tables the migrator creates later
            available to the app automatically.

Nothing here prints a password.
"""

import asyncio
import os
from urllib.parse import unquote, urlsplit

import asyncpg


def _parts(url: str) -> tuple[str, str, str]:
    u = urlsplit(url.replace("+asyncpg", ""))
    return unquote(u.username or ""), unquote(u.password or ""), u.path.lstrip("/")


def _ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise SystemExit(f"refusing unusual role name: {name!r}")
    return f'"{name}"'


async def _ensure_role(conn, name: str, password: str) -> None:
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", name)
    verb = "ALTER" if exists else "CREATE"
    # PASSWORD can't be a bind parameter; quote it as a literal.
    literal = "'" + password.replace("'", "''") + "'"
    await conn.execute(f"{verb} ROLE {_ident(name)} LOGIN PASSWORD {literal}")
    print(f"role {name}: {'updated' if exists else 'created'}")


async def main() -> None:
    master_url = os.environ["KBR_MASTER_DATABASE_URL"]
    mig_user, mig_pw, db = _parts(os.environ["KBR_MIGRATE_DATABASE_URL"])
    app_user, app_pw, app_db = _parts(os.environ["KBR_APP_DATABASE_URL"])
    if db != app_db or not (mig_user and mig_pw and app_user and app_pw):
        raise SystemExit("both URLs need a user, a password and the same database")
    if mig_user == app_user:
        raise SystemExit("migrator and app must be different roles")

    conn = await asyncpg.connect(master_url.replace("+asyncpg", ""))
    try:
        master = await conn.fetchval("SELECT current_user")
        async with conn.transaction():
            await _ensure_role(conn, mig_user, mig_pw)
            await _ensure_role(conn, app_user, app_pw)
            M, A = _ident(mig_user), _ident(app_user)
            # Non-superuser masters (RDS) must be able to SET ROLE to the new
            # owner before ALTER ... OWNER TO.
            await conn.execute(f"GRANT {M} TO {_ident(master)}")
            await conn.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {M}, {A}')
            await conn.execute(f"GRANT USAGE, CREATE ON SCHEMA public TO {M}")
            await conn.execute(f"GRANT USAGE ON SCHEMA public TO {A}")

            moved = 0
            for kind, rows in (
                (
                    "TABLE",
                    await conn.fetch(
                        "SELECT tablename AS n FROM pg_tables WHERE schemaname='public'"
                    ),
                ),
                (
                    "SEQUENCE",
                    await conn.fetch(
                        "SELECT sequencename AS n FROM pg_sequences WHERE schemaname='public'"
                    ),
                ),
                (
                    "VIEW",
                    await conn.fetch(
                        "SELECT viewname AS n FROM pg_views WHERE schemaname='public'"
                    ),
                ),
                (
                    "TYPE",
                    await conn.fetch(
                        "SELECT t.typname AS n FROM pg_type t JOIN pg_namespace s ON s.oid=t.typnamespace "
                        "WHERE s.nspname='public' AND t.typtype='e'"
                    ),
                ),
            ):
                for row in rows:
                    await conn.execute(f'ALTER {kind} public."{row["n"]}" OWNER TO {M}')
                    moved += 1
            print(f"ownership moved to {mig_user}: {moved} objects")

            await conn.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {A}"
            )
            await conn.execute(
                f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {A}"
            )
            await conn.execute(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {M} IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {A}"
            )
            await conn.execute(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {M} IN SCHEMA public "
                f"GRANT USAGE, SELECT ON SEQUENCES TO {A}"
            )
            # Enum types are used by app columns; USAGE is public by default
            # but make it explicit.
            await conn.execute(
                f"ALTER DEFAULT PRIVILEGES FOR ROLE {M} IN SCHEMA public "
                f"GRANT USAGE ON TYPES TO {A}"
            )
        print("done")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
