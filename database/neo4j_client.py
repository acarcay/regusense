"""
Neo4j Client: Async driver wrapper for graph database operations.

Provides connection management and Cypher query execution
with weighted conflict scoring and temporal decay support.
"""

import asyncio
import logging
from datetime import date
from typing import Optional, Any
from contextlib import asynccontextmanager

from neo4j import AsyncGraphDatabase, AsyncDriver
from neo4j.exceptions import ServiceUnavailable, AuthError

from config.settings import settings

logger = logging.getLogger(__name__)



# =============================================================================
# Weighted Conflict Scoring
# =============================================================================

CONNECTION_WEIGHTS = {
    "spouse": 1.0,
    "first_degree_relative": 1.0,
    "board_member": 0.9,
    "shareholder": 0.8,
    "founder": 0.8,
    "former_partner": 0.6,
    "advisor": 0.5,
    "lobbyist": 0.5,
    "sector_acquaintance": 0.3,
    "schoolmate": 0.2,
    "unknown": 0.1,
}


def get_connection_weight(connection_type: str) -> float:
    """Get weight for a connection type."""
    return CONNECTION_WEIGHTS.get(connection_type.lower(), 0.1)


def calculate_decay(end_date: Optional[date], years_half_life: int = 5) -> float:
    """
    Calculate temporal decay for a relationship.
    
    Args:
        end_date: When the relationship ended (None if still active)
        years_half_life: Years for weight to halve (default: 5)
        
    Returns:
        Decay factor between 0.0 and 1.0
    """
    if end_date is None:  # Still active
        return 1.0
    
    years_passed = (date.today() - end_date).days / 365
    if years_passed <= 0:
        return 1.0
    
    return 0.5 ** (years_passed / years_half_life)


def calculate_conflict_score(
    connection_type: str,
    end_date: Optional[date] = None,
    sector_relevance: float = 1.0,
) -> float:
    """
    Calculate final weighted conflict score.
    
    Formula: weight × decay × sector_relevance
    
    Returns:
        Score between 0.0 and 1.0
    """
    weight = get_connection_weight(connection_type)
    decay = calculate_decay(end_date)
    return weight * decay * sector_relevance


# =============================================================================
# Driver Management
# =============================================================================

# ---------------------------------------------------------------------------
# Driver singleton — module-level state.
# In Streamlit (multi-loop) environments the driver is re-created when the
# event loop changes. For production multi-threaded use, prefer FastAPI
# lifespan dependency injection over this singleton pattern.
# ---------------------------------------------------------------------------

_driver: Optional[AsyncDriver] = None
_driver_loop: Optional[asyncio.AbstractEventLoop] = None

async def get_driver() -> AsyncDriver:
    """Get or create Neo4j driver (singleton, loop-aware for Streamlit)."""
    global _driver, _driver_loop
    
    current_loop = asyncio.get_running_loop()
    
    # Check if driver exists but belongs to a different (stale) loop
    if _driver and _driver_loop and _driver_loop != current_loop:
        logger.warning(f"Event loop changed ({id(_driver_loop)} -> {id(current_loop)})! Resetting Neo4j driver...")
        # We cannot safely close the old driver from this new loop (would raise Future attached to different loop)
        # So we simply discard the reference and let GC handle it.
        _driver = None
        _driver_loop = None
    
    if _driver is None:
        logger.info(f"Connecting to Neo4j at {settings.neo4j_uri}")
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        _driver_loop = current_loop
        
        # Verify connectivity
        try:
            await _driver.verify_connectivity()
            logger.info("Neo4j connection established")
        except (ServiceUnavailable, AuthError) as e:
            logger.error(f"Neo4j connection failed: {e}")
            _driver = None
            _driver_loop = None
            raise
    
    return _driver


