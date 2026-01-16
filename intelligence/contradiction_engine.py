"""
Contradiction Engine for Political Statement Analysis.

Uses semantic search (RAG) and LLM verification to detect contradictions,
U-turns, and inconsistencies in political statements.

Author: ReguSense Team
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from thefuzz import process as fuzz_process

logger = logging.getLogger(__name__)


class ContradictionType(Enum):
    """Types of contradictions detected."""
    REVERSAL = "REVERSAL"           # Complete reversal of position
    BROKEN_PROMISE = "BROKEN_PROMISE"  # Failed to deliver on promise
    INCONSISTENCY = "INCONSISTENCY"  # Inconsistent statements
    NONE = "NONE"                    # No contradiction


@dataclass
class ContradictionResult:
    """Result of a contradiction detection analysis.
    
    Attributes:
        new_statement: The new statement being analyzed
        speaker: Speaker of the new statement
        historical_matches: List of matching historical statements
        contradiction_score: 0-100 score (higher = more contradictory)
        contradiction_type: Type of contradiction detected
        explanation: Turkish explanation of the contradiction
        key_conflict_points: List of specific conflict points
        is_contradiction: Whether score exceeds threshold (default 70)
        analysis_timestamp: When the analysis was performed
    """
    new_statement: str
    speaker: str = ""
    historical_matches: list[dict] = field(default_factory=list)
    contradiction_score: int = 0
    contradiction_type: ContradictionType = ContradictionType.NONE
    explanation: str = ""
    key_conflict_points: list[str] = field(default_factory=list)
    is_contradiction: bool = False
    analysis_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "new_statement": self.new_statement,
            "speaker": self.speaker,
            "historical_matches": self.historical_matches,
            "contradiction_score": self.contradiction_score,
            "contradiction_type": self.contradiction_type.value,
            "explanation": self.explanation,
            "key_conflict_points": self.key_conflict_points,
            "is_contradiction": self.is_contradiction,
            "analysis_timestamp": self.analysis_timestamp,
        }
    
    def __str__(self) -> str:
        """Human-readable representation."""
        status = "⚠️ CONTRADICTION" if self.is_contradiction else "✓ Consistent"
        return (
            f"{status}\n"
            f"  Score: {self.contradiction_score}/100\n"
            f"  Type: {self.contradiction_type.value}\n"
            f"  Speaker: {self.speaker}\n"
            f"  Explanation: {self.explanation}"
        )


class ContradictionDetector:
    """Detects contradictions between new and historical political statements.
    
    Uses a 3-step process:
    1. Retrieval: Find semantically similar historical statements
    2. Verification: Use LLM to analyze for contradictions
    3. Scoring: Return structured contradiction assessment
    
    Example:
        >>> from memory.vector_store import PoliticalMemory
        >>> from intelligence.gemini_analyzer import GeminiAnalyst
        >>> 
        >>> memory = PoliticalMemory()
        >>> analyzer = GeminiAnalyst()
        >>> detector = ContradictionDetector(memory, analyzer)
        >>> 
        >>> result = detector.detect(
        ...     "Enflasyon tek haneye düşecek",
        ...     speaker="Mehmet Şimşek"
        ... )
        >>> print(result.contradiction_score)
    """
    
    DEFAULT_TOP_K = 5
    DEFAULT_THRESHOLD = 70
    
    def __init__(
        self,
        memory: Any,  # PoliticalMemory
        analyzer: Any,  # GeminiAnalyst
        top_k: int = DEFAULT_TOP_K,
        contradiction_threshold: int = DEFAULT_THRESHOLD,
    ):
        """
        Initialize the contradiction detector.
        
        Args:
            memory: PoliticalMemory instance for vector search
            analyzer: GeminiAnalyst instance for LLM verification
            top_k: Number of historical matches to retrieve
            contradiction_threshold: Score threshold for is_contradiction flag
        """
        self.memory = memory
        self.analyzer = analyzer
        self.top_k = top_k
        self.contradiction_threshold = contradiction_threshold
        self._speaker_cache: Optional[set[str]] = None  # Cache for speaker names
        
        logger.info(f"ContradictionDetector initialized (top_k={top_k}, threshold={contradiction_threshold})")
    
    def _resolve_speaker_name(
        self,
        input_name: str,
        min_score: int = 65,
    ) -> tuple[str, int]:
        """
        Resolve a user-provided speaker name to the official name in the database.
        
        Uses fuzzy matching to find the best match from known speakers.
        Handles Turkish characters correctly.
        
        Args:
            input_name: User-provided speaker name (e.g., "Mahinur")
            min_score: Minimum fuzzy match score to accept (0-100)
            
        Returns:
            Tuple of (resolved_name, match_score)
            If no good match found, returns (input_name, 0)
        """
        if not input_name or not input_name.strip():
            return (input_name, 0)
        
        # Get unique speakers from memory (cache for performance)
        if self._speaker_cache is None:
            self._speaker_cache = self.memory.get_unique_speakers()
            logger.debug(f"Loaded {len(self._speaker_cache)} unique speakers into cache")
        
        if not self._speaker_cache:
            logger.debug("No speakers in database, returning input as-is")
            return (input_name, 0)
        
        # Convert to list for thefuzz
        speaker_list = list(self._speaker_cache)
        
        # Use thefuzz to find best match
        try:
            result = fuzz_process.extractOne(
                input_name,
                speaker_list,
                score_cutoff=0,  # Get result even if low score
            )
            
            if result:
                matched_name, score = result[0], result[1]
                
                if score >= min_score:
                    logger.info(
                        f"Resolved speaker: '{input_name}' → '{matched_name}' (Score: {score})"
                    )
                    return (matched_name, score)
                else:
                    logger.warning(
                        f"Low match score for '{input_name}': best match '{matched_name}' "
                        f"with score {score} (threshold: {min_score})"
                    )
                    return (input_name, score)
            
        except Exception as e:
            logger.warning(f"Fuzzy matching failed: {e}")
        
        return (input_name, 0)
    
    def clear_speaker_cache(self) -> None:
        """Clear the speaker name cache (call after ingesting new data)."""
        self._speaker_cache = None
        logger.debug("Speaker cache cleared")
    
    def _retrieve(
        self,
        query: str,
        speaker_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Retrieve relevant historical statements.
        
        Args:
            query: The new statement to search against
            speaker_filter: Optional filter by speaker name
            
        Returns:
            List of matched statements as dictionaries
        """
        matches = self.memory.search(
            query_text=query,
            top_k=self.top_k,
            speaker_filter=speaker_filter,
        )
        
        # Convert to dict format
        return [
            {
                "text": m.text,
                "speaker": m.speaker,
                "date": m.date,
                "similarity": m.similarity,
                "source": m.source,
                "source_type": m.source_type,
                "page_number": m.page_number,
            }
            for m in matches
        ]
    
    def _verify(
        self,
        new_statement: str,
        historical_statements: list[dict],
        speaker: str = "",
    ) -> dict:
        """
        Verify contradictions using LLM.
        
        Args:
            new_statement: The new statement
            historical_statements: List of historical statement dicts
            speaker: Speaker name for context
            
        Returns:
            LLM analysis result as dictionary
        """
        # Use the analyzer's contradiction analysis method
        return self.analyzer.analyze_contradiction(
            new_statement=new_statement,
            historical_statements=historical_statements,
            speaker=speaker,
        )
    
    def detect(
        self,
        new_statement: str,
        speaker: str = "",
        filter_by_speaker: bool = True,
    ) -> ContradictionResult:
        """
        Detect contradictions for a new statement.
        
        Args:
            new_statement: The new political statement to analyze
            speaker: Speaker of the new statement
            filter_by_speaker: Whether to filter historical search by speaker
            
        Returns:
            ContradictionResult with full analysis
        """
        if not new_statement or not new_statement.strip():
            return ContradictionResult(
                new_statement=new_statement,
                explanation="Empty statement provided",
            )
        
        # Resolve speaker name using fuzzy matching
        resolved_speaker = speaker
        if speaker:
            resolved_speaker, match_score = self._resolve_speaker_name(speaker)
            if resolved_speaker != speaker:
                logger.info(
                    f"Using resolved speaker name: '{resolved_speaker}' "
                    f"(original: '{speaker}', score: {match_score})"
                )
        
        logger.info(f"Analyzing statement: \"{new_statement[:50]}...\" by {resolved_speaker}")
        
        # Step 1: Retrieve historical matches (using resolved name)
        speaker_filter = resolved_speaker if filter_by_speaker and resolved_speaker else None
        historical_matches = self._retrieve(new_statement, speaker_filter)
        
        if not historical_matches:
            logger.info("No historical matches found")
            return ContradictionResult(
                new_statement=new_statement,
                speaker=resolved_speaker,
                explanation="Geçmiş kayıtlarda benzer bir açıklama bulunamadı.",
            )
        
        logger.info(f"Found {len(historical_matches)} historical matches")
        
        # Step 2: LLM Verification
        try:
            analysis = self._verify(new_statement, historical_matches, resolved_speaker)
        except Exception as e:
            logger.error(f"LLM verification failed: {e}")
            return ContradictionResult(
                new_statement=new_statement,
                speaker=resolved_speaker,
                historical_matches=historical_matches,
                explanation=f"Analiz hatası: {str(e)}",
            )
        
        # Step 3: Build result
        score = analysis.get("contradiction_score", 0)
        type_str = analysis.get("contradiction_type", "NONE")
        
        try:
            contradiction_type = ContradictionType(type_str)
        except ValueError:
            contradiction_type = ContradictionType.NONE
        
        result = ContradictionResult(
            new_statement=new_statement,
            speaker=resolved_speaker,  # Use resolved name
            historical_matches=historical_matches,
            contradiction_score=score,
            contradiction_type=contradiction_type,
            explanation=analysis.get("explanation", ""),
            key_conflict_points=analysis.get("key_conflict_points", []),
            is_contradiction=score >= self.contradiction_threshold,
        )
        
        logger.info(f"Analysis complete: score={score}, is_contradiction={result.is_contradiction}")
        
        return result
    
    def detect_batch(
        self,
        statements: list[dict],
    ) -> list[ContradictionResult]:
        """
        Analyze multiple statements.
        
        Args:
            statements: List of dicts with 'text' and optional 'speaker' keys
            
        Returns:
            List of ContradictionResult objects
        """
        results = []
        
        for i, stmt in enumerate(statements):
            text = stmt.get("text", "")
            speaker = stmt.get("speaker", "")
            
            logger.info(f"Processing statement {i+1}/{len(statements)}")
            result = self.detect(text, speaker)
            results.append(result)
        
        return results
