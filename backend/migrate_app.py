#!/usr/bin/env python3
"""App-state migration runner (B1/B2). Mirrors `migrate.py` for the Olist DB.

Applies the ordered `*.sql` files in `backend/migrations_app/` against the
app-state connection, recording each applied file in a `schema_migrations`
table so every migration runs exactly once. Migrations are written to be
idempotent so re-running against an existing app-state DB is safe.

Usage (run from the backend/ directory):
    python migrate_app.py status    # show applied / pending migrations
    python migrate_app.py up        # apply all pending migrations
"""
import asyncio
import sys
import os
from pathlib import Path

import aiosqlite
from config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations_app"


def _migration_files() -> list:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _path_from_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        return url[len("sqlite://"):]
    return url


async def _ensure_tracking_table(conn) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version text PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )


async def _applied_versions(conn) -> set:
    async with conn.execute("SELECT version FROM schema_migrations") as cur:
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def cmd_status() -> None:
    path = _path_from_url(settings.app_db_url)
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        await _ensure_tracking_table(conn)
        applied = await _applied_versions(conn)

    print(f"App DB:        {path}")
    print(f"Migrations:    {MIGRATIONS_DIR}")
    print("-" * 60)
    files = _migration_files()
    if not files:
        print("  (no migration files found)")
        return
    for f in files:
        mark = "applied" if f.stem in applied else "PENDING"
        print(f"  [{mark:>7}] {f.name}")


async def cmd_up() -> None:
    path = _path_from_url(settings.app_db_url)
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    async with aiosqlite.connect(path) as conn:
        await _ensure_tracking_table(conn)
        # Same PRAGMAs the app uses (foreign keys matters for ON DELETE CASCADE).
        await conn.execute("PRAGMA foreign_keys=ON")
        applied = await _applied_versions(conn)
        pending = [f for f in _migration_files() if f.stem not in applied]

        if not pending:
            print("App-state DB is up to date. Nothing to apply.")
            return

        for f in pending:
            sql = f.read_text()
            print(f"Applying {f.name} ...", end=" ", flush=True)
            try:
                await conn.execute("BEGIN")
                await conn.executescript(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (f.stem, __import__("datetime").datetime.utcnow().isoformat()),
                )
                await conn.commit()
                print("done")
            except Exception:
                await conn.rollback()
                raise
        print(f"\nApplied {len(pending)} migration(s).")


COMMANDS = {"status": cmd_status, "up": cmd_up}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        print(f"Available commands: {', '.join(COMMANDS)}")
        sys.exit(1)
    try:
        asyncio.run(COMMANDS[sys.argv[1]]())
    except Exception as e:
        print(f"\nMigration failed: {e!r}")
        sys.exit(1)


if __name__ == "__main__":
    main()
