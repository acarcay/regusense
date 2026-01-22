"""
Searcher Node: External web search for evidence.

Role:
- Use Tavily/Serper for web search
- Scrape promising URLs
- Append findings to evidence_chain
- Increment search_depth
"""

import logging
import os
from typing import Any, List

from agents.state import AgentState, Evidence

logger = logging.getLogger(__name__)

MAX_SEARCH_DEPTH = 3


def search_web(query: str, max_results: int = 5) -> List[dict]:
    """
    Search the web using Tavily API.
    
    Returns list of {title, url, content, score}
    """
    results = []
    
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        logger.warning("Searcher: TAVILY_API_KEY not set, skipping web search")
        return results
    
    try:
        from tavily import TavilyClient
        
        client = TavilyClient(api_key=tavily_key)
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=max_results,
            include_answer=False,
        )
        
        for result in response.get("results", []):
            results.append({
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "content": result.get("content", ""),
                "score": result.get("score", 0.5),
            })
        
        logger.info(f"Searcher: Found {len(results)} web results")
        
    except Exception as e:
        logger.error(f"Searcher: Tavily search failed: {e}")
    
    return results


def build_search_query(state: AgentState) -> str:
    """Build a search query from state."""
    parts = []
    
    speaker = state.get("speaker", "")
    if speaker:
        parts.append(speaker)
    
    topics = state.get("topics", [])
    if topics:
        parts.extend(topics[:3])  # Max 3 topics
    
    # Add some context
    statement = state.get("target_statement", "")
    if statement:
        # Take first 50 chars as context
        parts.append(statement[:50])
    
    query = " ".join(parts)
    return query if query else "Turkish politics news"


def searcher_node(state: AgentState) -> dict[str, Any]:
    """
    Searcher Node: Find external evidence via web search.
    
    Input:
        state.target_statement: Statement to find evidence for
        state.speaker: Speaker to include in query
        state.topics: Topics to search
        state.search_depth: Current depth (incremented)
        
    Output:
        evidence_chain: List[Evidence] (appended)
        search_depth: int (incremented)
        max_depth_reached: bool
    """
    current_depth = state.get("search_depth", 0)
    
    # Check max depth
    if current_depth >= MAX_SEARCH_DEPTH:
        logger.warning(f"Searcher: Max depth ({MAX_SEARCH_DEPTH}) reached")
        return {
            "search_depth": current_depth,
            "max_depth_reached": True,
        }
    
    # Build search query
    query = build_search_query(state)
    logger.info(f"Searcher: Searching for '{query}' (depth={current_depth + 1})")
    
    # Perform web search
    web_results = search_web(query, max_results=5)
    
    # Convert to Evidence
    new_evidence: List[Evidence] = []
    for result in web_results:
        new_evidence.append(Evidence(
            content=result["content"],
            source=result["title"],
            source_type="WEB_SEARCH",
            url=result["url"],
            relevance_score=result["score"],
        ))
    
    return {
        "evidence_chain": new_evidence,
        "search_depth": current_depth + 1,
        "max_depth_reached": (current_depth + 1) >= MAX_SEARCH_DEPTH,
        "requires_external_search": False,  # We just did the search
    }
