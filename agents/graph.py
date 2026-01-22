"""
LangGraph Graph Definition: The complete agent workflow.

Wires up all nodes with conditional routing:
- Watchdog → (newsworthy?) → Archivist or END
- Archivist → (evidence?) → Analyst or Searcher
- Searcher → Analyst
- Analyst → (needs more?) → Searcher (loop) or Editor
- Editor → Human Approval
- Human Approval → (approved?) → END or Analyst (re-analyze)
"""

import logging
from typing import Literal

from langgraph.graph import StateGraph, END

from agents.state import AgentState, create_initial_state
from agents.nodes.watchdog import watchdog_node
from agents.nodes.archivist import archivist_node
from agents.nodes.searcher import searcher_node
from agents.nodes.analyst import analyst_node
from agents.nodes.editor import editor_node
from agents.nodes.human_approval import human_approval_node

logger = logging.getLogger(__name__)

# === Conditional Edge Functions ===

def route_after_watchdog(state: AgentState) -> Literal["archivist", "end"]:
    """Route based on newsworthiness."""
    if state.get("is_newsworthy", False):
        return "archivist"
    return "end"


def route_after_archivist(state: AgentState) -> Literal["analyst", "searcher"]:
    """Route based on evidence availability."""
    if state.get("requires_external_search", False):
        return "searcher"
    return "analyst"


def route_after_analyst(state: AgentState) -> Literal["searcher", "editor"]:
    """Route based on evidence sufficiency."""
    # If needs more evidence and hasn't hit max depth, loop back
    if state.get("needs_more_evidence", False) and not state.get("max_depth_reached", False):
        return "searcher"
    return "editor"


def route_after_approval(state: AgentState) -> Literal["end", "analyst"]:
    """Route based on human decision."""
    decision = state.get("human_decision", None)
    
    if decision == "rejected":
        # Re-analyze with feedback
        return "analyst"
    
    # Approved or pending (for now, end)
    return "end"


# === Graph Builder ===

def create_graph() -> StateGraph:
    """
    Create the LangGraph StateGraph for contradiction detection.
    
    Returns:
        Compiled StateGraph ready for execution
    """
    # Initialize graph with state schema
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("watchdog", watchdog_node)
    graph.add_node("archivist", archivist_node)
    graph.add_node("searcher", searcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("editor", editor_node)
    graph.add_node("human_approval", human_approval_node)
    
    # Set entry point
    graph.set_entry_point("watchdog")
    
    # Add edges with conditional routing
    graph.add_conditional_edges(
        "watchdog",
        route_after_watchdog,
        {
            "archivist": "archivist",
            "end": END,
        }
    )
    
    graph.add_conditional_edges(
        "archivist",
        route_after_archivist,
        {
            "analyst": "analyst",
            "searcher": "searcher",
        }
    )
    
    # Searcher always goes to Analyst
    graph.add_edge("searcher", "analyst")
    
    graph.add_conditional_edges(
        "analyst",
        route_after_analyst,
        {
            "searcher": "searcher",
            "editor": "editor",
        }
    )
    
    # Editor goes to human approval
    graph.add_edge("editor", "human_approval")
    
    graph.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {
            "end": END,
            "analyst": "analyst",
        }
    )
    
    # Compile the graph
    compiled = graph.compile()
    
    logger.info("LangGraph compiled successfully")
    return compiled


# === Runner Functions ===

def run_analysis(
    statement: str,
    speaker: str = "",
    date: str = "",
    human_decision: str = None,
) -> AgentState:
    """
    Run the full analysis pipeline.
    
    Args:
        statement: The statement to analyze
        speaker: Speaker name
        date: Statement date
        human_decision: Optional pre-set decision for resuming
        
    Returns:
        Final AgentState with all results
    """
    # Create initial state
    initial_state = create_initial_state(
        statement=statement,
        speaker=speaker,
        date=date,
    )
    
    # Pre-set human decision if provided (for resuming)
    if human_decision:
        initial_state["human_decision"] = human_decision
    
    # Get compiled graph
    graph = create_graph()
    
    # Run the graph
    logger.info(f"Starting analysis for: '{statement[:50]}...'")
    
    final_state = graph.invoke(initial_state)
    
    logger.info(
        f"Analysis complete: score={final_state.get('contradiction_score', 0)}/10"
    )
    
    return final_state


# === CLI Entry Point ===

def main():
    """CLI entry point for testing."""
    import argparse
    import json
    
    logging.basicConfig(level=logging.INFO)
    
    parser = argparse.ArgumentParser(description="ReguSense Agent Analysis")
    parser.add_argument("--statement", required=True, help="Statement to analyze")
    parser.add_argument("--speaker", default="", help="Speaker name")
    parser.add_argument("--date", default="", help="Statement date")
    parser.add_argument("--output", default="json", choices=["json", "report"])
    
    args = parser.parse_args()
    
    result = run_analysis(
        statement=args.statement,
        speaker=args.speaker,
        date=args.date,
    )
    
    if args.output == "json":
        # Convert to JSON-serializable dict
        output = {
            k: (v.to_dict() if hasattr(v, "to_dict") else v)
            for k, v in result.items()
            if v is not None
        }
        # Handle Evidence list
        if "evidence_chain" in output:
            output["evidence_chain"] = [
                e.to_dict() if hasattr(e, "to_dict") else e
                for e in output["evidence_chain"]
            ]
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print(result.get("final_report", "No report generated"))


if __name__ == "__main__":
    main()
