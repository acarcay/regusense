"""
Hunter Mode: Scan all statements for company mentions.

The "Hunter" scans 70K+ statements and creates MENTIONED_BY 
relationships in Neo4j when a company name is found.

Process:
1. Load all company names/keywords from Neo4j
2. Iterate through PostgreSQL statements
3. For each match: Create (Statement)-[:MENTIONED_BY]->(Organization)
4. Queue suspicious connections for HITL review
"""

import os
import sys
import argparse
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

import asyncio
import logging
import re
import spacy
from typing import Optional, Any, Union, Dict, List, Tuple, Set
from dataclasses import dataclass, field

from database import neo4j_client
from database.session import get_async_session
from database.models import Statement, Speaker
from sqlalchemy import select, func

logger = logging.getLogger(__name__)

from intelligence.entity_masker import get_masker
from intelligence.cascade_processor import CascadeProcessor, MatchResult

@dataclass
class HunterStats:
    """Statistics for the Hunter scan."""
    statements_scanned: int = 0
    matches_found: int = 0
    unique_companies_mentioned: Set[str] = field(default_factory=set)
    speakers_with_mentions: Set[int] = field(default_factory=set)

# Strict Filtering Configuration (these are now loaded dynamically but kept as fallback)
STATIC_AMBIGUOUS_KEYWORDS = {"cengiz", "yüksel", "kalyon", "bayburt", "demir", "çelik", "özdemir", "kolin"}
CORPORATE_TRIGGERS = {"holding", "inşaat", "aş", "a.ş", "şirket", "ihale", "pazarlık", "yapı", "turizm", "enerji", "yatırım", "grup", "maden", "limak"}
STRICT_SUFFIXES = {"holding", "inşaat", "aş", "a.ş", "limited", "şirketi", "grup", "yapı", "sanayi", "ticaret", "turizm", "enerji"}

# Dynamic ambiguous keywords (loaded from Neo4j at runtime)
DYNAMIC_AMBIGUOUS_KEYWORDS: set[str] = set()

# NLP Models for cascade processing
nlp_heavy = None  # Transformer model (expensive)
nlp_light = None  # Small model (cheap) - placeholder for future

# Global cache for politicians
KNOWN_POLITICIANS = set()

# Load Spacy Transformer model (Heavy - L2)
try:
    nlp_heavy = spacy.load("tr_core_news_trf")
    logger.info("Spacy Turkish Transformer model loaded (L2 Heavy)")
except Exception as e:
    logger.warning(f"Failed to load Heavy NER model: {e}. L2 disabled.")
    nlp_heavy = None

# Load Spacy Small model (Light - L1) - optional
try:
    nlp_light = spacy.load("tr_core_news_sm")
    logger.info("Spacy Turkish Small model loaded (L1 Light)")
except Exception:
    nlp_light = None  # Will use heuristics only in L1

async def load_politicians():
    """Load all politician names into the global cache."""
    global KNOWN_POLITICIANS
    cypher = "MATCH (p:Politician) RETURN p.normalized_name as name"
    results = await neo4j_client.run_query(cypher)
    KNOWN_POLITICIANS = {r['name'] for r in results if r['name']}
    logger.info(f"Loaded {len(KNOWN_POLITICIANS)} politicians into cache")

async def load_company_keywords() -> Dict[str, Tuple[str, str]]:
    """
    Load all company keywords from Neo4j.
    Returns: {keyword: (company_name, mersis_no)}
    """
    cypher = """
    MATCH (o:Organization {sector: 'CONSTRUCTION'})
    RETURN o.name as name, o.mersis_no as mersis, o.keywords as keywords
    """
    results = await neo4j_client.run_query(cypher)
    
    keyword_map = {}
    for res in results:
        name = res['name']
        mersis = res['mersis']
        keywords = res['keywords'] or []
        
        # Always add the full name as a keyword
        keyword_map[name.lower()] = (name, mersis)
        
        # Add additional keywords
        for kw in keywords:
            keyword_map[kw.lower()] = (name, mersis)
            
    logger.info(f"Loaded {len(keyword_map)} keywords for {len(results)} companies")
    return keyword_map

