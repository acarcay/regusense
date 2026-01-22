"""
Cascade Processor: Multi-tier processing funnel for efficient statement scanning.

Architecture:
    L0 (Fast Regex)     → Check if ANY keyword exists (microseconds)
    L1 (Light NER)      → If L0 hits, run small NER on context window
    L2 (Heavy TRF)      → Only for conflicts, run Transformer + Consensus
    
This avoids running expensive Transformer models on all 70K statements.
Typically 90%+ of data is filtered at L0/L1 level.
"""

import re
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class MatchResult(Enum):
    """Classification result from cascade processing."""
    SKIP = "skip"               # No keyword found (L0 filter)
    CLEAR_ORG = "clear_org"     # Definitely a company mention
    CLEAR_PERSON = "clear_person"  # Definitely a person reference
    CONFLICT = "conflict"       # Needs HITL review


@dataclass
class CascadeResult:
    """Result from cascade processing a single match."""
    decision: MatchResult
    keyword: str
    company_name: Optional[str] = None
    mersis_no: Optional[str] = None
    confidence: float = 0.0
    method: str = "L0"  # L0, L1_NoConflict, L1, L2, L2_HITL


class CascadeProcessor:
    """
    Multi-tier processing engine for company mention detection.
    
    Usage:
        processor = CascadeProcessor(keyword_map, ambiguous_set, nlp_light, nlp_heavy)
        results = processor.process(statement_text, speaker_name)
    """
    
    # Corporate suffixes that strongly indicate organization context
    CORPORATE_SUFFIXES = {
        "holding", "inşaat", "aş", "a.ş", "a.ş.", "ltd", "limited", 
        "şirketi", "grup", "yapı", "sanayi", "ticaret", "turizm", 
        "enerji", "yatırım", "maden", "madencilik"
    }
    
    def __init__(
        self, 
        keyword_map: dict[str, tuple[str, str]],
        ambiguous_set: set[str],
        nlp_light = None,  # Spacy sm model (optional)
        nlp_heavy = None,  # Spacy trf model (optional)
    ):
        """
        Initialize cascade processor.
        
        Args:
            keyword_map: {keyword: (company_name, mersis_no)}
            ambiguous_set: Set of keywords that need extra validation
            nlp_light: Spacy small model for L1
            nlp_heavy: Spacy transformer model for L2
        """
        self.keyword_map = keyword_map
        self.ambiguous = ambiguous_set
        self.nlp_light = nlp_light
        self.nlp_heavy = nlp_heavy
        
        # Pre-compile L0 regex (all keywords in one giant pattern)
        all_keywords = sorted(keyword_map.keys(), key=len, reverse=True)
        if all_keywords:
            pattern_str = r'\b(' + '|'.join(map(re.escape, all_keywords)) + r')\b'
            self._l0_pattern = re.compile(pattern_str, re.IGNORECASE)
        else:
            self._l0_pattern = None
        
        logger.info(
            f"CascadeProcessor initialized: {len(keyword_map)} keywords, "
            f"{len(ambiguous_set)} ambiguous, "
            f"L1={'ON' if nlp_light else 'OFF'}, L2={'ON' if nlp_heavy else 'OFF'}"
        )
    
    def process(
        self, 
        text: str, 
        speaker_name: str = "",
        masked_text: Optional[str] = None,
    ) -> list[CascadeResult]:
        """
        Process a statement through the cascade.
        
        Args:
            text: Original statement text
            speaker_name: Speaker name for self-reference check
            masked_text: Pre-masked text (politician names replaced)
            
        Returns:
            List of CascadeResult for each detected company mention
        """
        if not text or not self._l0_pattern:
            return []
        
        # Use masked text if provided, otherwise original
        search_text = masked_text or text
        
        # ========== L0: Fast Regex ==========
        l0_matches = self._l0_pattern.findall(search_text)
        if not l0_matches:
            return []  # Skip entirely - no keywords found
        
        results = []
        seen_companies = set()
        
        for kw in set(l0_matches):
            kw_lower = kw.lower()
            
            # Skip if we already matched this company
            company_info = self.keyword_map.get(kw_lower)
            if not company_info:
                continue
            company_name, mersis = company_info
            if mersis in seen_companies:
                continue
            
            # ========== L1: Context Check ==========
            if kw_lower not in self.ambiguous:
                # Non-ambiguous keyword: directly accept
                results.append(CascadeResult(
                    decision=MatchResult.CLEAR_ORG,
                    keyword=kw,
                    company_name=company_name,
                    mersis_no=mersis,
                    confidence=0.9,
                    method="L1_NoConflict"
                ))
                seen_companies.add(mersis)
                continue
            
            # Ambiguous keyword: check context
            context = self._get_context(text, kw)
            l1_result = self._run_l1_check(context, kw)
            
            if l1_result == MatchResult.CLEAR_ORG:
                results.append(CascadeResult(
                    decision=MatchResult.CLEAR_ORG,
                    keyword=kw,
                    company_name=company_name,
                    mersis_no=mersis,
                    confidence=0.8,
                    method="L1_Suffix"
                ))
                seen_companies.add(mersis)
            elif l1_result == MatchResult.CLEAR_PERSON:
                # Skip: definitely a person reference
                continue
            else:
                # ========== L2: Heavy NER + Consensus ==========
                l2_result = self._run_l2_consensus(context, kw)
                
                if l2_result == MatchResult.CLEAR_ORG:
                    results.append(CascadeResult(
                        decision=MatchResult.CLEAR_ORG,
                        keyword=kw,
                        company_name=company_name,
                        mersis_no=mersis,
                        confidence=0.85,
                        method="L2_Consensus"
                    ))
                    seen_companies.add(mersis)
                elif l2_result == MatchResult.CONFLICT:
                    # Send to HITL
                    results.append(CascadeResult(
                        decision=MatchResult.CONFLICT,
                        keyword=kw,
                        company_name=company_name,
                        mersis_no=mersis,
                        confidence=0.5,
                        method="L2_HITL"
                    ))
                    seen_companies.add(mersis)
                # If CLEAR_PERSON, skip
        
        return results
    
    def _get_context(self, text: str, keyword: str, window: int = 50) -> str:
        """Extract context window around keyword."""
        text_lower = text.lower()
        kw_lower = keyword.lower()
        
        idx = text_lower.find(kw_lower)
        if idx == -1:
            return text[:100]  # Fallback
        
        start = max(0, idx - window)
        end = min(len(text), idx + len(keyword) + window)
        return text[start:end]
    
    def _run_l1_check(self, context: str, keyword: str) -> MatchResult:
        """
        L1: Fast heuristic check using suffix rules.
        
        If keyword is followed by a corporate suffix, it's likely an org.
        If preceded by honorifics (Sayın, Bay), it's likely a person.
        """
        context_lower = context.lower()
        kw_lower = keyword.lower()
        
        # Find keyword position in context
        idx = context_lower.find(kw_lower)
        if idx == -1:
            return MatchResult.CONFLICT
        
        # Check for corporate suffix after keyword
        after_kw = context_lower[idx + len(kw_lower):].strip()
        first_word_after = after_kw.split()[0] if after_kw.split() else ""
        first_word_after = re.sub(r'[^\w]', '', first_word_after)
        
        if first_word_after in self.CORPORATE_SUFFIXES:
            return MatchResult.CLEAR_ORG
        
        # Check for honorific before keyword
        before_kw = context_lower[:idx].strip()
        words_before = before_kw.split()
        last_word_before = words_before[-1] if words_before else ""
        last_word_before = re.sub(r'[^\w]', '', last_word_before)
        
        honorifics = {"sayın", "bay", "bayan", "başkan", "bakan", "vekili", "milletvekili"}
        if last_word_before in honorifics:
            return MatchResult.CLEAR_PERSON
        
        # If we have light NER, use it
        if self.nlp_light:
            try:
                doc = self.nlp_light(context)
                for ent in doc.ents:
                    if kw_lower in ent.text.lower():
                        if ent.label_ == "PERSON":
                            return MatchResult.CLEAR_PERSON
                        elif ent.label_ == "ORG":
                            return MatchResult.CLEAR_ORG
            except Exception as e:
                logger.warning(f"L1 NER failed: {e}")
        
        return MatchResult.CONFLICT
    
    def _run_l2_consensus(self, context: str, keyword: str) -> MatchResult:
        """
        L2: Heavy NER with consensus voting.
        
        Runs Transformer model and combines with rule-based check.
        If there's disagreement, returns CONFLICT for HITL.
        """
        votes = []
        
        # Vote 1: Suffix rule (already computed in L1, but we can re-check)
        suffix_vote = self._suffix_vote(context, keyword)
        votes.append(suffix_vote)
        
        # Vote 2: Heavy NER
        if self.nlp_heavy:
            try:
                doc = self.nlp_heavy(context)
                ner_vote = "UNKNOWN"
                kw_lower = keyword.lower()
                for ent in doc.ents:
                    if kw_lower in ent.text.lower():
                        ner_vote = ent.label_
                        break
                votes.append(ner_vote)
            except Exception as e:
                logger.warning(f"L2 NER failed: {e}")
                votes.append("UNKNOWN")
        else:
            votes.append("UNKNOWN")
        
        # Vote 3: Context keyword check (ihale, pazarlık, etc.)
        context_vote = self._context_vote(context)
        votes.append(context_vote)
        
        # Tally votes
        org_votes = sum(1 for v in votes if v in ("ORG", "CORPORATE"))
        person_votes = sum(1 for v in votes if v == "PERSON")
        
        if org_votes >= 2:
            return MatchResult.CLEAR_ORG
        if person_votes >= 2:
            return MatchResult.CLEAR_PERSON
        return MatchResult.CONFLICT
    
    def _suffix_vote(self, context: str, keyword: str) -> str:
        """Check if keyword is followed by corporate suffix."""
        context_lower = context.lower()
        kw_lower = keyword.lower()
        idx = context_lower.find(kw_lower)
        if idx == -1:
            return "UNKNOWN"
        
        after = context_lower[idx + len(kw_lower):].strip()
        first_word = after.split()[0] if after.split() else ""
        first_word = re.sub(r'[^\w]', '', first_word)
        
        return "ORG" if first_word in self.CORPORATE_SUFFIXES else "UNKNOWN"
    
    def _context_vote(self, context: str) -> str:
        """Check for high-stakes context keywords."""
        context_lower = context.lower()
        corporate_context = {"ihale", "pazarlık", "sözleşme", "bedeli", "proje", "inşaat", "yapım"}
        
        if any(kw in context_lower for kw in corporate_context):
            return "CORPORATE"
        return "UNKNOWN"
