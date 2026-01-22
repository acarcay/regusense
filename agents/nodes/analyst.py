"""
Analyst Node: LLM-powered contradiction analysis.

Role:
- Evaluate evidence_chain with Gemini Pro
- Apply temporal reasoning (time delta analysis)
- Output contradiction_score (0-10), type, explanation
- Can signal "needs_more_evidence" to loop back
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, List, Optional

from agents.state import AgentState, Evidence

logger = logging.getLogger(__name__)

# Contradiction types
CONTRADICTION_TYPES = [
    "REVERSAL",        # Complete 180° change
    "BROKEN_PROMISE",  # Said X would happen, didn't
    "INCONSISTENCY",   # Conflicting statements
    "PERSONA_SHIFT",   # Changed stance based on audience
    "NONE",            # No contradiction
]

ANALYST_PROMPT = """Sen bir siyasi analiz uzmanısın. Verilen açıklama ve kanıtları analiz ederek çelişki olup olmadığını belirle.

## Yeni Açıklama
Konuşmacı: {speaker}
Tarih: {date}
Açıklama: "{statement}"

## Geçmiş Kanıtlar
{evidence_text}

## Analiz Kuralları
1. Zaman farkını dikkate al: 
   - 1 yıldan az: Doğrudan çelişki olabilir
   - 1-3 yıl: Koşullar değişmiş olabilir
   - 3+ yıl: "Düşünce evrimi" olarak kabul edilebilir
2. Bağlamı değerlendir: Aynı konu hakkında mı?
3. Kelimelere değil, anlama bak

## Yanıt Formatı (JSON)
{{
    "contradiction_score": <0-10 arası puan>,
    "contradiction_type": "<REVERSAL|BROKEN_PROMISE|INCONSISTENCY|PERSONA_SHIFT|NONE>",
    "explanation": "<Türkçe açıklama>",
    "key_conflict_points": ["<çatışma noktası 1>", "<çatışma noktası 2>"],
    "needs_more_evidence": <true|false>,
    "confidence": "<LOW|MEDIUM|HIGH>"
}}

Sadece JSON döndür, başka bir şey yazma."""


def format_evidence(evidence_chain: List[Evidence]) -> str:
    """Format evidence chain for prompt."""
    if not evidence_chain:
        return "Kanıt bulunamadı."
    
    parts = []
    for i, ev in enumerate(evidence_chain[:5], 1):  # Max 5 evidence items
        parts.append(
            f"### Kanıt {i}\n"
            f"- Kaynak: {ev.source}\n"
            f"- Tarih: {ev.date or 'Bilinmiyor'}\n"
            f"- İçerik: \"{ev.content[:500]}...\"\n"
        )
    
    return "\n".join(parts)


def call_gemini(prompt: str) -> dict:
    """Call Gemini API for analysis."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    
    if not api_key:
        logger.error("Analyst: No Gemini API key found")
        return {"error": "No API key"}
    
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.0-flash",
            google_api_key=api_key,
            temperature=0.3,
        )
        
        response = llm.invoke(prompt)
        content = response.content
        
        # Parse JSON from response
        # Handle markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        return json.loads(content.strip())
        
    except json.JSONDecodeError as e:
        logger.error(f"Analyst: Failed to parse JSON response: {e}")
        return {"error": "JSON parse error", "raw": content}
    except Exception as e:
        logger.error(f"Analyst: Gemini call failed: {e}")
        return {"error": str(e)}


def analyst_node(state: AgentState) -> dict[str, Any]:
    """
    Analyst Node: Analyze evidence and determine contradiction.
    
    Input:
        state.target_statement: Statement to analyze
        state.speaker: Speaker name
        state.evidence_chain: Accumulated evidence
        
    Output:
        contradiction_score: float (0-10)
        contradiction_type: str
        explanation: str
        key_conflict_points: List[str]
        needs_more_evidence: bool
    """
    statement = state.get("target_statement", "")
    speaker = state.get("speaker", "")
    date = state.get("statement_date", datetime.now().strftime("%Y-%m-%d"))
    evidence_chain = state.get("evidence_chain", [])
    
    logger.info(f"Analyst: Analyzing with {len(evidence_chain)} evidence items")
    
    # Build prompt
    evidence_text = format_evidence(evidence_chain)
    prompt = ANALYST_PROMPT.format(
        speaker=speaker or "Bilinmiyor",
        date=date,
        statement=statement,
        evidence_text=evidence_text,
    )
    
    # Call LLM
    result = call_gemini(prompt)
    
    if "error" in result:
        logger.error(f"Analyst: LLM error: {result['error']}")
        return {
            "contradiction_score": 0,
            "contradiction_type": "NONE",
            "explanation": f"Analiz hatası: {result['error']}",
            "key_conflict_points": [],
            "needs_more_evidence": False,
            "errors": [result["error"]],
        }
    
    # Extract results
    score = min(10, max(0, float(result.get("contradiction_score", 0))))
    ctype = result.get("contradiction_type", "NONE")
    if ctype not in CONTRADICTION_TYPES:
        ctype = "NONE"
    
    needs_more = result.get("needs_more_evidence", False)
    
    # Don't request more if we already have max depth
    if state.get("max_depth_reached", False):
        needs_more = False
    
    logger.info(
        f"Analyst: score={score}/10, type={ctype}, "
        f"needs_more={needs_more}"
    )
    
    return {
        "contradiction_score": score,
        "contradiction_type": ctype,
        "explanation": result.get("explanation", ""),
        "key_conflict_points": result.get("key_conflict_points", []),
        "needs_more_evidence": needs_more,
    }