def is_valid_match(text: str, match: re.Match, speaker_name: str = "") -> bool:
    """
    Ruthless validation logic.
    """
    start, end = match.span()
    matched_text = text[start:end]
    matched_lower = matched_text.lower()
    text_lower = text.lower()
    
    # 0. Self-Reference Check (Speaker Name contains keyword -> Reject)
    # e.g. Speaker "Cüneyt Yüksel" saying "...Yüksel..." -> Reject
    if speaker_name and matched_lower in speaker_name.lower():
        return False

    # 1. Regex checks
    if matched_lower.islower() and not matched_lower.isdigit():
        return False
        
    context_start = max(0, start - 30)
    pre_context = text[context_start:start].lower()
    clean_pre = re.sub(r'[^\w\s]', '', pre_context).strip()
    words = clean_pre.split()
    if words:
        last_word = words[-1]
        invalid_prefixes = {
            "sayın", "bay", "bayan", "vekili", "bakanı", "bakan", "başkanı", "başkan",
            "üyesi", "üye", "kardeşim", "arkadaşım", "oğlu", "kızı", "eşi",
            "sevgili", "değerli", "milletvekili"
        }
        if last_word in invalid_prefixes:
            return False

    # 2. Strict Ambiguous Keyword Check
    if matched_lower in AMBIGUOUS_KEYWORDS:
        # Check Next Word (Strict Suffix)
        post_text = text[match.end():].strip()
        # Get first real word ignoring punctuation
        post_words = post_text.split()
        
        has_strict_suffix = False
        if post_words:
            next_word = post_words[0]
            next_word_clean = re.sub(r'[^\w]', '', next_word).lower()
            if next_word_clean in STRICT_SUFFIXES:
                has_strict_suffix = True
        
        if not has_strict_suffix:
            # If no strict suffix, check for "High Stakes Context" (ihale, pazarlık) within narrow window
            context_window = text[max(0, match.start()-30) : min(len(text), match.end()+30)].lower()
            risk_keywords = {"ihale", "pazarlık", "kik", "tutar", "sözleşme", "bedeli", "proje"}
            
            if not any(rk in context_window for rk in risk_keywords):
                return False

    # 3. Politician Blacklist (Overlap Check)
    # Check candidates
    post_context = text_lower[end : min(len(text), end+20)]
    post_words = post_context.split()
    next_word = post_words[0] if post_words else ""
    
    pre_words = pre_context.split()
    prev_word = pre_words[-1] if pre_words else ""
    
    prev_word = re.sub(r'[^\w]', '', prev_word)
    next_word = re.sub(r'[^\w]', '', next_word)
    matched_clean = re.sub(r'[^\w]', '', matched_lower)
    
    candidates = []
    if next_word: candidates.append(f"{matched_clean} {next_word}")
    if prev_word: candidates.append(f"{prev_word} {matched_clean}")
    if prev_word and next_word: candidates.append(f"{prev_word} {matched_clean} {next_word}")
        
    for cand in candidates:
        if cand in KNOWN_POLITICIANS:
            return False

    # 4. Spacy NER Fallback
    if nlp:
        try:
            window_start = max(0, start - 50)
            window_end = min(len(text), end + 50)
            window_text = text[window_start:window_end]
            rel_start = start - window_start
            rel_end = end - window_start
            doc = nlp(window_text)
            for ent in doc.ents:
                if ent.start_char <= rel_start and ent.end_char >= rel_end:
                    if ent.label_ == "PERSON":
                        return False
        except Exception:
            pass
            
    return True


def find_company_mentions(
    text: str,
    keyword_map: dict[str, tuple[str, str]],
    speaker_name: str = "",
    min_keyword_length: int = 4,
) -> list[tuple[str, str, str]]:
    """
    Find company mentions in text.
    
    Returns:
        List of (matched_keyword, company_name, mersis_no)
    """
    text_lower = text.lower()
    matches = []
    seen_companies = set()
    
    for keyword, (company_name, mersis) in keyword_map.items():
        if len(keyword) < min_keyword_length:
            continue
        
        # Word boundary search
        pattern = r'\b' + re.escape(keyword) + r'\b'
        
        # Find all matches to validate each
        for match in re.finditer(pattern, text_lower):
            if is_valid_match(text, match, speaker_name):
                if mersis not in seen_companies:
                    matches.append((keyword, company_name, mersis))
                    seen_companies.add(mersis)
                break # Found valid mention for this company, move to next company
    
    return matches


