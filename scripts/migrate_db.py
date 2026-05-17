#!/usr/bin/env python3
"""Aplica migraciones SQL en PostgreSQL (RDS con SSL)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.db.ssl import database_dsn_and_ssl  # noqa: E402


async def run(migration: Path) -> None:
    if not settings.database_url:
        raise SystemExit("DATABASE_URL no configurado")
    dsn, ssl_ctx = database_dsn_and_ssl()
    conn = await asyncpg.connect(dsn, ssl=ssl_ctx)
    try:
        await conn.execute(migration.read_text())
        print(f"OK: {migration}")
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "migration",
        nargs="?",
        default=ROOT / "migrations" / "001_ingestion_jobs.sql",
        type=Path,
    )
    args = parser.parse_args()
    asyncio.run(run(args.migration))


if __name__ == "__main__":
    main()
