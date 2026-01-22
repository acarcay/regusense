"""
Watchdog Node: Gateway filter for incoming statements.

Role:
- Scores "newsworthiness" (0-100)
- Filters out routine/procedural text
- Sets is_newsworthy flag for routing
"""

import logging
from typing import Any

from agents.state import AgentState

logger = logging.getLogger(__name__)

# Keywords that indicate low-value procedural content
PROCEDURAL_KEYWORDS = [
    "teşekkür ederim",
    "hoş geldiniz",
    "toplantıyı açıyorum",
    "toplantıyı kapatıyorum",
    "söz veriyorum",
    "buyurun",
    "evet arkadaşlar",
    "değerli milletvekilleri",
    "sayın başkan",
]

# Keywords that indicate high-value newsworthy content
NEWSWORTHY_KEYWORDS = [
    "enflasyon",
    "faiz",
    "dolar",
    "kur",
    "işsizlik",
    "ekonomi",
    "büyüme",
    "yatırım",
    "vergi",
    "bütçe",
    "açıklama",
    "karar",
    "yaptırım",
    "yasak",
    "reform",
]


def calculate_newsworthy_score(text: str) -> int:
    """
    Calculate newsworthiness score (0-100).
    
    Simple heuristic-based scoring:
    - Start at 50
    - Deduct for procedural keywords
    - Boost for newsworthy keywords
    - Adjust for length
    """
    text_lower = text.lower()
    score = 50
    
    # Check procedural keywords (-10 each, min -40)
    procedural_count = sum(1 for kw in PROCEDURAL_KEYWORDS if kw in text_lower)
    score -= min(procedural_count * 10, 40)
    
    # Check newsworthy keywords (+15 each, max +45)
    newsworthy_count = sum(1 for kw in NEWSWORTHY_KEYWORDS if kw in text_lower)
    score += min(newsworthy_count * 15, 45)
    
    # Length bonus (substantial statements are more newsworthy)
    if len(text) > 200:
        score += 10
    elif len(text) < 50:
        score -= 20
    
    # Clamp to 0-100
    return max(0, min(100, score))


def watchdog_node(state: AgentState) -> dict[str, Any]:
    """
    Watchdog Node: Filter and prioritize incoming statements.
    
    Input:
        state.target_statement: The statement to evaluate
        
    Output:
        is_newsworthy: bool
        newsworthy_score: int (0-100)
    """
    statement = state.get("target_statement", "")
    
    if not statement or not statement.strip():
        logger.warning("Watchdog: Empty statement received")
        return {
            "is_newsworthy": False,
            "newsworthy_score": 0,
            "errors": ["Empty statement"],
        }
    
    # Calculate score
    score = calculate_newsworthy_score(statement)
    is_newsworthy = score >= 60  # Threshold
    
    logger.info(
        f"Watchdog: score={score}, newsworthy={is_newsworthy}, "
        f"statement='{statement[:50]}...'"
    )
    
    return {
        "is_newsworthy": is_newsworthy,
        "newsworthy_score": score,
    }