async def create_mentioned_by_relationship(
    statement_pg_id: int,
    statement_text: str,
    statement_date: str,
    company_mersis: str,
    matched_keyword: str,
    speaker_pg_id: int,
) -> bool:
    """Create MENTIONED_BY relationship in Neo4j."""
    
    cypher = """
    MERGE (s:Statement {pg_id: $statement_id})
    SET s.text = $text,
        s.date = $date
    
    WITH s
    MATCH (o:Organization {mersis_no: $mersis})
    MERGE (s)-[r:MENTIONED_BY]->(o)
    SET r.matched_keyword = $keyword,
        r.created_at = datetime()
    
    WITH s, o
    OPTIONAL MATCH (p:Politician {pg_id: $speaker_id})
    FOREACH (_ IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
        MERGE (p)-[:MADE]->(s)
    )
    
    RETURN count(*) as created
    """
    
    try:
        await neo4j_client.run_write(cypher, {
            "statement_id": statement_pg_id,
            "text": statement_text,
            "date": statement_date.isoformat() if hasattr(statement_date, 'isoformat') else str(statement_date),
            "mersis": company_mersis,
            "keyword": matched_keyword,
            "speaker_id": speaker_pg_id,
        })
        return True
    except Exception as e:
        logger.error(f"Failed to create relationship: {e}")
        return False


async def create_pending_connection(
    speaker_id: int,
    speaker_name: str,
    company_mersis: str,
    company_name: str,
    evidence_count: int,
):
    """
    Create a pending connection for HITL review.
    
    This is stored in Neo4j as a PendingConnection node.
    """
    cypher = """
    MERGE (pc:PendingConnection {
        speaker_id: $speaker_id,
        company_mersis: $company_mersis
    })
    SET pc.speaker_name = $speaker_name,
        pc.company_name = $company_name,
        pc.evidence_count = $evidence_count,
        pc.status = 'PENDING',
        pc.created_at = datetime(),
        pc.connection_type = 'UNKNOWN'
    """
    
    await neo4j_client.run_write(cypher, {
        "speaker_id": speaker_id,
        "speaker_name": speaker_name,
        "company_mersis": company_mersis,
        "company_name": company_name,
        "evidence_count": evidence_count,
    })


