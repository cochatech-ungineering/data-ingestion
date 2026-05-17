import logging

import asyncpg

from app.core.config import settings
from app.db.ssl import database_dsn_and_ssl

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_dsn: str | None = None
_ssl: object | None = None


def _connect_kwargs() -> dict:
    global _dsn, _ssl
    if _dsn is None:
        _dsn, _ssl = database_dsn_and_ssl()
    kwargs: dict = {"dsn": _dsn}
    if _ssl is not None:
        kwargs["ssl"] = _ssl
    return kwargs


async def init_db() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    _pool = await asyncpg.create_pool(
        min_size=settings.database_pool_min_size,
        max_size=settings.database_pool_max_size,
        **_connect_kwargs(),
    )
    logger.info("Pool de PostgreSQL inicializado")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Pool de PostgreSQL cerrado")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL no inicializado; llama a init_db() en el lifespan.")
    return _pool
