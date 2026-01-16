"""
Knowledge Graph-based Contradiction Engine.

Refactored contradiction detection using:
1. Entity extraction (GLiNER/rule-based) for Person, Topic, Date
2. Knowledge Graph for statement-entity relationships
3. Evidence-based LLM analysis with structured output

Output format:
{
    "contradiction_score": 0-10,
    "evidence_1": {"text": "...", "date": "..."},
    "evidence_2": {"text": "...", "date": "..."},
    "explanation": "..."
}

Author: ReguSense Team
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from thefuzz import process as fuzz_process

from intelligence.entity_extractor import EntityExtractor, get_entity_extractor
from intelligence.knowledge_graph import KnowledgeGraph, get_knowledge_graph, EvidencePair

logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================

class ContradictionType(Enum):
    """Types of contradictions detected."""
    REVERSAL = "REVERSAL"              # Complete reversal of position
    BROKEN_PROMISE = "BROKEN_PROMISE"  # Failed to deliver on promise
    INCONSISTENCY = "INCONSISTENCY"    # Inconsistent statements
    PERSONA_SHIFT = "PERSONA_SHIFT"    # Change in persona/stance
    NONE = "NONE"                      # No contradiction


@dataclass
class Evidence:
    """A single piece of evidence."""
    text: str
    date: str = ""
    source: str = ""
    source_type: str = ""
    topics: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "date": self.date,
            "source": self.source,
            "source_type": self.source_type,
            "topics": self.topics,
        }


@dataclass
class ContradictionResult:
    """
    Result of contradiction analysis.
    
    Now uses 0-10 scale and evidence-based format.
    """
    new_statement: str
    speaker: str = ""
    
    # Evidence-based output
    evidence_1: Optional[Evidence] = None
    evidence_2: Optional[Evidence] = None
    
    # Scoring (0-10 scale)
    contradiction_score: int = 0
    contradiction_type: ContradictionType = ContradictionType.NONE
    
    # Analysis
    explanation: str = ""
    key_conflict_points: list[str] = field(default_factory=list)
    
    # Derived
    is_contradiction: bool = False
    analysis_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Legacy compatibility
    historical_matches: list[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "new_statement": self.new_statement,
            "speaker": self.speaker,
            "evidence_1": self.evidence_1.to_dict() if self.evidence_1 else None,
            "evidence_2": self.evidence_2.to_dict() if self.evidence_2 else None,
            "contradiction_score": self.contradiction_score,
            "contradiction_type": self.contradiction_type.value,
            "explanation": self.explanation,
            "key_conflict_points": self.key_conflict_points,
            "is_contradiction": self.is_contradiction,
            "analysis_timestamp": self.analysis_timestamp,
        }
    
    def __str__(self) -> str:
        status = "⚠️ ÇELİŞKİ" if self.is_contradiction else "✓ Tutarlı"
        return (
            f"{status}\n"
            f"  Skor: {self.contradiction_score}/10\n"
            f"  Tip: {self.contradiction_type.value}\n"
            f"  Konuşmacı: {self.speaker}\n"
            f"  Açıklama: {self.explanation}"
        )


# =============================================================================
# Contradiction Detector
# =============================================================================

class ContradictionDetector:
    """
    Knowledge Graph-based contradiction detector.
    
    Process:
    1. Extract entities from new statement (Person, Topic, Date)
    2. Query knowledge graph for related past statements
    3. Find evidence pairs (same speaker, same topic, different times)
    4. Send to LLM for contradiction analysis
    5. Return structured result with score 0-10
    
    Example:
        detector = ContradictionDetector(memory, analyzer)
        result = detector.detect(
            "Enflasyon tek haneye düşecek",
            speaker="Mehmet Şimşek"
        )
        print(f"Skor: {result.contradiction_score}/10")
        print(f"Kanıt 1: {result.evidence_1.text}")
        print(f"Kanıt 2: {result.evidence_2.text}")
    """
    
    DEFAULT_THRESHOLD = 6  # 6/10 = contradiction
    
    def __init__(
        self,
        memory: Any,  # PoliticalMemory for vector search fallback
        analyzer: Any,  # GeminiAnalyst for LLM analysis
        knowledge_graph: Optional[KnowledgeGraph] = None,
        entity_extractor: Optional[EntityExtractor] = None,
        contradiction_threshold: int = DEFAULT_THRESHOLD,
    ):
        """
        Initialize detector.
        
        Args:
            memory: PoliticalMemory for vector search
            analyzer: GeminiAnalyst for LLM
            knowledge_graph: Optional KnowledgeGraph instance
            entity_extractor: Optional EntityExtractor instance
            contradiction_threshold: Score threshold (0-10 scale)
        """
        self.memory = memory
        self.analyzer = analyzer
        self.graph = knowledge_graph or get_knowledge_graph()
        self.extractor = entity_extractor or get_entity_extractor()
        self.contradiction_threshold = contradiction_threshold
        
        self._speaker_cache: Optional[set[str]] = None
        
        logger.info(
            f"ContradictionDetector initialized (threshold={contradiction_threshold}/10, "
            f"graph_statements={self.graph.stats()['total_statements']})"
        )
    
    def _resolve_speaker(self, name: str, min_score: int = 65) -> str:
        """Resolve speaker name using fuzzy matching."""
        if not name or not name.strip():
            return name
        
        if self._speaker_cache is None:
            self._speaker_cache = self.memory.get_unique_speakers()
        
        if not self._speaker_cache:
            return name
        
        try:
            result = fuzz_process.extractOne(name, list(self._speaker_cache))
            if result and result[1] >= min_score:
                logger.info(f"Resolved speaker: '{name}' → '{result[0]}' ({result[1]}%)")
                return result[0]
        except Exception as e:
            logger.debug(f"Fuzzy match failed: {e}")
        
        return name
    
    def _extract_and_index(
        self,
        text: str,
        speaker: str,
        date: str = "",
        source: str = "",
        source_type: str = "",
    ) -> None:
        """Extract entities and add to knowledge graph."""
        result = self.extractor.extract(text)
        
        self.graph.add_statement(
            text=text,
            speaker=speaker,
            topics=result.topics,
            date=date,
            source=source,
            source_type=source_type,
            entities={
                "persons": result.persons,
                "organizations": result.organizations,
            },
        )
    
    def _get_evidence_from_graph(
        self,
        speaker: str,
        topics: list[str],
    ) -> Optional[EvidencePair]:
        """Get best evidence pair from knowledge graph."""
        for topic in topics:
            pairs = self.graph.get_evidence_pairs(
                speaker=speaker,
                topic=topic,
                min_time_delta_days=30,
            )
            if pairs:
                return pairs[0]  # Return best pair
        
        return None
    
    def _get_evidence_from_vector(
        self,
        query: str,
        speaker: str,
    ) -> list[dict]:
        """Fallback to vector search for evidence."""
        matches = self.memory.search(
            query_text=query,
            top_k=5,
            speaker_filter=speaker if speaker else None,
        )
        
        return [
            {
                "text": m.text,
                "date": m.date,
                "speaker": m.speaker,
                "source": m.source,
                "source_type": m.source_type,
            }
            for m in matches
        ]
    
    def _analyze_with_llm(
        self,
        new_statement: str,
        evidence_1: dict,
        evidence_2: Optional[dict],
        speaker: str,
    ) -> dict:
        """
        Send evidence pair to LLM for contradiction analysis.
        
        Uses specialized prompt for evidence-based comparison.
        """
        prompt = f"""Sen bir siyasi çelişki analisti'sin. Aşağıdaki iki açıklamayı karşılaştır.

