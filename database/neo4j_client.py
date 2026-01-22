"""
Neo4j Client: Async driver wrapper for graph database operations.

Provides connection management and Cypher query execution
with weighted conflict scoring and temporal decay support.
"""

import os
import asyncio
import logging
from datetime import date
from typing import Optional, Any
from contextlib import asynccontextmanager

from neo4j import AsyncGraphDatabase, AsyncDriver
from neo4j.exceptions import ServiceUnavailable, AuthError

logger = logging.getLogger(__name__)

# Connection settings (loaded from environment or defaults)
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "regusense_dev")

# Singleton driver instance
_driver: Optional[AsyncDriver] = None


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

_driver = None
_driver_loop = None

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
        logger.info(f"Connecting to Neo4j at {NEO4J_URI}")
        _driver = AsyncGraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
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
            return records[0] if records else {}
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
    party: str = "",
) -> dict:
    """Create or merge a Politician node."""
    cypher = """
    MERGE (p:Politician {pg_id: $pg_id})
    SET p.name = $name,
        p.normalized_name = $normalized_name,
        p.party = $party,
        p.updated_at = datetime()
    RETURN p
    """
    return await run_write(cypher, {
        "pg_id": pg_id,
        "name": name,
        "normalized_name": normalized_name,
        "party": party,
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


async def update_politician_party(
    pg_id: int,
    party: str,
    is_opposition: bool,
) -> dict:
    """
    Update politician with party affiliation and opposition flag.
    
    Args:
        pg_id: Politician PG ID
        party: Party name (AKP, CHP, etc.)
        is_opposition: True if opposition party
    """
    cypher = """
    MATCH (p:Politician {pg_id: $pg_id})
    SET p.party = $party,
        p.is_opposition = $is_opposition,
        p.updated_at = datetime()
    RETURN p
    """
    return await run_write(cypher, {
        "pg_id": pg_id,
        "party": party,
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

