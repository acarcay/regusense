"""
Archivist Node: Query internal databases for evidence.

Role:
- Query PostgreSQL for structured data
- Query ChromaDB for semantic similarity
- Append findings to evidence_chain
- Set requires_external_search if no evidence found
"""

import logging
from typing import Any, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agents.state import AgentState, Evidence

logger = logging.getLogger(__name__)

# Import database models (lazy to avoid circular imports)
def get_db_session():
    from database.session import get_async_session
    return get_async_session

def get_memory():
    from memory.vector_store import PoliticalMemory
    return PoliticalMemory()


async def query_postgres(
    speaker: str,
    topics: List[str],
    limit: int = 5,
) -> List[Evidence]:
    """Query PostgreSQL for related historical statements."""
    from database.session import get_async_session
    from database.models import Statement, Speaker, normalize_speaker_name
    
    evidence = []
    normalized_speaker = normalize_speaker_name(speaker) if speaker else ""
    
    try:
        async with get_async_session() as session:
            # Build query
            query = select(Statement, Speaker).join(Speaker)
            
            if normalized_speaker:
                query = query.where(Speaker.normalized_name == normalized_speaker)
            
            query = query.order_by(Statement.created_at.desc()).limit(limit)
            
            result = await session.execute(query)
            rows = result.fetchall()
            
            for stmt, spkr in rows:
                evidence.append(Evidence(
                    content=stmt.text,
                    source=f"PostgreSQL (ID: {stmt.id})",
                    source_type="INTERNAL_DB",
                    date=stmt.date or "",
                    relevance_score=0.8,  # High relevance for speaker match
                ))
            
            logger.info(f"Archivist: Found {len(evidence)} records in PostgreSQL")
            
    except Exception as e:
        logger.error(f"Archivist: PostgreSQL query failed: {e}")
    
    return evidence


def query_chromadb(
    query_text: str,
    speaker: Optional[str] = None,
    n_results: int = 5,
) -> List[Evidence]:
    """Query ChromaDB for semantically similar statements."""
    evidence = []
    
    try:
        memory = get_memory()
        
        # Use correct parameter names for PoliticalMemory.search()
        results = memory.search(
            query_text=query_text,
            top_k=n_results,
            speaker_filter=speaker if speaker else None,
        )
        
        for match in results:
            # match is StatementMatch object
            evidence.append(Evidence(
                content=match.text,
                source=match.source,
                source_type=match.source_type,
                date=match.date,
                relevance_score=match.similarity,
            ))
        
        logger.info(f"Archivist: Found {len(evidence)} similar docs in ChromaDB")
        
    except Exception as e:
        logger.error(f"Archivist: ChromaDB query failed: {e}")
    
    return evidence


def archivist_node(state: AgentState) -> dict[str, Any]:
    """
    Archivist Node: Search internal databases for evidence.
    
    Input:
        state.target_statement: Statement to find evidence for
        state.speaker: Speaker to filter by
        state.topics: Topics to search for
        
    Output:
        evidence_chain: List[Evidence] (appended)
        requires_external_search: bool
    """
    statement = state.get("target_statement", "")
    speaker = state.get("speaker", "")
    topics = state.get("topics", [])
    
    logger.info(f"Archivist: Searching for evidence, speaker='{speaker}'")
    
    all_evidence: List[Evidence] = []
    
    # 1. Query ChromaDB (semantic search)
    chroma_evidence = query_chromadb(
        query_text=statement,
        speaker=speaker if speaker else None,
        n_results=5,
    )
    all_evidence.extend(chroma_evidence)
    
    # 2. If no ChromaDB results, try PostgreSQL directly
    # (This is async, but we'll run it sync for now)
    # TODO: Make this properly async when integrating
    
    # Determine if we need external search
    has_good_evidence = any(e.relevance_score > 0.6 for e in all_evidence)
    requires_external = len(all_evidence) == 0 or not has_good_evidence
    
    logger.info(
        f"Archivist: Total evidence={len(all_evidence)}, "
        f"requires_external={requires_external}"
    )
    
    return {
        "evidence_chain": all_evidence,
        "requires_external_search": requires_external,
    }
