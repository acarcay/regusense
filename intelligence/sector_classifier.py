"""
Sector Classifier: NLP-based sector detection for statements.

Uses keyword matching + optional LLM for nuanced classification.
Returns ranked list of (sector_code, confidence) tuples.
"""

import os
import re
import logging
from typing import Optional
from dataclasses import dataclass

from database.graph_schema import SECTOR_DEFINITIONS, SectorCode

logger = logging.getLogger(__name__)


@dataclass
class SectorMatch:
    """A sector match with confidence score."""
    code: SectorCode
    name: str
    confidence: float
    matched_keywords: list[str]


class SectorClassifier:
    """
    Classify text into sectors using keyword matching.
    
    For high-stakes decisions, can optionally use LLM.
    """
    
    def __init__(self, use_llm: bool = False):
        self.use_llm = use_llm
        self.sectors = {s.code: s for s in SECTOR_DEFINITIONS}
        
        # Build keyword index
        self._keyword_index: dict[str, SectorCode] = {}
        for sector in SECTOR_DEFINITIONS:
            for kw in sector.keywords:
                self._keyword_index[kw.lower()] = sector.code
    
    def classify(
        self,
        text: str,
        min_confidence: float = 0.3,
        max_results: int = 3,
    ) -> list[SectorMatch]:
        """
        Classify text into sectors.
        
        Args:
            text: Input text to classify
            min_confidence: Minimum confidence threshold
            max_results: Maximum number of sectors to return
            
        Returns:
            List of SectorMatch ordered by confidence (descending)
        """
        if not text or not text.strip():
            return []
        
        text_lower = text.lower()
        
        # Count keyword matches per sector
        sector_scores: dict[SectorCode, tuple[int, list[str]]] = {}
        
        for keyword, sector_code in self._keyword_index.items():
            # Use word boundary matching
            pattern = r'\b' + re.escape(keyword) + r'\b'
            matches = re.findall(pattern, text_lower)
            
            if matches:
                if sector_code not in sector_scores:
                    sector_scores[sector_code] = (0, [])
                
                count, keywords = sector_scores[sector_code]
                sector_scores[sector_code] = (count + len(matches), keywords + [keyword])
        
        if not sector_scores:
            return []
        
        # Calculate confidence scores
        total_matches = sum(count for count, _ in sector_scores.values())
        
        results: list[SectorMatch] = []
        for code, (count, keywords) in sector_scores.items():
            confidence = count / max(total_matches, 1)
            
            # Boost confidence if multiple unique keywords match
            unique_boost = min(len(set(keywords)) * 0.1, 0.3)
            confidence = min(confidence + unique_boost, 1.0)
            
            if confidence >= min_confidence:
                sector = self.sectors[code]
                results.append(SectorMatch(
                    code=code,
                    name=sector.name,
                    confidence=confidence,
                    matched_keywords=list(set(keywords)),
                ))
        
        # Sort by confidence
        results.sort(key=lambda x: x.confidence, reverse=True)
        
        return results[:max_results]
    
    def classify_with_llm(
        self,
        text: str,
        statement_speaker: str = "",
    ) -> list[SectorMatch]:
        """
        Use LLM for more accurate sector classification.
        
        Falls back to keyword matching if LLM unavailable.
        """
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        
        if not api_key or not self.use_llm:
            return self.classify(text)
        
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            import json
            
            llm = ChatGoogleGenerativeAI(
                model="gemini-2.0-flash",
                google_api_key=api_key,
                temperature=0.1,
            )
            
            sector_list = ", ".join([f"{s.code} ({s.name})" for s in SECTOR_DEFINITIONS])
            
            prompt = f"""Aşağıdaki siyasi açıklamayı analiz et ve hangi sektörleri etkilediğini belirle.

Açıklama: "{text}"
Konuşmacı: {statement_speaker or "Bilinmiyor"}

Sektörler: {sector_list}

JSON formatında yanıt ver:
[{{"sector": "SECTOR_CODE", "confidence": 0.0-1.0, "keywords": ["keyword1", "keyword2"]}}]

Sadece ilgili sektörleri listele. En fazla 3 sektör."""

            response = llm.invoke(prompt)
            content = response.content
            
            # Parse JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            
            data = json.loads(content.strip())
            
            results = []
            for item in data:
                code = item.get("sector", "OTHER")
                if code in self.sectors:
                    results.append(SectorMatch(
                        code=code,
                        name=self.sectors[code].name,
                        confidence=float(item.get("confidence", 0.5)),
                        matched_keywords=item.get("keywords", []),
                    ))
            
            return results
            
        except Exception as e:
            logger.error(f"LLM sector classification failed: {e}")
            return self.classify(text)


# =============================================================================
# Convenience Functions
# =============================================================================

_classifier: Optional[SectorClassifier] = None


def get_classifier(use_llm: bool = False) -> SectorClassifier:
    """Get singleton classifier."""
    global _classifier
    if _classifier is None or _classifier.use_llm != use_llm:
        _classifier = SectorClassifier(use_llm=use_llm)
    return _classifier


def classify_sector(
    text: str,
    use_llm: bool = False,
    speaker: str = "",
) -> list[SectorMatch]:
    """Quick function to classify a text into sectors."""
    classifier = get_classifier(use_llm)
    
    if use_llm:
        return classifier.classify_with_llm(text, speaker)
    return classifier.classify(text)
