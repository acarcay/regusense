"""
intelligence/agent_graph/graph.py — Pipeline StateGraph tanımı.

Akış:
    IngestionAgent
        ↓  (belge yoksa → END)
    ExtractionAgent
        ↓
    FactCheckAgent
        ↓  (çelişki yoksa → END)
    PublishingAgent
        ↓
    END

Kullanım::

    from intelligence.agent_graph.graph import build_pipeline

    pipeline = build_pipeline()
    result = await pipeline.ainvoke(create_pipeline_state(batch_size=10))
    print(result["final_report"])
"""

from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import END, StateGraph

from intelligence.agent_graph.nodes.ingestion_agent import ingestion_agent
from intelligence.agent_graph.nodes.extraction_agent import extraction_agent
from intelligence.agent_graph.nodes.factcheck_agent import factcheck_agent
from intelligence.agent_graph.nodes.publishing_agent import publishing_agent
from intelligence.agent_graph.state import PipelineState

logger = logging.getLogger(__name__)


# =============================================================================
# Koşullu Yönlendirme Fonksiyonları
# =============================================================================

def _route_after_ingest(
    state: PipelineState,
) -> Literal["extraction_agent", "__end__"]:
    """
    IngestionAgent sonrası yönlendirme.

    Ham belge yoksa pipeline'ı sonlandır; varsa ExtractionAgent'a geç.
    """
    docs = state.get("raw_documents", [])
    if not docs:
        logger.info("Graph: İşlenecek belge yok → pipeline sonlanıyor.")
        return END
    logger.info("Graph: %d belge ingest edildi → ExtractionAgent'a yönleniyor.", len(docs))
    return "extraction_agent"


def _route_after_factcheck(
    state: PipelineState,
) -> Literal["publishing_agent", "__end__"]:
    """
    FactCheckAgent sonrası yönlendirme.

    Hiç çelişki bulunamadıysa publishing adımını atla.
    """
    contradictions = state.get("contradictions", [])
    if not contradictions:
        logger.info("Graph: Çelişki bulunamadı → PublishingAgent atlanıyor.")
        return END
    logger.info(
        "Graph: %d çelişki bulundu → PublishingAgent'a yönleniyor.",
        len(contradictions),
    )
    return "publishing_agent"


# =============================================================================
# Graph Builder
# =============================================================================

def build_pipeline() -> StateGraph:
    """
    ReguSense Intelligence Pipeline'ını derler ve döndürür.

    Dönen nesne ``CompiledStateGraph``'tır:
    - ``pipeline.invoke(state)``     → senkron çalıştırma
    - ``await pipeline.ainvoke(state)`` → async çalıştırma

    Returns:
        Derlenmiş LangGraph StateGraph

    Example::

        pipeline = build_pipeline()
        initial = create_pipeline_state(batch_size=20)
        final_state = await pipeline.ainvoke(initial)
        print(final_state["final_report"])
    """
    # ── Graph tanımı ──────────────────────────────────────────────────────
    graph = StateGraph(PipelineState)

    # ── Node'ları ekle ────────────────────────────────────────────────────
    graph.add_node("ingestion_agent",  ingestion_agent)
    graph.add_node("extraction_agent", extraction_agent)
    graph.add_node("factcheck_agent",  factcheck_agent)
    graph.add_node("publishing_agent", publishing_agent)

    # ── Giriş noktası ─────────────────────────────────────────────────────
    graph.set_entry_point("ingestion_agent")

    # ── Kenarlar ──────────────────────────────────────────────────────────

    # Ingest → (belge var mı?) → Extraction | END
    graph.add_conditional_edges(
        "ingestion_agent",
        _route_after_ingest,
        {
            "extraction_agent": "extraction_agent",
            END: END,
        },
    )

    # Extraction → FactCheck (her zaman)
    graph.add_edge("extraction_agent", "factcheck_agent")

    # FactCheck → (çelişki var mı?) → Publishing | END
    graph.add_conditional_edges(
        "factcheck_agent",
        _route_after_factcheck,
        {
            "publishing_agent": "publishing_agent",
            END: END,
        },
    )

    # Publishing → END
    graph.add_edge("publishing_agent", END)

    # ── Derle ─────────────────────────────────────────────────────────────
    compiled = graph.compile()
    logger.info(
        "ReguSense Intelligence Pipeline derlendi: "
        "IngestionAgent → ExtractionAgent → FactCheckAgent → PublishingAgent"
    )
    return compiled


# =============================================================================
# Çalıştırma Yardımcıları
# =============================================================================

async def run_pipeline_async(
    batch_size: int = 20,
    run_id: str | None = None,
) -> PipelineState:
    """
    Pipeline'ı async olarak çalıştırır.

    Args:
        batch_size: Tek seferde işlenecek belge sayısı
        run_id:     Opsiyonel çalıştırma kimliği

    Returns:
        Tamamlanmış PipelineState
    """
    from intelligence.agent_graph.state import create_pipeline_state

    initial = create_pipeline_state(batch_size=batch_size, run_id=run_id)
    pipeline = build_pipeline()

    logger.info(
        "Pipeline başlatılıyor [run=%s, batch_size=%d]",
        initial["run_id"], batch_size,
    )

    final_state: PipelineState = await pipeline.ainvoke(initial)

    _log_summary(final_state)
    return final_state


def run_pipeline_sync(
    batch_size: int = 20,
    run_id: str | None = None,
) -> PipelineState:
    """
    Pipeline'ı senkron olarak çalıştırır (asyncio.run ile).

    asyncio event loop'u zaten çalışıyorsa ``run_pipeline_async`` kullanın.

    Args:
        batch_size: Tek seferde işlenecek belge sayısı
        run_id:     Opsiyonel çalıştırma kimliği

    Returns:
        Tamamlanmış PipelineState
    """
    import asyncio
    return asyncio.run(run_pipeline_async(batch_size=batch_size, run_id=run_id))


def _log_summary(state: PipelineState) -> None:
    """Pipeline tamamlanma özetini loglar."""
    docs = state.get("ingested_count", 0)
    extracted = len(state.get("extracted_entities", []))
    contradictions = state.get("contradictions", [])
    cards = state.get("insight_cards", [])
    errors = state.get("errors", [])

    critical = sum(1 for c in contradictions if c.risk_level == "CRITICAL")

    logger.info("=" * 60)
    logger.info("📊 PIPELINE TAMAMLANDI [run=%s]", state.get("run_id", "?"))
    logger.info("  İngest : %d belge", docs)
    logger.info("  Çıkarma: %d entity bundle", extracted)
    logger.info("  Kontrol: %d çelişki bulundu", len(contradictions))
    logger.info("  Kart   : %d Insight Card üretildi", len(cards))
    if critical:
        logger.warning("  🚨 KRİTİK: %d kritik çelişki!", critical)
    if errors:
        logger.warning("  ❌ Hatalar: %d adet", len(errors))
    logger.info("=" * 60)
