"""
AgentState: The shared state passed between all LangGraph nodes.

This TypedDict carries all data needed for the investigation pipeline:
- Input data (statement, speaker, date)
- Evidence chain (accumulated findings)
- Control flow flags
- Output results
"""

from typing import TypedDict, List, Optional, Annotated, Literal
from dataclasses import dataclass, field
import operator


@dataclass
class Evidence:
    """A single piece of evidence from internal or external sources."""
    
    content: str
    source: str = ""
    source_type: str = ""  # TBMM_COMMISSION, SOCIAL_MEDIA, WEB_SEARCH, etc.
    date: str = ""
    relevance_score: float = 0.0
    url: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "source": self.source,
            "source_type": self.source_type,
            "date": self.date,
            "relevance_score": self.relevance_score,
            "url": self.url,
        }


class AgentState(TypedDict, total=False):
    """
    LangGraph AgentState - Single source of truth for all nodes.
    
    Uses Annotated with operator.add for append-only lists.
    """
    
    # === Input Data ===
    target_statement: str
    speaker: str
    statement_date: str
    
    # === Investigation State ===
    # Append-only list of found evidence
    evidence_chain: Annotated[List[Evidence], operator.add]
    # Current hypothesis being tested
    current_hypothesis: str
    # Search iterations count (prevents infinite loops)
    search_depth: int
    # Topics extracted from statement
    topics: List[str]
    
    # === Control Flow Flags ===
    # Is this statement newsworthy? (Set by Watchdog)
    is_newsworthy: bool
    # Newsworthiness score 0-100
    newsworthy_score: int
    # Needs external search? (Set by Archivist if no internal evidence)
    requires_external_search: bool
    # Needs more evidence? (Set by Analyst to loop back)
    needs_more_evidence: bool
    # Max search depth reached?
    max_depth_reached: bool
    
    # === Analysis Results ===
    # Contradiction score 0-10 (Set by Analyst)
    contradiction_score: Optional[float]
    # Type: REVERSAL, BROKEN_PROMISE, INCONSISTENCY, PERSONA_SHIFT, NONE
    contradiction_type: str
    # Explanation from LLM
    explanation: str
    # Key conflict points
    key_conflict_points: List[str]
    
    # === Output ===
    # Final formatted report (Set by Editor)
    final_report: Optional[str]
    # Tweet text
    tweet_text: Optional[str]
    # Video script
    video_script: Optional[str]
    
    # === Human-in-the-Loop ===
    # Pending approval?
    pending_approval: bool
    # Human decision: "approved", "rejected", None
    human_decision: Optional[Literal["approved", "rejected"]]
    # Rejection feedback
    rejection_feedback: Optional[str]
    
    # === Metadata ===
    # Error messages from any node
    errors: List[str]
    # Processing timestamps
    started_at: str
    completed_at: Optional[str]


# === Default State Factory ===

def create_initial_state(
    statement: str,
    speaker: str = "",
    date: str = "",
) -> AgentState:
    """Create a fresh AgentState for a new analysis."""
    from datetime import datetime
    
    return AgentState(
        target_statement=statement,
        speaker=speaker,
        statement_date=date or datetime.now().strftime("%Y-%m-%d"),
        evidence_chain=[],
        current_hypothesis="",
        search_depth=0,
        topics=[],
        is_newsworthy=False,
        newsworthy_score=0,
        requires_external_search=False,
        needs_more_evidence=False,
        max_depth_reached=False,
        contradiction_score=None,
        contradiction_type="NONE",
        explanation="",
        key_conflict_points=[],
        final_report=None,
        tweet_text=None,
        video_script=None,
        pending_approval=False,
        human_decision=None,
        rejection_feedback=None,
        errors=[],
        started_at=datetime.now().isoformat(),
        completed_at=None,
    )
