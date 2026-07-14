"""
PostgreSQL Client – ReguSense veri katmanı için async bağlantı yöneticisi.

Backward-compatibility layer: the single engine/session factory lives in
database.session — this module delegates to it so existing imports keep
working. Yeni kod için database.session.get_async_session kullanın.

Kullanım:
    from database.postgres_client import get_session

    async with get_session() as session:
        result = await session.execute(select(RawDocument))
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_async_session, get_engine, get_session_factory

logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async veritabanı oturumu sağlar.

    Commit/rollback otomatik yönetilir; hata durumunda rollback yapılır.

    Örnek::

        async with get_session() as session:
            session.add(RawDocument(...))
            # commit otomatik yapılır

    Yields:
        AsyncSession: Aktif SQLAlchemy oturumu
    """
    async with get_async_session() as session:
        yield session


# ─── Schema Oluşturma Yardımcısı ─────────────────────────────────────────────
async def create_all_tables() -> None:
    """
    Tüm ORM modellerini veritabanında oluşturur (geliştirme ortamı için).

    Üretimde Alembic migration'ları kullanılmalıdır.
    """
    from database.models import Base  # döngüsel import'u önlemek için lazy

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Tüm tablolar oluşturuldu (create_all)")


async def drop_all_tables() -> None:
    """
    Tüm tabloları siler – SADECE TEST ORTAMINDA kullanın!
    """
    from database.models import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        logger.warning("Tüm tablolar silindi (drop_all)")


def __getattr__(name: str):
    # Backward compatibility: `engine` and `AsyncSessionFactory` used to be
    # module-level objects created at import time.
    if name == "engine":
        return get_engine()
    if name == "AsyncSessionFactory":
        return get_session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
