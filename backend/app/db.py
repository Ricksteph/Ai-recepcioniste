"""Async database layer.

Production target: PostgreSQL + pgvector (docker-compose).
Dev/test fallback: SQLite with JSON-embedded vectors and in-process cosine search.
"""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    url = settings.database_url
    kwargs = {"echo": False, "future": True}
    if url.startswith("sqlite"):
        # NullPool: each session opens a fresh connection in the current event
        # loop — required for aiosqlite, and ideal for a local file DB.
        from sqlalchemy.pool import NullPool

        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = NullPool
    return create_async_engine(url, **kwargs)


engine = _make_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables. For a real deployment use Alembic; create_all keeps the MVP simple."""
    from . import models  # noqa: F401  ensure models are registered

    async with engine.begin() as conn:
        if is_postgres():
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.run_sync(Base.metadata.create_all)
