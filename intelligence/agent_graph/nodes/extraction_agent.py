"""
ExtractionAgent Node: Metinden varlık çıkarır, Neo4j ve PostgreSQL'e yazar.

Görev:
    - ``raw_documents`` listesindeki her belge için:
        1. ``intelligence.entity_extractor.EntityExtractor`` ile NER çalıştır
        2. ``database.graph_helper.GraphHelper`` ile Neo4j'e yaz:
           - Kişi → ``create_siyasetci()``
           - Kurum → ``create_kurum()``
           - Şirket → ``create_sirket()``
        3. ``RawDocument.processing_status`` → ``'done'`` olarak güncelle
    - ``EntityBundle`` listesini state'e ekler.

Çıkış (state güncellemesi):
    extracted_entities         : List[EntityBundle]
    neo4j_nodes_created        : int
    neo4j_relationships_created: int
    errors                     : List[str]
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from intelligence.agent_graph.state import (
    EntityBundle,
    PipelineState,
    RawDocumentDTO,
)

logger = logging.getLogger(__name__)

# Neo4j pg_id bulunamadığında kullanılan varsayılan (geçici) değer.
# Gerçek production'da Speaker tablosuna bakılıp eşleştirilmeli.
_UNKNOWN_PG_ID = -1


def _extract_entities_sync(raw_text: str) -> dict:
    """
    EntityExtractor'ı senkron olarak çalıştırır.

    GLiNER model yüklemesi CPU-bound olduğu için asyncio event loop'u
    bloklamamak adına thread pool executor içinde çağrılabilir; ancak
    burada basitlik için doğrudan çağırıyoruz (model zaten singleton).
    """
    from intelligence.entity_extractor import get_entity_extractor

    extractor = get_entity_extractor()
    result = extractor.extract(raw_text)

    return {
        "persons": result.persons,
        "organizations": result.organizations,
        "dates": result.dates,
        "topics": result.topics,
    }


async def _write_to_neo4j(
    entities: dict,
    doc: RawDocumentDTO,
    helper,
) -> tuple[int, int]:
    """
    Çıkarılan varlıkları Neo4j'e yazar.

    Returns:
        (nodes_created, relationships_created) tuple
    """
    nodes_created = 0
    rels_created = 0

    # ── Kişiler (Siyasetçi) ───────────────────────────────────────────────
    for person_name in entities.get("persons", []):
        if not person_name.strip():
            continue
        try:
            # Normalized ad: Türkçe karakter dönüşümü
            from database.models import normalize_speaker_name
            normalized = normalize_speaker_name(person_name)

            result = await helper.create_siyasetci(
                pg_id=_UNKNOWN_PG_ID,   # Gerçek ID eşleştirmesi sonraki aşamada
                ad=person_name,
                normalized_ad=normalized,
                parti="",               # Parti bilgisi sonraki aşamada zenginleştirilir
                unvan="",
            )
            nodes_created += result.get("nodes_created", 0)
        except Exception as exc:
            logger.warning("Neo4j siyasetçi yazma hatası (%s): %s", person_name, exc)

    # ── Kurumlar / Şirketler ──────────────────────────────────────────────
    for org_name in entities.get("organizations", []):
        if not org_name.strip():
            continue
        try:
            # Basit heuristik: "A.Ş.", "Ltd.", "Holding" → şirket; diğerleri → kurum
            _company_keywords = ("a.ş.", "ltd.", "holding", "şirketi", "anonim")
            is_company = any(kw in org_name.lower() for kw in _company_keywords)

            if is_company:
                result = await helper.create_sirket(
                    ad=org_name,
                    sirket_tipi="company",
                )
            else:
                result = await helper.create_kurum(
                    ad=org_name,
                    kurum_tipi="public_institution",
                )
            nodes_created += result.get("nodes_created", 0)
        except Exception as exc:
            logger.warning("Neo4j kurum/şirket yazma hatası (%s): %s", org_name, exc)

    return nodes_created, rels_created


async def _mark_document_done(doc_id: int) -> None:
    """PostgreSQL'de belgeyi 'done' olarak işaretle."""
    try:
        from database.postgres_client import get_session
        from database.models import RawDocument

        async with get_session() as session:
            doc = await session.get(RawDocument, doc_id)
            if doc:
                doc.mark_done()
    except Exception as exc:
        logger.error("Belge %d 'done' olarak işaretlenemedi: %s", doc_id, exc)


