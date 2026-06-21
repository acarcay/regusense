import logging
from typing import Optional, List, Dict, Any



logger = logging.getLogger(__name__)

async def run_agent_pipeline(
    batch_size: int = 20,
    dry_run: bool = False,
) -> dict:
    """
    ReguSense Intelligence Pipeline'ını LangGraph üzerinden çalıştırır.

    Akış:
        IngestionAgent  → PostgreSQL'den pending RawDocument'ları çeker
        ExtractionAgent → Entity çıkarır, Neo4j'e yazar
        FactCheckAgent  → ChromaDB + LLM ile çelişki tespiti
        PublishingAgent → Insight Card (tweet + rapor) üretir

    Args:
        batch_size: Tek çalıştırmada işlenecek belge sayısı (varsayılan: 20)
        dry_run:    True ise sadece ingest + extraction; FactCheck atlanır

    Returns:
        Pipeline'ın final state özeti (dict)
    """
    from intelligence.agent_graph import run_pipeline_async

    logger.info("=" * 70)
    logger.info("🤖 LANGGRAPH AGENT PIPELINE BAŞLIYOR")
    logger.info("   batch_size=%d | dry_run=%s", batch_size, dry_run)
    logger.info("=" * 70)

    if dry_run:
        logger.info("⚠️  Dry-run modu: FactCheck ve Publishing atlanıyor.")
        # Dry-run: yalnızca ingest + extraction pipeline'ı çalıştır
        # (graph conditional edges zaten belge yoksa durduruyor)

    final_state = await run_pipeline_async(batch_size=batch_size)

    # Özet çıktı
    cards = final_state.get("insight_cards", [])
    contradictions = final_state.get("contradictions", [])
    errors = final_state.get("errors", [])

    summary = {
        "run_id":             final_state.get("run_id"),
        "ingested_count":     final_state.get("ingested_count", 0),
        "extracted_count":    len(final_state.get("extracted_entities", [])),
        "contradiction_count": len(contradictions),
        "insight_card_count": len(cards),
        "error_count":        len(errors),
        "completed_at":       final_state.get("completed_at"),
    }

    logger.info("📊 Pipeline özeti: %s", summary)
    return summary
