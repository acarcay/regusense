"""
Risk Engine Module.

Pure Python keyword-based risk detection engine for identifying
legislative threats to specific business sectors.

Author: ReguSense Team
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Sector(str, Enum):
    """Business sectors monitored for legislative risks."""

    CRYPTO = "CRYPTO"
    ENERGY = "ENERGY"
    CONSTRUCTION = "CONSTRUCTION"
    FINTECH = "FINTECH"


# Sector keyword definitions (Turkish)
SECTOR_KEYWORDS: dict[Sector, list[str]] = {
    Sector.CRYPTO: [
        "kripto",
        "blokzincir",
        "blockchain",
        "coin",
        "dijital varlık",
        "dijital para",
        "bitcoin",
        "ethereum",
        "token",
        "nft",
        "madencilik",  # mining
        "cüzdan",  # wallet
        "borsa",  # exchange (in crypto context)
    ],
    Sector.ENERGY: [
        "elektrik",
        "doğalgaz",
        "doğal gaz",
        "epdk",
        "santral",
        "enerji",
        "yenilenebilir",
        "güneş enerjisi",
        "rüzgar enerjisi",
        "nükleer",
        "petrol",
        "akaryakıt",
        "dağıtım şirketi",
        "iletim",
    ],
    Sector.CONSTRUCTION: [
        "inşaat",
        "müteahhit",
        "imar",
        "yapı ruhsatı",
        "kentsel dönüşüm",
        "konut",
        "toki",
        "gayrimenkul",
        "arsa",
        "tapu",
        "iskan",
    ],
    Sector.FINTECH: [
        "fintek",
        "fintech",
        "ödeme sistemi",
        "elektronik para",
        "mobil ödeme",
        "açık bankacılık",
        "api",
        "regtech",
        "insurtech",
        "bddk",
        "tcmb",
    ],
}

# Threat type keywords (Turkish)
THREAT_KEYWORDS: list[str] = [
    "vergi",
    "ceza",
    "yasak",
    "kısıtlama",
    "denetim",
    "lisans iptali",
    "yaptırım",
    "düzenleme",
    "regülasyon",
    "sınırlama",
    "para cezası",
    "idari para cezası",
    "kapatma",
    "durdurma",
    "iptal",
    "ruhsat",
    "izin",
    "zorunluluk",
    "yükümlülük",
    "bildirim",
    "tebliğ",
    "kanun teklifi",
    "yasa değişikliği",
    "mevzuat",
]


@dataclass
class RiskHit:
    """
    Represents a detected risk match in the transcript.

    Attributes:
        sector: The business sector affected
        threat_type: The type of legislative threat detected
        page_number: Page number where the risk was found
        snippet: Text excerpt containing the risk keywords
        sector_keyword: The specific sector keyword that matched
        threat_keyword: The specific threat keyword that matched
        confidence: Confidence score (for future AI enhancement)
    """

    sector: Sector
    threat_type: str
    page_number: int
    snippet: str
    expanded_context: str = ""  # Larger context for AI analysis
    sector_keyword: str = ""
    threat_keyword: str = ""
    confidence: float = 1.0
    source_file: str = ""  # Source PDF filename for multi-commission tracking

    def __str__(self) -> str:
        """Human-readable representation of the risk hit."""
        source = f" ({self.source_file})" if self.source_file else ""
        return (
            f"[{self.sector.value}] Page {self.page_number}{source}: "
            f"'{self.threat_type}' - {self.snippet[:100]}..."
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "sector": self.sector.value,
            "threat_type": self.threat_type,
            "page_number": self.page_number,
            "snippet": self.snippet,
            "expanded_context": self.expanded_context,
            "sector_keyword": self.sector_keyword,
            "threat_keyword": self.threat_keyword,
            "confidence": self.confidence,
            "source_file": self.source_file,
        }


@dataclass
class AnalysisResult:
    """
    Complete analysis result from the risk engine.

    Attributes:
        hits: List of detected risk hits
        total_pages_analyzed: Number of pages processed
        sectors_found: Set of sectors with detected risks
        summary: Summary statistics by sector
    """

    hits: list[RiskHit] = field(default_factory=list)
    total_pages_analyzed: int = 0
    sectors_found: set[Sector] = field(default_factory=set)

    @property
    def summary(self) -> dict[str, dict]:
        """Generate summary statistics by sector."""
        summary: dict[str, dict] = {}

        for sector in Sector:
            sector_hits = [h for h in self.hits if h.sector == sector]
            if sector_hits:
                pages = sorted(set(h.page_number for h in sector_hits))
                summary[sector.value] = {
                    "count": len(sector_hits),
                    "pages": pages,
                    "threats": list(set(h.threat_type for h in sector_hits)),
                }

        return summary

    def get_hits_by_sector(self, sector: Sector) -> list[RiskHit]:
        """Get all hits for a specific sector."""
        return [h for h in self.hits if h.sector == sector]

    def print_summary(self) -> None:
        """Print a formatted summary to console."""
        print("\n" + "=" * 60)
        print("RISK ANALYSIS SUMMARY")
        print("=" * 60)

        if not self.hits:
            print("No risk alerts detected.")
            return

        print(f"Total alerts: {len(self.hits)}")
        print(f"Pages analyzed: {self.total_pages_analyzed}")
        print(f"Sectors affected: {', '.join(s.value for s in self.sectors_found)}")
        print()

        for sector_name, stats in self.summary.items():
            print(f"📊 {sector_name}:")
            print(f"   Alerts: {stats['count']}")
            print(f"   Pages: {stats['pages']}")
            print(f"   Threats: {', '.join(stats['threats'])}")
            print()


class RiskEngine:
    """
    Keyword-based risk detection engine.

    Analyzes text for co-occurrence of sector keywords and threat keywords
    to identify potential legislative risks for monitored business sectors.

    Example:
        engine = RiskEngine()
        pages = [{'page': 1, 'text': 'Kripto varlıklara yeni vergi geliyor...'}]
        result = engine.analyze_text(pages)
        result.print_summary()
    """

    # Context window: number of characters around keywords for snippet
    SNIPPET_CONTEXT = 200
    # Expanded context: number of sentences before/after for AI analysis
    SENTENCE_CONTEXT = 3

    def __init__(
        self,
        sectors: Optional[dict[Sector, list[str]]] = None,
        threats: Optional[list[str]] = None,
        case_sensitive: bool = False,
    ) -> None:
        """
        Initialize the risk engine.

        Args:
            sectors: Custom sector keywords (uses defaults if None)
            threats: Custom threat keywords (uses defaults if None)
            case_sensitive: Whether keyword matching is case-sensitive
        """
        self.sectors = sectors or SECTOR_KEYWORDS
        self.threats = threats or THREAT_KEYWORDS
        self.case_sensitive = case_sensitive

        # Compile regex patterns for efficient matching
        self._sector_patterns: dict[Sector, list[re.Pattern]] = {}
        self._threat_patterns: list[tuple[str, re.Pattern]] = []

        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for all keywords."""
        flags = 0 if self.case_sensitive else re.IGNORECASE

        # Compile sector patterns
        for sector, keywords in self.sectors.items():
            self._sector_patterns[sector] = [
                (kw, re.compile(rf"\b{re.escape(kw)}\b", flags))
                for kw in keywords
            ]

        # Compile threat patterns
        self._threat_patterns = [
            (kw, re.compile(rf"\b{re.escape(kw)}\b", flags))
            for kw in self.threats
        ]

    def _find_keyword_matches(
        self, text: str, patterns: list[tuple[str, re.Pattern]]
    ) -> list[tuple[str, re.Match]]:
        """Find all keyword matches in text."""
        matches = []
        for keyword, pattern in patterns:
            for match in pattern.finditer(text):
                matches.append((keyword, match))
        return matches

    def _extract_snippet(
        self, text: str, start_pos: int, end_pos: int
    ) -> str:
        """Extract a snippet around the matched keywords."""
        # Expand to include context
        snippet_start = max(0, start_pos - self.SNIPPET_CONTEXT)
        snippet_end = min(len(text), end_pos + self.SNIPPET_CONTEXT)

        # Try to align to word boundaries
        while snippet_start > 0 and text[snippet_start] not in " \n":
            snippet_start -= 1
        while snippet_end < len(text) and text[snippet_end] not in " \n":
            snippet_end += 1

        snippet = text[snippet_start:snippet_end].strip()

        # Add ellipsis if truncated
        if snippet_start > 0:
            snippet = "..." + snippet
        if snippet_end < len(text):
            snippet = snippet + "..."

        return snippet

    def _extract_expanded_context(
        self, full_text: str, match_start: int, match_end: int
    ) -> str:
        """
        Extract expanded context (3 sentences before/after) for AI analysis.
        
        Args:
            full_text: The complete page text
            match_start: Start position of the keyword match
            match_end: End position of the keyword match
            
        Returns:
            Expanded context with N sentences before and after
        """
        # Split text into sentences using Turkish sentence boundaries
        # Turkish uses period, question mark, exclamation mark
        sentence_pattern = re.compile(r'(?<=[.!?])\s+')
        sentences = sentence_pattern.split(full_text)
        
        # Find which sentence contains our match
        current_pos = 0
        target_sentence_idx = 0
        
        for idx, sentence in enumerate(sentences):
            sentence_end = current_pos + len(sentence)
            if current_pos <= match_start < sentence_end:
                target_sentence_idx = idx
                break
            current_pos = sentence_end + 1  # +1 for the split character
        
        # Get N sentences before and after
        start_idx = max(0, target_sentence_idx - self.SENTENCE_CONTEXT)
        end_idx = min(len(sentences), target_sentence_idx + self.SENTENCE_CONTEXT + 1)
        
        # Join the context sentences
        context_sentences = sentences[start_idx:end_idx]
        expanded = ' '.join(s.strip() for s in context_sentences if s.strip())
        
        # Add markers for truncation
        if start_idx > 0:
            expanded = "[...] " + expanded
        if end_idx < len(sentences):
            expanded = expanded + " [...]"
        
        return expanded

    def _analyze_page(
        self, page_num: int, text: str
    ) -> list[RiskHit]:
        """Analyze a single page for risk hits."""
        hits: list[RiskHit] = []

        # Split text into paragraphs/sentences for more precise matching
        # We consider a "context window" - if sector and threat keywords
        # appear within the same paragraph, it's a hit
        paragraphs = re.split(r"\n\s*\n", text)
        
        # Track cumulative position for expanded context extraction
        para_start_positions: list[tuple[int, str]] = []
        current_pos = 0
        for para in paragraphs:
            para_start_positions.append((current_pos, para))
            current_pos += len(para) + 2  # +2 for \n\n separator

        for para_pos, para in para_start_positions:
            if len(para.strip()) < 20:
                continue

            # Check each sector
            for sector, patterns in self._sector_patterns.items():
                sector_matches = self._find_keyword_matches(para, patterns)

                if not sector_matches:
                    continue

                # Check for threat keywords in the same paragraph
                threat_matches = self._find_keyword_matches(
                    para, self._threat_patterns
                )

                if not threat_matches:
                    continue

                # We have both sector and threat - create a hit
                # Use the first match of each for the snippet
                sector_kw, sector_match = sector_matches[0]
                threat_kw, threat_match = threat_matches[0]

                # Extract snippet covering both matches
                start = min(sector_match.start(), threat_match.start())
                end = max(sector_match.end(), threat_match.end())
                snippet = self._extract_snippet(para, start, end)
                
                # Extract expanded context for AI analysis
                # Calculate absolute position in full text
                abs_start = para_pos + start
                abs_end = para_pos + end
                expanded_context = self._extract_expanded_context(
                    text, abs_start, abs_end
                )

                hit = RiskHit(
                    sector=sector,
                    threat_type=threat_kw,
                    page_number=page_num,
                    snippet=snippet,
                    expanded_context=expanded_context,
                    sector_keyword=sector_kw,
                    threat_keyword=threat_kw,
                )
                hits.append(hit)

                logger.debug(
                    f"Hit on page {page_num}: {sector.value} + {threat_kw}"
                )

        return hits

    def analyze_text(
        self, pages: list[dict] | list
    ) -> AnalysisResult:
        """
        Analyze extracted PDF pages for legislative risks.

        Args:
            pages: List of page dictionaries with 'page' and 'text' keys,
                   or list of PageContent objects

        Returns:
            AnalysisResult containing all detected risk hits
        """
        result = AnalysisResult()
        seen_hits: set[tuple] = set()  # Deduplicate similar hits

        for page_data in pages:
            # Handle both dict and PageContent objects
            if isinstance(page_data, dict):
                page_num = page_data.get("page", 0)
                text = page_data.get("text", "")
            else:
                page_num = getattr(page_data, "page", 0)
                text = getattr(page_data, "text", "")

            if not text:
                continue

            result.total_pages_analyzed += 1
            page_hits = self._analyze_page(page_num, text)

            for hit in page_hits:
                # Deduplicate based on sector, threat, and page
                hit_key = (hit.sector, hit.threat_type, hit.page_number)
                if hit_key not in seen_hits:
                    seen_hits.add(hit_key)
                    result.hits.append(hit)
                    result.sectors_found.add(hit.sector)

        logger.info(
            f"Analysis complete: {len(result.hits)} hits found "
            f"across {result.total_pages_analyzed} pages"
        )

        return result


# Module-level convenience function
def analyze_transcript(pages: list[dict]) -> AnalysisResult:
    """
    Convenience function to analyze transcript pages.

    Args:
        pages: List of page dictionaries with 'page' and 'text' keys

    Returns:
        AnalysisResult with detected risks
    """
    engine = RiskEngine()
    return engine.analyze_text(pages)