async def _mark_document_failed(doc_id: int, error: str) -> None:
    """PostgreSQL'de belgeyi 'failed' olarak işaretle."""
    try:
        from database.postgres_client import get_session
        from database.models import RawDocument

        async with get_session() as session:
            doc = await session.get(RawDocument, doc_id)
            if doc:
                doc.mark_failed(error[:500])  # Hata mesajını kısalt
    except Exception as exc:
        logger.error("Belge %d 'failed' olarak işaretlenemedi: %s", doc_id, exc)


async def extraction_agent(state: PipelineState) -> dict[str, Any]:
    """
    LangGraph node — Her belgeden varlık çıkarır ve Neo4j'e yazar.

    Args:
        state: Mevcut PipelineState (``raw_documents`` dolu olmalı)

    Returns:
        State güncellemesi: ``extracted_entities``, ``neo4j_nodes_created``,
        ``neo4j_relationships_created``, ``errors``
    """
    run_id = state.get("run_id", "unknown")
    raw_documents: list[RawDocumentDTO] = state.get("raw_documents", [])

    logger.info(
        "ExtractionAgent [run=%s]: %d belge işlenecek",
        run_id, len(raw_documents),
    )

    if not raw_documents:
        logger.info("ExtractionAgent: İşlenecek belge yok, atlanıyor.")
        return {
            "extracted_entities": [],
            "neo4j_nodes_created": 0,
            "neo4j_relationships_created": 0,
            "errors": [],
        }

    from database.graph_helper import GraphHelper
    helper = GraphHelper()

    bundles: list[EntityBundle] = []
    total_nodes = 0
    total_rels = 0
    errors: list[str] = []

    for doc in raw_documents:
        logger.debug(
            "ExtractionAgent: Belge %d işleniyor (%s)…",
            doc.doc_id, doc.doc_type,
        )
        try:
            # ── 1. NER çalıştır (CPU-bound → thread pool'da çalıştır) ──
            loop = asyncio.get_running_loop()
            entities = await loop.run_in_executor(
                None,                       # Varsayılan thread pool
                _extract_entities_sync,
                doc.raw_text,
            )

            # ── 2. Neo4j'e yaz ────────────────────────────────────────────
            nodes, rels = await _write_to_neo4j(entities, doc, helper)
            total_nodes += nodes
            total_rels += rels

            # ── 3. EntityBundle oluştur ───────────────────────────────────
            # Konuşmacı: varsa metadata'dan al, yoksa ilk kişi adı
            speaker = (
                doc.metadata.get("speaker", "")
                or (entities["persons"][0] if entities["persons"] else "")
            )

            bundle = EntityBundle(
                doc_id=doc.doc_id,
                doc_type=doc.doc_type,
                persons=entities["persons"],
                organizations=entities["organizations"],
                dates=entities["dates"],
                topics=entities["topics"],
                raw_text=doc.raw_text,
                speaker=speaker,
                statement_date=doc.date or "",
            )
            bundles.append(bundle)

            # ── 4. PostgreSQL → done ──────────────────────────────────────
            await _mark_document_done(doc.doc_id)

            logger.debug(
                "ExtractionAgent: Belge %d → %d kişi, %d org, %d konu",
                doc.doc_id,
                len(entities["persons"]),
                len(entities["organizations"]),
                len(entities["topics"]),
            )

        except Exception as exc:
            msg = f"ExtractionAgent belge {doc.doc_id} hata: {exc}"
            logger.exception(msg)
            errors.append(msg)
            await _mark_document_failed(doc.doc_id, str(exc))

    logger.info(
        "ExtractionAgent [run=%s]: %d bundle üretildi, "
        "%d Neo4j node, %d ilişki",
        run_id, len(bundles), total_nodes, total_rels,
    )

    return {
        "extracted_entities": bundles,
        "neo4j_nodes_created": total_nodes,
        "neo4j_relationships_created": total_rels,
        "errors": errors,
    }
