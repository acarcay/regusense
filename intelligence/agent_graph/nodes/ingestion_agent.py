"""
IngestionAgent Node: PostgreSQL'den işlenmemiş belgeleri çeker.

Görev:
    - ``raw_documents`` tablosundan ``processing_status = 'pending'`` olan
      kayıtları ``batch_size`` kadar çeker.
    - Her kaydı ``processing_status = 'processing'`` olarak günceller
      (başka runner'ların aynı belgeyi almasını önler).
    - ``RawDocumentDTO`` listesini state'e ekler.

Çıkış (state güncellemesi):
    raw_documents   : List[RawDocumentDTO]  (operator.add ile eklenir)
    ingested_count  : int
    errors          : List[str]             (operator.add ile eklenir)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from intelligence.agent_graph.state import PipelineState, RawDocumentDTO

logger = logging.getLogger(__name__)


async def ingestion_agent(state: PipelineState) -> dict[str, Any]:
    """
    LangGraph node — PostgreSQL'den pending belgeleri çeker.

    Async SQLAlchemy session kullanır; ``database.postgres_client.get_session``
    context manager'a dayanır.

    Args:
        state: Mevcut PipelineState

    Returns:
        State güncellemesi: ``raw_documents``, ``ingested_count``, ``errors``
    """
    batch_size: int = state.get("batch_size", 20)
    run_id: str = state.get("run_id", "unknown")

    logger.info(
        "IngestionAgent [run=%s]: başlıyor, batch_size=%d",
        run_id, batch_size,
    )

    fetched: list[RawDocumentDTO] = []
    errors: list[str] = []

    try:
        from database.postgres_client import get_session
        from database.models import RawDocument, DocumentStatus

        async with get_session() as session:
            # ── 1. Pending belgeleri kilitle ──────────────────────────────
            # SELECT ... FOR UPDATE SKIP LOCKED → eş zamanlı runner çakışmasını önler
            stmt = (
                select(RawDocument)
                .where(RawDocument.processing_status == DocumentStatus.PENDING.value)
                .order_by(RawDocument.created_at.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            docs = result.scalars().all()

            if not docs:
                logger.info("IngestionAgent: İşlenecek pending belge yok.")
                return {
                    "raw_documents": [],
                    "ingested_count": 0,
                    "errors": [],
                }

            # ── 2. İşleme durumunu güncelle ───────────────────────────────
            doc_ids = [d.id for d in docs]
            await session.execute(
                update(RawDocument)
                .where(RawDocument.id.in_(doc_ids))
                .values(processing_status=DocumentStatus.PROCESSING.value)
            )
            # commit get_session() context manager tarafından yapılır

            # ── 3. DTO'ya dönüştür ────────────────────────────────────────
            for doc in docs:
                fetched.append(
                    RawDocumentDTO(
                        doc_id=doc.id,
                        doc_type=doc.doc_type,
                        title=doc.title,
                        raw_text=doc.raw_text,
                        date=doc.date,
                        session_id=doc.session_id,
                        source_url=doc.source_url,
                        metadata=doc.metadata_json or {},
                    )
                )

        logger.info(
            "IngestionAgent [run=%s]: %d belge alındı → processing olarak işaretlendi",
            run_id, len(fetched),
        )

    except Exception as exc:
        msg = f"IngestionAgent hata: {exc}"
        logger.exception(msg)
        errors.append(msg)

    return {
        "raw_documents": fetched,
        "ingested_count": len(fetched),
        "errors": errors,
    }
