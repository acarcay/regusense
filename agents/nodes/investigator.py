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
    
    import asyncio

    for sector_match in sector_matches[:2]:  # Top 2 sectors
        try:
            connections = asyncio.run(
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


# =============================================================================
# Temporal Conflict Analysis (Module 4: The Smoking Gun)
# =============================================================================

@dataclass
class TemporalConflict:
    """
    A temporal conflict between tender award date and political advocacy.
    
    This is the "smoking gun" - if a politician advocates for a company
    within ±15 days of that company winning a tender, it's highly suspicious.
    """
    politician: str
    politician_party: Optional[str]
    organization: str
    organization_mersis: str
    tender_ikn: Optional[str]
    tender_date: date
    advocacy_date: date
    days_difference: int
    risk_level: str  # "CRITICAL" (±3 days) | "HIGH" (±7 days) | "MEDIUM" (±15 days)
    statement_id: Optional[int] = None
    confidence: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "politician": self.politician,
            "politician_party": self.politician_party,
            "organization": self.organization,
            "organization_mersis": self.organization_mersis,
            "tender_ikn": self.tender_ikn,
            "tender_date": self.tender_date.isoformat() if isinstance(self.tender_date, date) else str(self.tender_date),
            "advocacy_date": self.advocacy_date.isoformat() if isinstance(self.advocacy_date, date) else str(self.advocacy_date),
            "days_difference": self.days_difference,
            "risk_level": self.risk_level,
            "statement_id": self.statement_id,
            "confidence": self.confidence,
        }


def classify_temporal_risk(days_diff: int) -> str:
    """Classify risk level based on days difference."""
    abs_diff = abs(days_diff)
    if abs_diff <= 3:
        return "CRITICAL"
    elif abs_diff <= 7:
        return "HIGH"
    else:
        return "MEDIUM"


async def detect_temporal_conflicts(
    org_mersis: str,
    tender_date: date,
    window_days: int = 15,
) -> list[TemporalConflict]:
    """
    Detect temporal conflicts between a tender and political advocacy.
    
    The "Smoking Gun" detector: if a politician advocated for a company
    within ±window_days of that company winning a tender, flag it.
    
    Args:
        org_mersis: Company MERSIS number
        tender_date: Date the tender was awarded
        window_days: Days before/after to search (default: 15)
        
    Returns:
        List of TemporalConflict objects
    """
    from database import neo4j_client
    
    tender_date_str = tender_date.isoformat() if isinstance(tender_date, date) else str(tender_date)
    
    try:
        results = await neo4j_client.find_temporal_conflicts(
            org_mersis=org_mersis,
            tender_date=tender_date_str,
            window_days=window_days,
        )
        
        conflicts = []
        for r in results:
            try:
                advocacy_dt = date.fromisoformat(r.get("advocacy_date", ""))
            except (ValueError, TypeError):
                advocacy_dt = tender_date
            
            conflict = TemporalConflict(
                politician=r.get("politician_name", "Unknown"),
                politician_party=r.get("party"),
                organization=r.get("company_name", "Unknown"),
                organization_mersis=org_mersis,
                tender_ikn=None,  # Not available in single-tender query
                tender_date=tender_date,
                advocacy_date=advocacy_dt,
                days_difference=r.get("days_difference", 0),
                risk_level=classify_temporal_risk(r.get("days_difference", 0)),
                statement_id=r.get("statement_id"),
                confidence=r.get("confidence", 0.0),
            )
            conflicts.append(conflict)
            
            # Log critical findings
            if conflict.risk_level == "CRITICAL":
                logger.warning(
                    f"🔥 CRITICAL TEMPORAL CONFLICT: {conflict.politician} ({conflict.politician_party}) "
                    f"advocated for {conflict.organization} {abs(conflict.days_difference)} days "
                    f"{'before' if conflict.days_difference < 0 else 'after'} tender award!"
                )
        
        return conflicts
        
    except Exception as e:
        logger.error(f"Temporal conflict detection failed: {e}")
        return []


def format_temporal_conflicts_report(conflicts: list[TemporalConflict]) -> str:
    """Format temporal conflicts for human review."""
    if not conflicts:
        return "Zaman çizelgesi çakışması bulunamadı."
    
    lines = ["## 🔥 Zaman Çizelgesi Çakışmaları (İhale-Savunuculuk)", ""]
    
    for i, c in enumerate(conflicts, 1):
        emoji = "🚨" if c.risk_level == "CRITICAL" else ("🔴" if c.risk_level == "HIGH" else "🟠")
        direction = "ÖNCE" if c.days_difference < 0 else "SONRA"
        
        lines.extend([
            f"### {emoji} {c.risk_level} RİSK - Çakışma {i}",
            f"- **Siyasetçi:** {c.politician} ({c.politician_party or 'Parti bilinmiyor'})",
            f"- **Şirket:** {c.organization}",
            f"- **İhale Tarihi:** {c.tender_date}",
            f"- **Savunuculuk Tarihi:** {c.advocacy_date}",
            f"- **Fark:** {abs(c.days_difference)} gün {direction}",
            f"- **Güven Skoru:** {c.confidence:.2f}",
            "",
        ])
    
    return "\n".join(lines)

