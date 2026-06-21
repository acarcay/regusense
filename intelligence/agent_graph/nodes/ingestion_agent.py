"""
IngestionAgent Node: PostgreSQL'den işlenmemiş belgeleri çeker.

Görev:
    - ``raw_documents`` tablosundan ``processing_status = 'pending'`` olan
      kayıtları ``batch_size`` kadar çeker.
    - Her kaydı ``processing_status = 'processing'`` olarak günceller
      (başka runner'ların aynı belgeyi almasını önler).
    - ``RawDocumentDTO`` listesini state'e ekler.

Çıkış (state güncellemesi):
    statements      : List[StatementDTO]  (operator.add ile eklenir)
    ingested_count  : int
    errors          : List[str]             (operator.add ile eklenir)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from intelligence.agent_graph.state import PipelineState, StatementDTO

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

    fetched: list[StatementDTO] = []
    errors: list[str] = []

    try:
        from database.postgres_client import get_session
        from database.models import RawDocument, DocumentStatus, Statement
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            # ── 1. Pending belgeleri kilitle ──────────────────────────────
            # SELECT ... FOR UPDATE SKIP LOCKED → eş zamanlı runner çakışmasını önler
            stmt = (
                select(RawDocument)
                .where(RawDocument.processing_status == DocumentStatus.PENDING.value)
                .order_by(RawDocument.created_at.asc())
                .limit(batch_size)
                .options(selectinload(RawDocument.statements))
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            docs = result.scalars().all()

            if not docs:
                logger.info("IngestionAgent: İşlenecek pending belge yok.")
                return {
                    "statements": [],
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
            statement_count = 0
            for doc in docs:
                for stmt in doc.statements:
                    fetched.append(
                        StatementDTO(
                            stmt_id=stmt.id,
                            raw_document_id=doc.id,
                            text=stmt.text,
                            speaker=stmt.raw_speaker_name or "Bilinmiyor",
                            date=stmt.date or doc.date or "2023-01-01",
                            page_number=stmt.page_number or 1,
                            session_id=doc.session_id,
                            source_url=doc.source_url,
                        )
                    )
                    statement_count += 1

        logger.info(
            "IngestionAgent [run=%s]: %d belge alındı, %d statement işleme alındı.",
            run_id, len(docs), statement_count,
        )

    except Exception as exc:
        msg = f"IngestionAgent hata: {exc}"
        logger.exception(msg)
        errors.append(msg)

    return {
        "statements": fetched,
        "ingested_count": len(fetched),
        "errors": errors,
    }
