"""
Editor Node: Format analysis results for output.

Role:
- Generate tweet text (max 280 chars)
- Generate video script
- Generate executive summary
- Select appropriate tone/assets based on score
"""

import logging
from typing import Any
from datetime import datetime

from agents.state import AgentState

logger = logging.getLogger(__name__)


def generate_tweet(state: AgentState) -> str:
    """Generate a tweet from analysis results."""
    speaker = state.get("speaker", "Siyasetçi")
    score = state.get("contradiction_score", 0)
    ctype = state.get("contradiction_type", "NONE")
    explanation = state.get("explanation", "")
    
    if score < 5:
        return ""  # Not newsworthy enough for a tweet
    
    # Build tweet based on contradiction type
    type_emojis = {
        "REVERSAL": "🔄",
        "BROKEN_PROMISE": "💔",
        "INCONSISTENCY": "⚠️",
        "PERSONA_SHIFT": "🎭",
        "NONE": "📊",
    }
    
    emoji = type_emojis.get(ctype, "📊")
    
    # Truncate explanation for tweet
    short_exp = explanation[:200] if explanation else "Detaylı analiz için tıklayın."
    
    tweet = f"{emoji} {speaker} çelişki puanı: {score}/10\n\n{short_exp}"
    
    # Ensure max length
    if len(tweet) > 280:
        tweet = tweet[:277] + "..."
    
    return tweet


def generate_video_script(state: AgentState) -> str:
    """Generate a video script for high-impact contradictions."""
    speaker = state.get("speaker", "Siyasetçi")
    score = state.get("contradiction_score", 0)
    ctype = state.get("contradiction_type", "NONE")
    explanation = state.get("explanation", "")
    key_points = state.get("key_conflict_points", [])
    evidence = state.get("evidence_chain", [])
    
    if score < 7:
        return ""  # Only generate video for high scores
    
    script_parts = [
        f"# {speaker} Çelişki Analizi",
        f"**Puan:** {score}/10 | **Tür:** {ctype}",
        "",
        "## Giriş",
        f"Bugün {speaker}'in tartışmalı açıklamasını inceliyoruz.",
        "",
        "## Yeni Açıklama",
        f'"{state.get("target_statement", "")[:300]}..."',
        "",
        "## Geçmiş Kayıtlar",
    ]
    
    for i, ev in enumerate(evidence[:3], 1):
        script_parts.append(f"{i}. ({ev.date or '?'}): \"{ev.content[:150]}...\"")
    
    script_parts.extend([
        "",
        "## Analiz",
        explanation,
        "",
        "## Sonuç",
    ])
    
    if key_points:
        for point in key_points:
            script_parts.append(f"- {point}")
    
    return "\n".join(script_parts)


def generate_report(state: AgentState) -> str:
    """Generate executive summary report."""
    speaker = state.get("speaker", "Bilinmiyor")
    score = state.get("contradiction_score", 0)
    ctype = state.get("contradiction_type", "NONE")
    explanation = state.get("explanation", "")
    key_points = state.get("key_conflict_points", [])
    statement = state.get("target_statement", "")
    date = state.get("statement_date", "")
    
    report = f"""# Çelişki Analiz Raporu

**Tarih:** {datetime.now().strftime("%Y-%m-%d %H:%M")}
**Konuşmacı:** {speaker}
**Açıklama Tarihi:** {date}

---

## Özet
**Çelişki Puanı:** {score}/10
**Çelişki Türü:** {ctype}

## Yeni Açıklama
> {statement[:500]}{"..." if len(statement) > 500 else ""}

## Analiz
{explanation}

## Temel Çatışma Noktaları
"""
    
    if key_points:
        for point in key_points:
            report += f"- {point}\n"
    else:
        report += "- Belirgin çatışma noktası bulunamadı.\n"
    
    return report


def editor_node(state: AgentState) -> dict[str, Any]:
    """
    Editor Node: Format output for various channels.
    
    Input:
        state (full analysis results)
        
    Output:
        final_report: str
        tweet_text: str
        video_script: str
        pending_approval: bool (always True to trigger HITL)
    """
    logger.info("Editor: Generating output formats")
    
    # Generate all formats
    report = generate_report(state)
    tweet = generate_tweet(state)
    video = generate_video_script(state)
    
    score = state.get("contradiction_score", 0)
    
    logger.info(
        f"Editor: Generated report ({len(report)} chars), "
        f"tweet ({len(tweet)} chars), video ({len(video)} chars)"
    )
    
    return {
        "final_report": report,
        "tweet_text": tweet,
        "video_script": video,
        # Only request approval for significant contradictions
        "pending_approval": score >= 5,
        "completed_at": datetime.now().isoformat(),
    }
