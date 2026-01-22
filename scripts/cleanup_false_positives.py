"""
Script to cleanup False Positive relationships from Neo4j.

It re-validates all MENTIONED_BY relationships using the new filter logic.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT))

import asyncio
import re
from database import neo4j_client
import logging

import spacy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load Spacy model
try:
    nlp = spacy.load("tr_core_news_trf")
    logger.info("Spacy Turkish Transformer model loaded successfully")
except Exception as e:
    logger.warning(f"Failed to load Spacy model: {e}. Running without NER...")
    nlp = None

# Strict Filtering Configuration
AMBIGUOUS_KEYWORDS = {"cengiz", "yüksel", "kalyon", "bayburt", "demir", "çelik", "özdemir", "kolin"}
STRICT_SUFFIXES = {"holding", "inşaat", "aş", "a.ş", "limited", "şirketi", "grup", "yapı", "sanayi", "ticaret", "turizm", "enerji"}

# Global cache for politicians (loaded at runtime)
KNOWN_POLITICIANS = set()

async def load_politicians():
    """Load all politician names for blacklist."""
    logger.info("Loading politician blacklist...")
    cypher = "MATCH (p:Politician) RETURN p.name as name"
    results = await neo4j_client.run_query(cypher)
    for row in results:
        name = row['name'].lower()
        KNOWN_POLITICIANS.add(name)
    logger.info(f"Loaded {len(KNOWN_POLITICIANS)} politicians into blacklist")

def is_valid_match(text: str, match: re.Match, speaker_name: str) -> bool:
    """
    Ruthless validation logic.
    """
    matched_text = text[match.start():match.end()]
    matched_lower = matched_text.lower()
    
    # 0. Self-Reference Check (Speaker Name contains keyword -> Reject)
    # e.g. Speaker "Cüneyt Yüksel" saying "...Yüksel..." -> Reject
    if speaker_name and matched_lower in speaker_name.lower():
        return False

    # 1. Regex Context (Titles - "Sayın" etc.) - Still useful
    context_start = max(0, match.start() - 30)
    pre_context = text[context_start:match.start()].lower()
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
    # Check if surrounding words form a Politician Name
    post_context = text[match.end() : min(len(text), match.end()+20)].lower()
    post_words = post_context.split()
    next_word = re.sub(r'[^\w]', '', post_words[0]) if post_words else ""
    
    pre_context_short = text[max(0, match.start()-20) : match.start()].lower()
    pre_words = pre_context_short.split()
    prev_word = re.sub(r'[^\w]', '', pre_words[-1]) if pre_words else ""
    
    matched_clean = re.sub(r'[^\w]', '', matched_lower)
    
    candidates = []
    if next_word: candidates.append(f"{matched_clean} {next_word}")
    if prev_word: candidates.append(f"{prev_word} {matched_clean}")
    
    for cand in candidates:
        if cand in KNOWN_POLITICIANS:
            return False
            
    return True

async def cleanup_false_positives():
    logger.info("Starting cleanup of False Positives...")
    
    # Fetch relationships + Speaker Name
    cypher = """
    MATCH (p:Politician)-[:MADE]->(s:Statement)-[r:MENTIONED_BY]->(o:Organization)
    WHERE s.text IS NOT NULL
    RETURN elementId(r) as rel_id, s.text as text, r.matched_keyword as keyword, p.name as speaker
    UNION
    MATCH (s:Statement)-[r:MENTIONED_BY]->(o:Organization)
    WHERE s.text IS NOT NULL AND NOT ( (:Politician)-[:MADE]->(s) )
    RETURN elementId(r) as rel_id, s.text as text, r.matched_keyword as keyword, "" as speaker
    """
    
    results = await neo4j_client.run_query(cypher)
    logger.info(f"Checking {len(results)} existing relationships...")
    
    deleted_count = 0
    
    for row in results:
        rel_id = row['rel_id']
        text = row['text']
        keyword = row['keyword']
        speaker = row.get('speaker', "")
        
        # Re-validate
        text_lower = text.lower()
        pattern = r'\b' + re.escape(keyword) + r'\b'
        matches = list(re.finditer(pattern, text_lower))
        
        if matches:
            final_validity = False
            for match in matches:
                if is_valid_match(text, match, speaker):
                    final_validity = True
                    break
            
            if not final_validity:
                del_cypher = "MATCH ()-[r]->() WHERE elementId(r) = $rel_id DELETE r"
                await neo4j_client.run_write(del_cypher, {"rel_id": rel_id})
                deleted_count += 1
                if deleted_count % 50 == 0:
                    print(f"Deleted {deleted_count} false positives...")

    logger.info(f"Cleanup Complete. Deleted {deleted_count} relationships.")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(load_politicians())
    loop.run_until_complete(cleanup_false_positives())
