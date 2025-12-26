"""
ReguSense Intelligence Module.

Risk keyword matching and Gemini AI analysis for legislative risk detection.
"""

from intelligence.risk_engine import (
    RiskEngine,
    RiskHit,
    AnalysisResult,
    Sector,
    SECTOR_KEYWORDS,
    THREAT_KEYWORDS,
    analyze_transcript,
)

from intelligence.gemini_analyzer import (
    GeminiAnalyst,
    VerifiedRisk,
    IntelligenceReport,
    RiskLevel,
    verify_risks,
)

__all__ = [
    # Risk Engine
    "RiskEngine",
    "RiskHit",
    "AnalysisResult",
    "Sector",
    "SECTOR_KEYWORDS",
    "THREAT_KEYWORDS",
    "analyze_transcript",
    # Gemini Analyzer
    "GeminiAnalyst",
    "VerifiedRisk",
    "IntelligenceReport",
    "RiskLevel",
    "verify_risks",
]
