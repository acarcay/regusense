"""
PostgreSQL Client – ReguSense veri katmanı için async bağlantı yöneticisi.

.env dosyasındaki DATABASE_URL değişkeninden bağlantı URL'si okunur.
SQLAlchemy 2.x async engine + asyncpg driver kullanılır.

Kullanım:
    from database.postgres_client import get_session, engine

    async with get_session() as session:
        result = await session.execute(select(RawDocument))
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# .env'i yükle (Docker/prod ortamında sistem env değişkenleri önceliklidir)
load_dotenv()

logger = logging.getLogger(__name__)

# ─── Bağlantı URL'si ──────────────────────────────────────────────────────────
# Öncelik sırası: DATABASE_URL env > bireysel parçalardan oluşturulan URL
_DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    (
        "postgresql+asyncpg://"
        f"{os.getenv('POSTGRES_USER', 'regusense')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'regusense_dev_2026')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'regusense')}"
    ),
)

# ─── Engine ───────────────────────────────────────────────────────────────────
engine: AsyncEngine = create_async_engine(
    _DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",  # SQL debug logu
    pool_size=int(os.getenv("PG_POOL_SIZE", "5")),
    max_overflow=int(os.getenv("PG_MAX_OVERFLOW", "10")),
    pool_pre_ping=True,  # Stale bağlantıları temizler
)

# ─── Session Factory ──────────────────────────────────────────────────────────
AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

logger.info(
    "PostgreSQL engine oluşturuldu: %s",
    _DATABASE_URL.split("@")[-1],  # Şifreyi loglamıyoruz
)


# ─── Context Manager ──────────────────────────────────────────────────────────
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
    session: AsyncSession = AsyncSessionFactory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


# ─── Schema Oluşturma Yardımcısı ─────────────────────────────────────────────
async def create_all_tables() -> None:
    """
    Tüm ORM modellerini veritabanında oluşturur (geliştirme ortamı için).

    Üretimde Alembic migration'ları kullanılmalıdır.
    """
    from database.models import Base  # döngüsel import'u önlemek için lazy

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Tüm tablolar oluşturuldu (create_all)")


async def drop_all_tables() -> None:
    """
    Tüm tabloları siler – SADECE TEST ORTAMINDA kullanın!
    """
    from database.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        logger.warning("Tüm tablolar silindi (drop_all)")