async def close_driver():
    """Close the Neo4j driver."""
    global _driver, _driver_loop
    
    if _driver:
        current_loop = asyncio.get_running_loop()
        
        # Only attempt to await close() if we are in the same loop
        if _driver_loop == current_loop:
            try:
                await _driver.close()
                logger.info("Neo4j driver closed")
            except Exception as e:
                logger.warning(f"Error closing Neo4j driver: {e}")
        else:
            logger.warning("Attempted to close driver from different loop. Discarding without clean close.")
            
        _driver = None
        _driver_loop = None


@asynccontextmanager
async def get_session():
    """Get a Neo4j session context manager."""
    driver = await get_driver()
    session = driver.session()
    try:
        yield session
    finally:
        await session.close()


async def load_politicians_for_masking() -> list[tuple[int, str]]:
    """
    Load all politicians as (pg_id, name) tuples for Entity Masking.
    
    Returns:
        List of (pg_id, full_name) tuples sorted by name length (longest first)
    """
    cypher = "MATCH (p:Politician) RETURN p.pg_id as id, p.name as name"
    results = await run_query(cypher)
    politicians = [(r['id'], r['name']) for r in results if r['name']]
    logger.info(f"Loaded {len(politicians)} politicians for masking")
    return politicians


async def get_dynamic_ambiguous_keywords() -> set[str]:
    """
    Find politician surnames that overlap with Organization names/keywords.
    
    This replaces the static AMBIGUOUS_KEYWORDS list with database-driven logic.
    When a new politician like "Koç" is added, the system automatically detects
    the overlap with "Koç Holding" without code changes.
    
    Returns:
        Set of lowercase surnames that are also found in organization names
    """
    # Extract surname as the last word from politician name
    cypher = """
    MATCH (p:Politician), (o:Organization)
    WHERE p.name IS NOT NULL AND o.name IS NOT NULL
    WITH p, o, split(p.name, ' ')[-1] AS surname
    WHERE size(surname) >= 3
      AND (toLower(o.name) CONTAINS toLower(surname)
           OR ANY(kw IN o.keywords WHERE toLower(kw) = toLower(surname)))
    RETURN DISTINCT toLower(surname) as ambiguous_keyword
    """
    results = await run_query(cypher)
    keywords = {r['ambiguous_keyword'] for r in results if r['ambiguous_keyword']}
    logger.info(f"Detected {len(keywords)} dynamic ambiguous keywords from Neo4j")
    return keywords


# =============================================================================
# Query Execution
# =============================================================================

async def run_query(
    cypher: str,
    params: Optional[dict] = None,
    return_single: bool = False,
) -> list[dict[str, Any]]:
    """
    Execute a Cypher query and return results.
    
    Args:
        cypher: Cypher query string
        params: Query parameters
        return_single: If True, return only first result
        
    Returns:
        List of result dictionaries
    """
    params = params or {}
    
    async with get_session() as session:
        result = await session.run(cypher, params)
        records = await result.data()
        
        if return_single:
            return [records[0]] if records else []
        return records


async def run_write(cypher: str, params: Optional[dict] = None) -> dict:
    """
    Execute a write transaction.
    
    Returns:
        Summary of the operation
    """
    params = params or {}
    
    async with get_session() as session:
        result = await session.run(cypher, params)
        summary = await result.consume()
        
        return {
            "nodes_created": summary.counters.nodes_created,
            "relationships_created": summary.counters.relationships_created,
            "properties_set": summary.counters.properties_set,
        }


# =============================================================================
# Common Queries
# =============================================================================

async def create_politician(
    pg_id: int,
    name: str,
    normalized_name: str,
) -> dict:
    """Create or merge a Politician node."""
    cypher = """
    MERGE (p:Politician {pg_id: $pg_id})
    SET p.name = $name,
        p.normalized_name = $normalized_name,
        p.updated_at = datetime()
    RETURN p
    """
    return await run_write(cypher, {
        "pg_id": pg_id,
        "name": name,
        "normalized_name": normalized_name,
    })


