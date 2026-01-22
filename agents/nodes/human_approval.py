"""
Human Approval Node: HITL checkpoint for final review.

Role:
- Pause execution for human review
- Accept approval/rejection decision
- Route based on decision
"""

import logging
from typing import Any

from agents.state import AgentState

logger = logging.getLogger(__name__)


def human_approval_node(state: AgentState) -> dict[str, Any]:
    """
    Human Approval Node: Checkpoint for human review.
    
    This node is a "passthrough" that signals the graph should pause
    for human input. In LangGraph, we use interrupts or checkpointing
    to achieve this.
    
    Input:
        state.pending_approval: bool
        state.final_report: str
        
    Output:
        pending_approval: True (to signal pause)
        
    The actual approval logic happens outside the graph:
    1. Graph runs until this node
    2. System presents report to user
    3. User clicks Approve/Reject
    4. System resumes graph with human_decision set
    """
    logger.info("Human Approval: Awaiting decision")
    
    score = state.get("contradiction_score", 0)
    speaker = state.get("speaker", "")
    
    # If score is very low, auto-approve (no need for human)
    if score < 3:
        logger.info("Human Approval: Auto-approved (low score)")
        return {
            "pending_approval": False,
            "human_decision": "approved",
        }
    
    # Check if decision already made (resuming)
    existing_decision = state.get("human_decision")
    if existing_decision:
        logger.info(f"Human Approval: Existing decision = {existing_decision}")
        return {
            "pending_approval": False,
        }
    
    # Otherwise, signal that we're waiting
    logger.info(
        f"Human Approval: Waiting for decision on {speaker}'s statement "
        f"(score: {score}/10)"
    )
    
    return {
        "pending_approval": True,
    }


def handle_approval_decision(
    state: AgentState,
    decision: str,
    feedback: str = "",
) -> dict[str, Any]:
    """
    Handle incoming human decision (called externally).
    
    Args:
        state: Current state
        decision: "approved" or "rejected"
        feedback: Optional rejection feedback
        
    Returns:
        State updates
    """
    if decision == "approved":
        logger.info("Human Decision: APPROVED")
        return {
            "human_decision": "approved",
            "pending_approval": False,
        }
    elif decision == "rejected":
        logger.info(f"Human Decision: REJECTED - {feedback}")
        return {
            "human_decision": "rejected",
            "rejection_feedback": feedback,
            "pending_approval": False,
            # Reset needs_more_evidence to trigger re-analysis
            "needs_more_evidence": True,
        }
    else:
        logger.warning(f"Human Decision: Unknown decision '{decision}'")
        return {}
