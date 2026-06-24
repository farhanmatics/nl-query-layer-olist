#!/usr/bin/env python3
"""Lightweight, dependency-free database migration runner.

Applies the ordered ``*.sql`` files in ``backend/migrations/`` against an admin
(superuser) Postgres connection, recording each applied file in a
``schema_migrations`` table so every migration runs exactly once. Migrations are
written to be idempotent, so re-running against an already-populated database
(e.g. one restored from a pg_dump) is safe.

The application itself connects with the read-only ``nlq_readonly`` role and can
NEVER run these migrations — schema changes require the separate admin
connection configured via ``MIGRATION_DB_URL``.

Usage (run from the backend/ directory):
    python migrate.py status      # show applied / pending migrations
    python migrate.py up          # apply all pending migrations
    python migrate.py create-db   # create the target database if it is missing
"""
import asyncio
import sys
import urllib.parse
from pathlib import Path

import asyncpg

from config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


async def _ensure_tracking_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY,
            applied_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


async def _applied_versions(conn: asyncpg.Connection) -> set:
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {r["version"] for r in rows}


async def cmd_status() -> None:
    conn = await asyncpg.connect(settings.migration_db_url)
    try:
        await _ensure_tracking_table(conn)
        applied = await _applied_versions(conn)
    finally:
        await conn.close()

    print(f"Database:       {_safe_url(settings.migration_db_url)}")
    print(f"Migrations dir: {MIGRATIONS_DIR}")
    print("-" * 60)
    files = _migration_files()
    if not files:
        print("  (no migration files found)")
        return
    for f in files:
        mark = "applied" if f.stem in applied else "PENDING"
        print(f"  [{mark:>7}] {f.name}")


async def cmd_up() -> None:
    conn = await asyncpg.connect(settings.migration_db_url)
    try:
        await _ensure_tracking_table(conn)
        applied = await _applied_versions(conn)
        pending = [f for f in _migration_files() if f.stem not in applied]

        if not pending:
            print("Database is up to date. Nothing to apply.")
            return

        for f in pending:
            sql = f.read_text()
            print(f"Applying {f.name} ...", end=" ", flush=True)
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", f.stem
                )
            print("done")
        print(f"\nApplied {len(pending)} migration(s).")
    finally:
        await conn.close()


async def cmd_create_db() -> None:
    parsed = urllib.parse.urlparse(settings.migration_db_url)
    target_db = parsed.path.lstrip("/")
    if not target_db:
        print("ERROR: MIGRATION_DB_URL has no database name in its path.")
        sys.exit(1)

    # Connect to the maintenance database to create the target if needed.
    admin_url = parsed._replace(path="/postgres").geturl()
    conn = await asyncpg.connect(admin_url)
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db
        )
        if exists:
            print(f"Database '{target_db}' already exists.")
        else:
            # CREATE DATABASE cannot run inside a transaction block.
            await conn.execute(f'CREATE DATABASE "{target_db}"')
            print(f"Created database '{target_db}'.")
    finally:
        await conn.close()


def _safe_url(url: str) -> str:
    """Mask the password when printing a connection string."""
    parsed = urllib.parse.urlparse(url)
    if parsed.password:
        netloc = parsed.netloc.replace(f":{parsed.password}@", ":****@")
        parsed = parsed._replace(netloc=netloc)
    return parsed.geturl()


COMMANDS = {
    "status": cmd_status,
    "up": cmd_up,
    "create-db": cmd_create_db,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"Available commands: {', '.join(COMMANDS)}")
        sys.exit(1)
    try:
        asyncio.run(COMMANDS[sys.argv[1]]())
    except (asyncpg.PostgresError, OSError) as e:
        print(f"\nMigration failed: {e!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