async def create_political_party(name: str, is_opposition: bool = False) -> dict:
    """Create or merge a PoliticalParty node."""
    cypher = """
    MERGE (p:PoliticalParty {name: $name})
    SET p.is_opposition = $is_opposition,
        p.updated_at = datetime()
    RETURN p
    """
    return await run_write(cypher, {"name": name, "is_opposition": is_opposition})


async def add_politician_role(
    pg_id: int,
    party_name: str,
    title: str,
    term_name: str = "",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """Create a SERVED_IN relationship representing a political term."""
    cypher = """
    MATCH (p:Politician {pg_id: $pg_id})
    MATCH (party:PoliticalParty {name: $party_name})
    MERGE (p)-[r:SERVED_IN {title: $title, term_name: $term_name}]->(party)
    SET r.start_date = $start_date,
        r.end_date = $end_date,
        r.updated_at = datetime()
    RETURN r
    """
    return await run_write(cypher, {
        "pg_id": pg_id,
        "party_name": party_name,
        "title": title,
        "term_name": term_name,
        "start_date": start_date,
        "end_date": end_date,
    })


async def create_speech(pg_id: int, content: str, date: str, term_name: str, raw_speaker_name: str) -> dict:
    """Create a Speech node in Neo4j representing a statement in TBMM."""
    cypher = """
    MERGE (s:Speech {pg_id: $pg_id})
    SET s.content = $content,
        s.date = $date,
        s.term_name = $term_name,
        s.raw_speaker_name = $raw_speaker_name,
        s.updated_at = datetime()
    RETURN s
    """
    return await run_write(cypher, {
        "pg_id": pg_id,
        "content": content,
        "date": date,
        "term_name": term_name,
        "raw_speaker_name": raw_speaker_name
    })

async def add_made_speech_relation(speaker_pg_id: int, speech_pg_id: int) -> dict:
    """Link a Politician to their Speech."""
    cypher = """
    MATCH (p:Politician {pg_id: $speaker_pg_id})
    MATCH (s:Speech {pg_id: $speech_pg_id})
    MERGE (p)-[r:MADE_SPEECH]->(s)
    SET r.updated_at = datetime()
    RETURN r
    """
    return await run_write(cypher, {
        "speaker_pg_id": speaker_pg_id,
        "speech_pg_id": speech_pg_id,
    })


async def create_organization(
    name: str,
    mersis_no: Optional[str] = None,
    vergi_no: Optional[str] = None,
    org_type: str = "company",
) -> dict:
    """Create or merge an Organization node."""
    # Use MERSİS as primary key if available
    if mersis_no:
        cypher = """
        MERGE (o:Organization {mersis_no: $mersis_no})
        SET o.name = $name,
            o.vergi_no = $vergi_no,
            o.type = $org_type,
            o.updated_at = datetime()
        RETURN o
        """
    else:
        cypher = """
        MERGE (o:Organization {name: $name})
        SET o.vergi_no = $vergi_no,
            o.type = $org_type,
            o.updated_at = datetime()
        RETURN o
        """
    
    return await run_write(cypher, {
        "name": name,
        "mersis_no": mersis_no,
        "vergi_no": vergi_no,
        "org_type": org_type,
    })


async def create_sector(code: str, name: str) -> dict:
    """Create or merge a Sector node."""
    cypher = """
    MERGE (s:Sector {code: $code})
    SET s.name = $name
    RETURN s
    """
    return await run_write(cypher, {"code": code, "name": name})


async def connect_politician_to_org(
    politician_id: int,
    org_mersis: str,
    connection_type: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    source: str = "",
) -> dict:
    """Create CONNECTED_TO relationship with weight."""
    weight = get_connection_weight(connection_type)
    
    cypher = """
    MATCH (p:Politician {pg_id: $politician_id})
    MATCH (o:Organization {mersis_no: $org_mersis})
    MERGE (p)-[r:CONNECTED_TO]->(o)
    SET r.type = $connection_type,
        r.weight = $weight,
        r.start_date = $start_date,
        r.end_date = $end_date,
        r.source = $source,
        r.last_verified = date()
    RETURN r
    """
    return await run_write(cypher, {
        "politician_id": politician_id,
        "org_mersis": org_mersis,
        "connection_type": connection_type,
        "weight": weight,
        "start_date": start_date,
        "end_date": end_date,
        "source": source,
    })


async def find_conflicts_for_politician(
    politician_name: str,
    sector_code: Optional[str] = None,
) -> list[dict]:
    """
    Find potential conflicts of interest for a politician.
    
    Returns organizations connected to the politician,
    optionally filtered by sector.
    """
    if sector_code:
        cypher = """
        MATCH (p:Politician {normalized_name: $name})-[r:CONNECTED_TO]->(o:Organization)
        MATCH (o)-[:OPERATES_IN]->(s:Sector {code: $sector_code})
        RETURN p.name AS politician,
               o.name AS organization,
               o.mersis_no AS mersis,
               r.type AS connection_type,
               r.weight AS weight,
               r.end_date AS end_date,
               s.name AS sector
        ORDER BY r.weight DESC
        """
        params = {"name": politician_name, "sector_code": sector_code}
    else:
        cypher = """
        MATCH (p:Politician {normalized_name: $name})-[r:CONNECTED_TO]->(o:Organization)
        OPTIONAL MATCH (o)-[:OPERATES_IN]->(s:Sector)
        RETURN p.name AS politician,
               o.name AS organization,
               o.mersis_no AS mersis,
               r.type AS connection_type,
               r.weight AS weight,
               r.end_date AS end_date,
               collect(s.name) AS sectors
        ORDER BY r.weight DESC
        """
        params = {"name": politician_name}
    
    return await run_query(cypher, params)


async def get_politician_network(
    politician_name: str,
    max_hops: int = 2,
    limit: int = 50,
) -> list[dict]:
    """Get the network around a politician (n-hop traversal)."""
    if not isinstance(max_hops, int) or not (1 <= max_hops <= 5):
        raise ValueError(
            f"max_hops must be an integer between 1 and 5, got: {max_hops!r}"
        )
        
    # max_hops is validated above — safe to interpolate (not parameterizable in Neo4j)
    cypher = f"""
    MATCH path = (p:Politician {{normalized_name: $name}})-[*1..{max_hops}]-(connected)
    RETURN path
    LIMIT $limit
    """
    return await run_query(cypher, {"name": politician_name, "limit": limit})


async def get_pending_connection_evidence(
    speaker_id: int,
    company_mersis: str,
    limit: int = 5,
) -> list[dict]:
    """Get sample evidence (statements) for a pending connection."""
    cypher = """
    MATCH (p:Politician {pg_id: $speaker_id})-[:MADE]->(s:Statement)
    MATCH (s)-[r:MENTIONED_BY]->(o:Organization {mersis_no: $mersis})
    RETURN s.pg_id as pg_id,
           s.text as text,
           s.date as date,
           r.matched_keyword as keyword
    ORDER BY s.date DESC
    LIMIT $limit
    """
    return await run_query(cypher, {
        "speaker_id": speaker_id,
        "mersis": company_mersis,
        "limit": limit
    })


# =============================================================================
# Intent-Based Relationships (Phase 8)
# =============================================================================

async def create_criticized_relationship(
    speaker_id: int,
    org_mersis: str,
    statement_id: int,
    confidence: float,
    key_triggers: list[str],
) -> dict:
    """
    Create CRITICIZED relationship (opposition critiquing a company).
    
    This replaces MENTIONED_BY for negative/attack mentions.
    """
    cypher = """
    MATCH (p:Politician {pg_id: $speaker_id})
    MATCH (o:Organization {mersis_no: $mersis})
    MERGE (p)-[r:CRITICIZED]->(o)
    SET r.statement_id = $statement_id,
        r.confidence = $confidence,
        r.key_triggers = $triggers,
        r.created_at = datetime()
    RETURN r
    """
    return await run_write(cypher, {
        "speaker_id": speaker_id,
        "mersis": org_mersis,
        "statement_id": statement_id,
        "confidence": confidence,
        "triggers": key_triggers,
    })


async def create_advocated_relationship(
    speaker_id: int,
    org_mersis: str,
    statement_id: int,
    confidence: float,
    is_conflict_candidate: bool,
    key_triggers: list[str],
) -> dict:
    """
    Create ADVOCATED relationship (speaker defending/supporting a company).
    
    If is_conflict_candidate=True, this is flagged for HITL review.
    """
    cypher = """
    MATCH (p:Politician {pg_id: $speaker_id})
    MATCH (o:Organization {mersis_no: $mersis})
    MERGE (p)-[r:ADVOCATED]->(o)
    SET r.statement_id = $statement_id,
        r.confidence = $confidence,
        r.is_conflict = $is_conflict,
        r.key_triggers = $triggers,
        r.created_at = datetime()
    RETURN r
    """
    return await run_write(cypher, {
        "speaker_id": speaker_id,
        "mersis": org_mersis,
        "statement_id": statement_id,
        "confidence": confidence,
        "is_conflict": is_conflict_candidate,
        "triggers": key_triggers,
    })


async def update_political_party_status(
    party_name: str,
    is_opposition: bool,
) -> dict:
    """
    Update political party opposition flag.
    """
    cypher = """
    MATCH (p:PoliticalParty {name: $party_name})
    SET p.is_opposition = $is_opposition,
        p.updated_at = datetime()
    RETURN p
    """
    return await run_write(cypher, {
        "party_name": party_name,
        "is_opposition": is_opposition,
    })


async def get_conflict_candidates(limit: int = 50) -> list[dict]:
    """
    Get all ADVOCATED relationships marked as conflict candidates.
    
    These are government-bloc speakers defending companies.
    """
    cypher = """
    MATCH (p:Politician)-[r:ADVOCATED {is_conflict: true}]->(o:Organization)
    RETURN p.name as speaker,
           p.party as party,
           o.name as company,
           o.mersis_no as mersis,
           r.confidence as confidence,
           r.key_triggers as triggers,
           r.statement_id as statement_id
    ORDER BY r.confidence DESC
    LIMIT $limit
    """
    return await run_query(cypher, {"limit": limit})


async def get_criticism_stats() -> dict:
    """Get statistics on CRITICIZED vs ADVOCATED relationships."""
    cypher = """
    MATCH ()-[c:CRITICIZED]->()
    WITH count(c) as criticized_count
    MATCH ()-[a:ADVOCATED]->()
    WITH criticized_count, count(a) as advocated_count
    MATCH ()-[ac:ADVOCATED {is_conflict: true}]->()
    RETURN criticized_count,
           advocated_count,
           count(ac) as conflict_candidates
    """
    results = await run_query(cypher)
    if results:
        return results[0]
    return {"criticized_count": 0, "advocated_count": 0, "conflict_candidates": 0}


# =============================================================================
# Temporal Conflict Analysis (Module 4: The Smoking Gun)
# =============================================================================

async def find_temporal_conflicts(
    org_mersis: str,
    tender_date: str,
    window_days: int = 15,
) -> list[dict]:
    """
    Find ADVOCATED relationships within ±window_days of a tender date.
    
    This is the "smoking gun" detector: if a politician advocated for a company
    within 15 days of that company winning a tender, it's a critical conflict.
    
    Args:
        org_mersis: Company MERSIS number
        tender_date: Tender award date (ISO format: YYYY-MM-DD)
        window_days: Days before/after tender to search (default: 15)
        
    Returns:
        List of potential temporal conflicts with:
        - politician_name, party
        - advocacy_date
        - days_difference (negative = before tender, positive = after)
        - statement_id
        - confidence, key_triggers
    """
    cypher = """
    MATCH (p:Politician)-[r:ADVOCATED]->(o:Organization {mersis_no: $mersis})
    WHERE r.created_at IS NOT NULL
    WITH p, r, o,
         date($tender_date) as tender,
         date(r.created_at) as advocacy
    WITH p, r, o, tender, advocacy,
         duration.inDays(tender, advocacy).days as days_diff
    WHERE abs(days_diff) <= $window
    
    // Find the active party during the advocacy date
    OPTIONAL MATCH (p)-[term:SERVED_IN]->(party:PoliticalParty)
    WHERE (term.start_date IS NULL OR date(term.start_date) <= advocacy)
      AND (term.end_date IS NULL OR date(term.end_date) >= advocacy)
      
    RETURN p.name as politician_name,
           party.name as party,
           p.pg_id as politician_id,
           toString(advocacy) as advocacy_date,
           days_diff as days_difference,
           r.statement_id as statement_id,
           r.confidence as confidence,
           r.key_triggers as key_triggers,
           r.is_conflict as is_conflict_candidate,
           o.name as company_name
    ORDER BY abs(days_diff) ASC
    """
    
    try:
        results = await run_query(cypher, {
            "mersis": org_mersis,
            "tender_date": tender_date,
            "window": window_days,
        })
        
        if results:
            logger.info(f"🔥 Found {len(results)} temporal conflicts for {org_mersis} near {tender_date}")
        
        return results
        
    except Exception as e:
        logger.error(f"Temporal conflict query failed: {e}")
        return []


async def find_all_temporal_conflicts(window_days: int = 15) -> list[dict]:
    """
    Scan all EKAP tenders and find temporal conflicts with ADVOCATED relationships.
    
    This is the batch version for full-system analysis.
    
    Returns:
        List of all temporal conflicts detected
    """
    cypher = """
    // Find all organizations with both tenders and advocacy
    MATCH (o:Organization)
    WHERE o.sector = 'CONSTRUCTION' 
      AND EXISTS((o)<-[:ADVOCATED]-(:Politician))
    
    // Get their tender dates from tender nodes if available
    OPTIONAL MATCH (t:Tender)-[:AWARDED_TO]->(o)
    WHERE t.award_date IS NOT NULL
    
    WITH o, collect(DISTINCT t) as tenders
    WHERE size(tenders) > 0
    
    UNWIND tenders as tender
    
    // Find advocacy within window of each tender
    MATCH (p:Politician)-[r:ADVOCATED]->(o)
    WHERE r.created_at IS NOT NULL
    WITH p, r, o, tender,
         date(tender.award_date) as tender_date,
         date(r.created_at) as advocacy_date,
         duration.inDays(date(tender.award_date), date(r.created_at)).days as days_diff
    WHERE abs(days_diff) <= $window
    
    // Find the active party during the advocacy date
    OPTIONAL MATCH (p)-[term:SERVED_IN]->(party:PoliticalParty)
    WHERE (term.start_date IS NULL OR date(term.start_date) <= advocacy_date)
      AND (term.end_date IS NULL OR date(term.end_date) >= advocacy_date)
    
    RETURN p.name as politician_name,
           party.name as party,
           o.name as company_name,
           o.mersis_no as company_mersis,
           tender.ikn as tender_ikn,
           toString(tender_date) as tender_date,
           toString(advocacy_date) as advocacy_date,
           days_diff as days_difference,
           r.statement_id as statement_id,
           CASE 
             WHEN abs(days_diff) <= 3 THEN 'CRITICAL'
             WHEN abs(days_diff) <= 7 THEN 'HIGH'
             ELSE 'MEDIUM'
           END as risk_level
    ORDER BY abs(days_diff) ASC
    """
    
    try:
        results = await run_query(cypher, {"window": window_days})
        logger.info(f"🔥 Temporal conflict scan complete: {len(results)} conflicts found")
        return results
    except Exception as e:
        logger.error(f"Full temporal conflict scan failed: {e}")
        return []
