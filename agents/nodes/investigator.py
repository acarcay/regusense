"""
Investigator Agent Node: Sector-aware conflict of interest detection.

Role:
1. Extract sector from statement
2. Query Neo4j for politician-organization connections
3. Calculate weighted conflict scores with temporal decay
4. Return potential conflicts for HITL review
"""

import logging
from datetime import date
from typing import Any, Optional
from dataclasses import dataclass

from agents.state import AgentState, Evidence
from intelligence.sector_classifier import classify_sector, SectorMatch

logger = logging.getLogger(__name__)


@dataclass
class ConflictOfInterest:
    """A potential conflict of interest finding."""
    
    politician: str
    organization: str
    organization_mersis: Optional[str]
    sector: str
    connection_type: str
    raw_weight: float
    decay_factor: float
    final_score: float
    evidence_summary: str
    
    def to_dict(self) -> dict:
        return {
            "politician": self.politician,
            "organization": self.organization,
            "organization_mersis": self.organization_mersis,
            "sector": self.sector,
            "connection_type": self.connection_type,
            "raw_weight": self.raw_weight,
            "decay_factor": self.decay_factor,
            "final_score": self.final_score,
            "evidence_summary": self.evidence_summary,
        }


def calculate_temporal_decay(end_date_str: Optional[str], years_half_life: int = 5) -> float:
    """Calculate decay factor for a relationship."""
    if not end_date_str:
        return 1.0  # Still active
    
    try:
        end_date = date.fromisoformat(end_date_str)
        years_passed = (date.today() - end_date).days / 365
        if years_passed <= 0:
            return 1.0
        return 0.5 ** (years_passed / years_half_life)
    except (ValueError, TypeError):
        return 1.0


async def query_neo4j_conflicts(
    politician_name: str,
    sector_code: Optional[str] = None,
) -> list[dict]:
    """Query Neo4j for conflicts. Returns empty list if Neo4j unavailable."""
    try:
        from database.neo4j_client import find_conflicts_for_politician
        return await find_conflicts_for_politician(politician_name, sector_code)
    except Exception as e:
        logger.warning(f"Neo4j query failed (may not be running): {e}")
        return []


def investigator_node(state: AgentState) -> dict[str, Any]:
    """
    Investigator Node: Detect conflicts of interest.
    
    Process:
    1. Classify statement into sectors
    2. Query Neo4j for politician-organization connections
    3. Calculate weighted conflict scores
    4. Add findings to evidence chain
    
    Input:
        state.target_statement: Statement to analyze
        state.speaker: Politician name
        
    Output:
        evidence_chain: List[Evidence] with conflict findings
        detected_sectors: List of sector codes
        conflict_findings: List[ConflictOfInterest]
    """
    statement = state.get("target_statement", "")
    speaker = state.get("speaker", "")
    
    if not speaker:
        logger.info("Investigator: No speaker provided, skipping conflict check")
        return {}
    
    logger.info(f"Investigator: Checking conflicts for {speaker}")
    
    # Step 1: Classify sectors
    sector_matches = classify_sector(statement, use_llm=False, speaker=speaker)
    detected_sectors = [m.code for m in sector_matches]
    
    logger.info(f"Investigator: Detected sectors: {detected_sectors}")
    
    if not sector_matches:
        logger.info("Investigator: No sectors detected")
        return {"detected_sectors": []}
    
    # Step 2: Query Neo4j for each detected sector
    all_conflicts: list[ConflictOfInterest] = []
    new_evidence: list[Evidence] = []
    
    # Run async query synchronously for now
    import asyncio
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    for sector_match in sector_matches[:2]:  # Top 2 sectors
        try:
            connections = loop.run_until_complete(
                query_neo4j_conflicts(speaker, sector_match.code)
            )
            
            for conn in connections:
                # Calculate final score with decay
                raw_weight = conn.get("weight", 0.5)
                end_date_str = conn.get("end_date")
                decay = calculate_temporal_decay(end_date_str)
                sector_relevance = sector_match.confidence
                
                final_score = raw_weight * decay * sector_relevance
                
                if final_score >= 0.3:  # Threshold for reporting
                    conflict = ConflictOfInterest(
                        politician=conn.get("politician", speaker),
                        organization=conn.get("organization", ""),
                        organization_mersis=conn.get("mersis"),
                        sector=sector_match.name,
                        connection_type=conn.get("connection_type", "unknown"),
                        raw_weight=raw_weight,
                        decay_factor=decay,
                        final_score=final_score,
                        evidence_summary=f"{speaker} has {conn.get('connection_type', 'connection')} "
                                        f"to {conn.get('organization')} in {sector_match.name} sector",
                    )
                    all_conflicts.append(conflict)
                    
                    # Add to evidence chain
                    new_evidence.append(Evidence(
                        content=conflict.evidence_summary,
                        source="Neo4j Graph",
                        source_type="CONFLICT_OF_INTEREST",
                        relevance_score=final_score,
                    ))
                    
        except Exception as e:
            logger.error(f"Investigator: Error querying sector {sector_match.code}: {e}")
    
    logger.info(f"Investigator: Found {len(all_conflicts)} potential conflicts")
    
    # Sort by score
    all_conflicts.sort(key=lambda x: x.final_score, reverse=True)
    
    return {
        "detected_sectors": detected_sectors,
        "conflict_findings": [c.to_dict() for c in all_conflicts],
        "evidence_chain": new_evidence,
    }


def format_conflict_report(conflicts: list[dict]) -> str:
    """Format conflicts for human review."""
    if not conflicts:
        return "Çıkar çatışması bulunmadı."
    
    lines = ["## 🔍 Potansiyel Çıkar Çatışmaları", ""]
    
    for i, c in enumerate(conflicts, 1):
        score = c.get("final_score", 0)
        emoji = "🔴" if score >= 0.7 else ("🟠" if score >= 0.5 else "🟡")
        
        lines.extend([
            f"### {emoji} Çatışma {i}",
            f"- **Siyasetçi:** {c.get('politician')}",
            f"- **Organizasyon:** {c.get('organization')}",
            f"- **Sektör:** {c.get('sector')}",
            f"- **Bağ Tipi:** {c.get('connection_type')}",
            f"- **Skor:** {score:.2f}",
            f"  - Ham Ağırlık: {c.get('raw_weight', 0):.2f}",
            f"  - Zaman Aşımı: {c.get('decay_factor', 1):.2f}",
            "",
        ])
    
    return "\n".join(lines)
