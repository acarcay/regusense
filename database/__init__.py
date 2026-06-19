"""
Database package for ReguSense.

Hibrit veri katmanı:
    - PostgreSQL (SQLAlchemy async) → yapısal veriler
    - Neo4j (async driver)          → ilişki grafı
    - ChromaDB (memory/vector_store) → vektör arama (bu pakete dahil değil)
"""

# ── PostgreSQL ─────────────────────────────────────────────────────────────────
from database.models import (
    Base,
    Speaker,
    Statement,
    Source,
    RawDocument,
    DocumentType,
    DocumentStatus,
)
from database.session import get_async_session, async_engine
from database.postgres_client import get_session, engine, create_all_tables

# ── Neo4j ──────────────────────────────────────────────────────────────────────
from database.neo4j_client import (
    get_driver,
    close_driver,
    run_query,
    run_write,
    create_politician,
    create_organization,
    get_session as get_neo4j_session,
)
from database.graph_helper import GraphHelper

__all__ = [
    # PostgreSQL ORM
    "Base",
    "Speaker",
    "Statement",
    "Source",
    "RawDocument",
    "DocumentType",
    "DocumentStatus",
    # PostgreSQL session (session.py – legacy uyumluluk)
    "get_async_session",
    "async_engine",
    # PostgreSQL client (postgres_client.py – yeni)
    "get_session",
    "engine",
    "create_all_tables",
    # Neo4j driver & helpers
    "get_driver",
    "close_driver",
    "run_query",
    "run_write",
    "get_neo4j_session",
    "create_politician",
    "create_organization",
    # Graf CRUD yardımcısı
    "GraphHelper",
]
