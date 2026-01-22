"""
ReguSense LangGraph Agents Package.

Multi-agent system for political contradiction detection:
- Watchdog: Filters incoming data
- Archivist: Queries internal DBs
- Searcher: External web search
- Analyst: LLM reasoning
- Editor: Output formatting
- Human Approval: HITL checkpoint
"""

from agents.state import AgentState, Evidence
from agents.graph import create_graph, run_analysis

__all__ = [
    "AgentState",
    "Evidence",
    "create_graph",
    "run_analysis",
]
