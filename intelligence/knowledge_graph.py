"""
Knowledge Graph for Political Statements.

JSON-based graph structure for storing relationships between:
- Statements
- Persons (speakers)
- Topics
- Dates

Enables queries like: "What did Person X say about Topic Y at Time T?"

Author: ReguSense Team
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Iterator
from collections import defaultdict

from core.logging import get_logger
from config.settings import settings

logger = get_logger(__name__)


# =============================================================================
# Graph Node Types
# =============================================================================

@dataclass
class StatementNode:
    """A statement in the knowledge graph."""
    id: str
    text: str
    speaker: str
    date: str = ""
    source: str = ""
    source_type: str = ""
    topics: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "StatementNode":
        return cls(**data)


@dataclass
class EvidencePair:
    """A pair of statements for contradiction analysis."""
    evidence_1: StatementNode
    evidence_2: StatementNode
    speaker: str
    topic: str
    time_delta_days: int = 0
    
    def to_dict(self) -> dict:
        return {
            "evidence_1": self.evidence_1.to_dict(),
            "evidence_2": self.evidence_2.to_dict(),
            "speaker": self.speaker,
            "topic": self.topic,
            "time_delta_days": self.time_delta_days,
        }


# =============================================================================
# Knowledge Graph
# =============================================================================

class KnowledgeGraph:
    """
    JSON-based knowledge graph for political statements.
    
    Structure:
    - statements: {id: StatementNode}
    - speaker_index: {speaker: [statement_ids]}
    - topic_index: {topic: [statement_ids]}
    - date_index: {YYYY-MM: [statement_ids]}
    
    Example:
        graph = KnowledgeGraph()
        graph.add_statement(
            text="Enflasyon tek haneye düşecek",
            speaker="Mehmet Şimşek",
            topics=["ENFLASYON"],
            date="2023-06-15"
        )
        
        results = graph.query(
            speaker="Mehmet Şimşek",
            topic="ENFLASYON"
        )
    """
    
    def __init__(
        self,
        persist_path: Optional[Path] = None,
        auto_save: bool = True,
    ):
        """
        Initialize knowledge graph.
        
        Args:
            persist_path: Path to save/load graph JSON
            auto_save: Whether to auto-save after modifications
        """
        self.persist_path = persist_path or (settings.data_dir / "knowledge_graph.json")
        self.auto_save = auto_save
        
        # Core storage
        self._statements: dict[str, StatementNode] = {}
        
        # Indexes for fast lookup
        self._speaker_index: dict[str, set[str]] = defaultdict(set)
        self._topic_index: dict[str, set[str]] = defaultdict(set)
        self._date_index: dict[str, set[str]] = defaultdict(set)
        
        # Load existing data
        self._load()
        
        logger.info(f"KnowledgeGraph initialized with {len(self._statements)} statements")
    
    def _generate_id(self, text: str, speaker: str, date: str) -> str:
        """Generate unique ID for a statement."""
        content = f"{text}|{speaker}|{date}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def _extract_date_key(self, date: str) -> str:
        """Extract YYYY-MM from date string."""
        if not date:
            return ""
        
        # Handle various formats
        try:
            if "-" in date:
                parts = date.split("-")
                if len(parts) >= 2:
                    return f"{parts[0]}-{parts[1]}"
            elif len(date) == 4 and date.isdigit():
                return date
        except Exception:
            pass
        
        return date[:7] if len(date) >= 7 else date
    
    def add_statement(
        self,
        text: str,
        speaker: str,
        topics: list[str] = None,
        date: str = "",
        source: str = "",
        source_type: str = "",
        entities: dict[str, list[str]] = None,
    ) -> str:
        """
        Add a statement to the graph.
        
        Args:
            text: Statement text
            speaker: Speaker name
            topics: List of topics
            date: Date in YYYY-MM-DD format
            source: Source file/URL
            source_type: Type of source
            entities: Additional extracted entities
            
        Returns:
            Statement ID
        """
        stmt_id = self._generate_id(text, speaker, date)
        
        # Skip if already exists
        if stmt_id in self._statements:
            return stmt_id
        
        node = StatementNode(
            id=stmt_id,
            text=text[:5000],  # Limit text length
            speaker=speaker,
            date=date,
            source=source,
            source_type=source_type,
            topics=topics or [],
            entities=entities or {},
        )
        
        # Store statement
        self._statements[stmt_id] = node
        
        # Update indexes
        self._speaker_index[speaker.lower()].add(stmt_id)
        
        for topic in (topics or []):
            self._topic_index[topic.upper()].add(stmt_id)
        
        date_key = self._extract_date_key(date)
        if date_key:
            self._date_index[date_key].add(stmt_id)
        
        # Auto-save
        if self.auto_save:
            self._save()
        
        return stmt_id
    
    def query(
        self,
        speaker: Optional[str] = None,
        topic: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 50,
    ) -> list[StatementNode]:
        """
        Query statements from the graph.
        
        Args:
            speaker: Filter by speaker
            topic: Filter by topic
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            limit: Maximum results
            
        Returns:
            List of matching StatementNodes
        """
        # Start with all IDs or filter by speaker/topic
        candidate_ids: Optional[set[str]] = None
        
        if speaker:
            speaker_key = speaker.lower()
            if speaker_key in self._speaker_index:
                candidate_ids = self._speaker_index[speaker_key].copy()
            else:
                # Fuzzy match speaker
                for key in self._speaker_index:
                    if speaker_key in key or key in speaker_key:
                        if candidate_ids is None:
                            candidate_ids = set()
                        candidate_ids.update(self._speaker_index[key])
        
        if topic:
            topic_key = topic.upper()
            topic_ids = self._topic_index.get(topic_key, set())
            
            if candidate_ids is None:
                candidate_ids = topic_ids.copy()
            else:
                candidate_ids &= topic_ids
        
        # If no filters, get all
        if candidate_ids is None:
            candidate_ids = set(self._statements.keys())
        
        # Get statements
        results = []
        for stmt_id in candidate_ids:
            if stmt_id in self._statements:
                stmt = self._statements[stmt_id]
                
                # Date filter
                if date_from and stmt.date < date_from:
                    continue
                if date_to and stmt.date > date_to:
                    continue
                
                results.append(stmt)
        
        # Sort by date descending
        results.sort(key=lambda x: x.date or "", reverse=True)
        
        return results[:limit]
    
    def get_evidence_pairs(
        self,
        speaker: str,
        topic: str,
        min_time_delta_days: int = 30,
    ) -> list[EvidencePair]:
        """
        Get pairs of statements for contradiction analysis.
        
        Finds statements by the same speaker on the same topic
        at different times.
        
        Args:
            speaker: Speaker name
            topic: Topic to analyze
            min_time_delta_days: Minimum days between statements
            
        Returns:
            List of EvidencePairs
        """
        statements = self.query(speaker=speaker, topic=topic)
        
        if len(statements) < 2:
            return []
        
        pairs = []
        
        # Generate pairs with different dates
        for i, stmt1 in enumerate(statements):
            for stmt2 in statements[i + 1:]:
                # Calculate time delta
                delta = self._calculate_date_delta(stmt1.date, stmt2.date)
                
                if delta >= min_time_delta_days:
                    # Older statement is evidence_1
                    if stmt1.date < stmt2.date:
                        e1, e2 = stmt1, stmt2
                    else:
                        e1, e2 = stmt2, stmt1
                    
                    pairs.append(EvidencePair(
                        evidence_1=e1,
                        evidence_2=e2,
                        speaker=speaker,
                        topic=topic,
                        time_delta_days=delta,
                    ))
        
        # Sort by time delta (larger gaps are more interesting)
        pairs.sort(key=lambda x: x.time_delta_days, reverse=True)
        
        return pairs[:10]  # Limit to top 10 pairs
    
    def _calculate_date_delta(self, date1: str, date2: str) -> int:
        """Calculate days between two dates."""
        if not date1 or not date2:
            return 0
        
        try:
            d1 = datetime.strptime(date1[:10], "%Y-%m-%d")
            d2 = datetime.strptime(date2[:10], "%Y-%m-%d")
            return abs((d2 - d1).days)
        except ValueError:
            # Try year-only comparison
            try:
                y1 = int(date1[:4])
                y2 = int(date2[:4])
                return abs(y2 - y1) * 365
            except ValueError:
                return 0
    
    def get_speaker_topics(self, speaker: str) -> dict[str, int]:
        """Get topics a speaker has talked about with counts."""
        statements = self.query(speaker=speaker, limit=1000)
        
        topic_counts: dict[str, int] = defaultdict(int)
        for stmt in statements:
            for topic in stmt.topics:
                topic_counts[topic] += 1
        
        return dict(sorted(topic_counts.items(), key=lambda x: -x[1]))
    
    def get_timeline(
        self,
        speaker: str,
        topic: str,
    ) -> list[dict]:
        """
        Get chronological timeline of statements.
        
        Returns:
            List of {date, text, source} dicts
        """
        statements = self.query(speaker=speaker, topic=topic)
        
        # Sort by date ascending
        statements.sort(key=lambda x: x.date or "")
        
        return [
            {
                "date": s.date,
                "text": s.text[:500],
                "source": s.source,
                "source_type": s.source_type,
            }
            for s in statements
        ]
    
    def _save(self) -> None:
        """Save graph to JSON file."""
        data = {
            "statements": {
                k: v.to_dict() for k, v in self._statements.items()
            },
            "metadata": {
                "count": len(self._statements),
                "updated_at": datetime.now().isoformat(),
            },
        }
        
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.debug(f"Saved {len(self._statements)} statements to {self.persist_path}")
    
    def _load(self) -> None:
        """Load graph from JSON file."""
        if not self.persist_path.exists():
            return
        
        try:
            with open(self.persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Load statements
            for stmt_id, stmt_data in data.get("statements", {}).items():
                node = StatementNode.from_dict(stmt_data)
                self._statements[stmt_id] = node
                
                # Rebuild indexes
                self._speaker_index[node.speaker.lower()].add(stmt_id)
                for topic in node.topics:
                    self._topic_index[topic.upper()].add(stmt_id)
                date_key = self._extract_date_key(node.date)
                if date_key:
                    self._date_index[date_key].add(stmt_id)
            
            logger.info(f"Loaded {len(self._statements)} statements from {self.persist_path}")
            
        except Exception as e:
            logger.warning(f"Failed to load knowledge graph: {e}")
    
    def stats(self) -> dict:
        """Get graph statistics."""
        return {
            "total_statements": len(self._statements),
            "unique_speakers": len(self._speaker_index),
            "unique_topics": len(self._topic_index),
            "date_range": self._get_date_range(),
        }
    
    def _get_date_range(self) -> dict:
        """Get min/max dates in graph."""
        dates = [s.date for s in self._statements.values() if s.date]
        if not dates:
            return {"min": None, "max": None}
        return {"min": min(dates), "max": max(dates)}
    
    def clear(self) -> None:
        """Clear all data."""
        self._statements.clear()
        self._speaker_index.clear()
        self._topic_index.clear()
        self._date_index.clear()
        
        if self.auto_save:
            self._save()


# =============================================================================
# Singleton accessor
# =============================================================================

_graph_instance: Optional[KnowledgeGraph] = None


def get_knowledge_graph() -> KnowledgeGraph:
    """Get or create singleton KnowledgeGraph."""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = KnowledgeGraph()
    return _graph_instance