## Konuşmacı
{speaker}

## Kanıt 1 (Eski Açıklama)
Tarih: {evidence_1.get('date', 'Bilinmiyor')}
Kaynak: {evidence_1.get('source_type', 'Bilinmiyor')}
Açıklama: "{evidence_1.get('text', '')[:1000]}"

## Kanıt 2 (Yeni Açıklama)
Tarih: Şu an
Açıklama: "{new_statement}"

## Görev
Bu iki açıklama arasındaki tutarsızlığı analiz et.

## Yanıt Formatı (JSON)
{{
    "contradiction_score": <0-10 arası puan, 0=tamamen tutarlı, 10=tam çelişki>,
    "contradiction_type": "<REVERSAL|BROKEN_PROMISE|INCONSISTENCY|PERSONA_SHIFT|NONE>",
    "explanation": "<Türkçe açıklama, 1-2 cümle>",
    "key_conflict_points": ["<çelişki noktası 1>", "<çelişki noktası 2>"]
}}

Sadece JSON döndür, başka bir şey yazma."""

        try:
            response = self.analyzer._generate_with_retry(prompt)
            
            # Parse JSON from response
            import json
            import re
            
            # Extract JSON block
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
            
        except Exception as e:
            logger.error(f"LLM analysis failed: {e}")
        
        return {
            "contradiction_score": 0,
            "contradiction_type": "NONE",
            "explanation": "Analiz yapılamadı",
            "key_conflict_points": [],
        }
    
    def detect(
        self,
        new_statement: str,
        speaker: str = "",
        filter_by_speaker: bool = True,
        index_statement: bool = True,
    ) -> ContradictionResult:
        """
        Detect contradictions for a new statement.
        
        Process:
        1. Extract entities from new statement
        2. Query knowledge graph for evidence pairs
        3. Fall back to vector search if no graph matches
        4. Send to LLM for analysis
        5. Return structured result
        
        Args:
            new_statement: The new statement to analyze
            speaker: Speaker name
            filter_by_speaker: Filter evidence by speaker
            index_statement: Add statement to knowledge graph
            
        Returns:
            ContradictionResult with evidence and score
        """
        if not new_statement or not new_statement.strip():
            return ContradictionResult(
                new_statement=new_statement,
                explanation="Boş açıklama",
            )
        
        # Resolve speaker
        resolved_speaker = self._resolve_speaker(speaker) if speaker else ""
        
        logger.info(f"Analyzing: \"{new_statement[:50]}...\" by {resolved_speaker}")
        
        # Step 1: Extract entities
        extraction = self.extractor.extract(new_statement)
        topics = extraction.topics
        
        logger.debug(f"Extracted topics: {topics}")
        
        # Step 2: Try knowledge graph first
        evidence_1 = None
        evidence_2 = None
        
        if resolved_speaker and topics:
            pair = self._get_evidence_from_graph(resolved_speaker, topics)
            
            if pair:
                evidence_1 = Evidence(
                    text=pair.evidence_1.text,
                    date=pair.evidence_1.date,
                    source=pair.evidence_1.source,
                    source_type=pair.evidence_1.source_type,
                    topics=pair.evidence_1.topics,
                )
                logger.info(f"Found evidence pair from graph (delta: {pair.time_delta_days} days)")
        
        # Step 3: Fall back to vector search
        historical_matches = []
        if evidence_1 is None:
            speaker_filter = resolved_speaker if filter_by_speaker and resolved_speaker else None
            historical_matches = self._get_evidence_from_vector(new_statement, speaker_filter)
            
            if historical_matches:
                match = historical_matches[0]
                evidence_1 = Evidence(
                    text=match["text"],
                    date=match.get("date", ""),
                    source=match.get("source", ""),
                    source_type=match.get("source_type", ""),
                )
                logger.info("Using vector search for evidence")
        
        if evidence_1 is None:
            logger.info("No historical evidence found")
            return ContradictionResult(
                new_statement=new_statement,
                speaker=resolved_speaker,
                explanation="Geçmiş kayıtlarda benzer bir açıklama bulunamadı.",
            )
        
        # Evidence 2 is the new statement
        evidence_2 = Evidence(
            text=new_statement,
            date=datetime.now().strftime("%Y-%m-%d"),
            topics=topics,
        )
        
        # Step 4: LLM Analysis
        analysis = self._analyze_with_llm(
            new_statement=new_statement,
            evidence_1=evidence_1.to_dict(),
            evidence_2=evidence_2.to_dict(),
            speaker=resolved_speaker,
        )
        
        # Parse score (ensure 0-10 scale)
        score = min(10, max(0, int(analysis.get("contradiction_score", 0))))
        
        # Parse type
        type_str = analysis.get("contradiction_type", "NONE")
        try:
            contradiction_type = ContradictionType(type_str)
        except ValueError:
            contradiction_type = ContradictionType.NONE
        
        # Step 5: Index new statement
        if index_statement and resolved_speaker:
            self._extract_and_index(
                text=new_statement,
                speaker=resolved_speaker,
                date=datetime.now().strftime("%Y-%m-%d"),
                source="live_analysis",
                source_type="LIVE",
            )
        
        # Build result
        result = ContradictionResult(
            new_statement=new_statement,
            speaker=resolved_speaker,
            evidence_1=evidence_1,
            evidence_2=evidence_2,
            contradiction_score=score,
            contradiction_type=contradiction_type,
            explanation=analysis.get("explanation", ""),
            key_conflict_points=analysis.get("key_conflict_points", []),
            is_contradiction=score >= self.contradiction_threshold,
            historical_matches=historical_matches,  # Legacy
        )
        
        logger.info(
            f"Analysis complete: score={score}/10, "
            f"is_contradiction={result.is_contradiction}"
        )
        
        return result
    
    def detect_batch(
        self,
        statements: list[dict],
    ) -> list[ContradictionResult]:
        """Analyze multiple statements."""
        results = []
        
        for i, stmt in enumerate(statements):
            text = stmt.get("text", "")
            speaker = stmt.get("speaker", "")
            
            logger.info(f"Processing {i+1}/{len(statements)}")
            result = self.detect(text, speaker)
            results.append(result)
        
        return results
    
    def index_historical_data(
        self,
        limit: int = 10000,
    ) -> int:
        """
        Index existing data from vector store into knowledge graph.
        
        Call this once to populate the graph with historical data.
        
        Returns:
            Number of statements indexed
        """
        logger.info("Indexing historical data to knowledge graph...")
        
        # Get all unique speakers
        speakers = self.memory.get_unique_speakers()
        indexed = 0
        
        for speaker in list(speakers)[:100]:  # Limit speakers
            # Get statements for this speaker
            matches = self.memory.search(
                query_text="",
                top_k=100,
                speaker_filter=speaker,
            )
            
            for match in matches:
                if indexed >= limit:
                    break
                
                # Extract and index
                self._extract_and_index(
                    text=match.text,
                    speaker=match.speaker,
                    date=match.date,
                    source=match.source,
                    source_type=match.source_type,
                )
                indexed += 1
        
        logger.info(f"Indexed {indexed} statements to knowledge graph")
        return indexed
    
    # Legacy compatibility
    @property
    def top_k(self) -> int:
        return 5
    
    @top_k.setter
    def top_k(self, value: int):
        pass  # Ignored in new implementation
    
    def clear_speaker_cache(self) -> None:
        """Clear speaker name cache."""
        self._speaker_cache = None