async def run_hunter_scan(
    batch_size: int = 1000,
    max_statements: Optional[int] = None,
    create_pending_threshold: int = 3,
):
    """
    Run the Hunter scan on all statements.
    
    Args:
        batch_size: Statements per batch
        max_statements: Limit for testing (None = all)
        create_pending_threshold: Min mentions to create pending connection
    """
    logger.info("=" * 60)
    logger.info("🎯 HUNTER MODE: Scanning for Company Mentions (Cascade Processor)")
    logger.info("=" * 60)
    
    # Load politicians for blacklist check
    await load_politicians()
    
    # Initialize Entity Masker (masks politician names before scanning)
    masker = await get_masker()
    logger.info(f"Entity Masker ready with {len(masker.politicians)} politicians")
    
    # Load keywords
    keyword_map = await load_company_keywords()
    
    if not keyword_map:
        logger.error("No company keywords found. Run import_construction_companies.py first.")
        return
    
    # Load dynamic ambiguous keywords from Neo4j (replaces static list)
    global DYNAMIC_AMBIGUOUS_KEYWORDS
    DYNAMIC_AMBIGUOUS_KEYWORDS = await neo4j_client.get_dynamic_ambiguous_keywords()
    # Union with static fallback for safety
    all_ambiguous = DYNAMIC_AMBIGUOUS_KEYWORDS | STATIC_AMBIGUOUS_KEYWORDS
    logger.info(f"Ambiguous keywords: {len(all_ambiguous)} (dynamic: {len(DYNAMIC_AMBIGUOUS_KEYWORDS)})")
    
    # Initialize Cascade Processor
    cascade = CascadeProcessor(
        keyword_map=keyword_map,
        ambiguous_set=all_ambiguous,
        nlp_light=nlp_light,
        nlp_heavy=nlp_heavy,
    )
    
    stats = HunterStats()
    
    # Track speaker-company mention counts for pending connections
    speaker_company_counts: dict[tuple[int, str], int] = {}
    speaker_names: dict[int, str] = {}
    company_names: dict[str, str] = {}
    
    async with get_async_session() as session:
        # Get total count
        total_result = await session.execute(select(func.count(Statement.id)))
        total_statements = total_result.scalar_one()
        
        if max_statements:
            total_statements = min(total_statements, max_statements)
        
        logger.info(f"Scanning {total_statements} statements...")
        
        offset = 0
        
        while offset < total_statements:
            # Fetch batch with speaker info
            query = (
                select(Statement, Speaker)
                .join(Speaker)
                .offset(offset)
                .limit(batch_size)
            )
            
            result = await session.execute(query)
            rows = result.fetchall()
            
            if not rows:
                break
            
            for statement, speaker in rows:
                stats.statements_scanned += 1
                
                # Step 1: Mask politician names to prevent false positives
                masked_text, _ = masker.mask(statement.text)
                
                # Step 2: Run Cascade Processor (L0 → L1 → L2)
                cascade_results = cascade.process(
                    text=statement.text,
                    speaker_name=speaker.name,
                    masked_text=masked_text,
                )
                
                for cr in cascade_results:
                    if cr.decision == MatchResult.CLEAR_ORG:
                        # Definite company mention
                        stats.matches_found += 1
                        stats.unique_companies_mentioned.add(cr.mersis_no)
                        stats.speakers_with_mentions.add(speaker.id)
                        
                        speaker_names[speaker.id] = speaker.name
                        company_names[cr.mersis_no] = cr.company_name
                        
                        key = (speaker.id, cr.mersis_no)
                        speaker_company_counts[key] = speaker_company_counts.get(key, 0) + 1
                        
                        await create_mentioned_by_relationship(
                            statement.id,
                            statement.text,
                            statement.date,
                            cr.mersis_no,
                            cr.keyword,
                            speaker.id,
                        )
                    elif cr.decision == MatchResult.CONFLICT:
                        # Needs HITL review - create pending with special flag
                        logger.debug(f"HITL Queue: {cr.keyword} in statement {statement.id} ({cr.method})")
                        # Track for pending connection creation later
                        speaker_names[speaker.id] = speaker.name
                        company_names[cr.mersis_no] = cr.company_name
                        key = (speaker.id, cr.mersis_no)
                        speaker_company_counts[key] = speaker_company_counts.get(key, 0) + 1
            
            offset += batch_size
            
            if offset % 5000 == 0:
                logger.info(
                    f"  Progress: {offset}/{total_statements} "
                    f"({offset/total_statements*100:.1f}%) - "
                    f"{stats.matches_found} matches"
                )
    
    # Create pending connections for frequent mentioners
    logger.info("Creating pending connections for HITL review...")
    pending_count = 0
    
    for (speaker_id, mersis), count in speaker_company_counts.items():
        if count >= create_pending_threshold:
            await create_pending_connection(
                speaker_id=speaker_id,
                speaker_name=speaker_names.get(speaker_id, "Unknown"),
                company_mersis=mersis,
                company_name=company_names.get(mersis, "Unknown"),
                evidence_count=count,
            )
            pending_count += 1
    
    logger.info("=" * 60)
    logger.info("🎯 HUNTER SCAN COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Statements Scanned: {stats.statements_scanned:,}")
    logger.info(f"  Company Mentions Found: {stats.matches_found:,}")
    logger.info(f"  Unique Companies: {len(stats.unique_companies_mentioned)}")
    logger.info(f"  Speakers with Mentions: {len(stats.speakers_with_mentions)}")
    logger.info(f"  Pending Connections (HITL): {pending_count}")
    logger.info("=" * 60)


async def main():
    parser = argparse.ArgumentParser(description="Scan statements for company mentions.")
    parser.add_argument("--max", type=int, help="Maximum number of statements to scan")
    parser.add_argument("--batch", type=int, default=1000, help="Batch size for scanning")
    parser.add_argument("--threshold", type=int, default=3, help="Evidence threshold for pending connections")
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        await run_hunter_scan(
            batch_size=args.batch,
            max_statements=args.max,
            create_pending_threshold=args.threshold
        )
    except Exception as e:
        logger.error(f"Hunter scan failed: {e}", exc_info=True)
    finally:
        await neo4j_client.close_driver()


if __name__ == "__main__":
    asyncio.run(main())
