"""
intelligence/agent_graph — ReguSense LangGraph tabanlı intelligence pipeline.

Kullanım::

    from intelligence.agent_graph import build_pipeline, run_pipeline_async
    from intelligence.agent_graph.state import create_pipeline_state

    # Async kullanım (FastAPI, main.py)
    pipeline = build_pipeline()
    state = create_pipeline_state(batch_size=20)
    result = await pipeline.ainvoke(state)

    # Senkron kısayol
    result = run_pipeline_sync(batch_size=20)
"""

from intelligence.agent_graph.graph import (
    build_pipeline,
    run_pipeline_async,
    run_pipeline_sync,
)
from intelligence.agent_graph.state import (
    PipelineState,
    create_pipeline_state,
    RawDocumentDTO,
    EntityBundle,
    ContradictionBundle,
    InsightCard,
)

__all__ = [
    # Graph
    "build_pipeline",
    "run_pipeline_async",
    "run_pipeline_sync",
    # State
    "PipelineState",
    "create_pipeline_state",
    # DTOs
    "RawDocumentDTO",
    "EntityBundle",
    "ContradictionBundle",
    "InsightCard",
]
