"""
Entity Extractor for Political Statements.

Uses GLiNER for zero-shot Named Entity Recognition to extract:
- PERSON: Politicians, officials
- ORG: Organizations, parties, ministries
- DATE: Dates, time references
- TOPIC: Economic topics, policy areas
- LOCATION: Cities, countries

Author: ReguSense Team
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
from functools import lru_cache

from core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Entity Types
# =============================================================================

@dataclass
class ExtractedEntity:
    """A single extracted entity."""
    text: str
    label: str  # PERSON, ORG, DATE, TOPIC, LOCATION
    start: int = 0
    end: int = 0
    confidence: float = 0.0
    normalized: str = ""  # Normalized form
    
    def __post_init__(self):
        if not self.normalized:
            self.normalized = self.text


@dataclass
class ExtractionResult:
    """Result of entity extraction."""
    text: str
    entities: list[ExtractedEntity] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    persons: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    
    def get_by_label(self, label: str) -> list[ExtractedEntity]:
        """Get entities by label."""
        return [e for e in self.entities if e.label == label]


# =============================================================================
# Topic Keywords (Turkish Political Topics)
# =============================================================================

TOPIC_KEYWORDS = {
    # Economy
    "ekonomi": "EKONOMİ",
    "enflasyon": "ENFLASYON",
    "faiz": "FAİZ",
    "dolar": "DÖVİZ",
    "euro": "DÖVİZ",
    "döviz": "DÖVİZ",
    "kur": "DÖVİZ",
    "vergi": "VERGİ",
    "bütçe": "BÜTÇE",
    "borç": "BORÇ",
    "kredi": "FİNANS",
    "maaş": "ÜCRET",
    "asgari ücret": "ASGARİ ÜCRET",
    "zam": "ZAM",
    "işsizlik": "İSTİHDAM",
    "istihdam": "İSTİHDAM",
    
    # Politics
    "seçim": "SEÇİM",
    "referandum": "SEÇİM",
    "anayasa": "ANAYASA",
    "kanun": "YASAMA",
    "yasa": "YASAMA",
    "reform": "REFORM",
    "meclis": "MECLİS",
    "komisyon": "KOMİSYON",
    "hükümet": "HÜKÜMET",
    "muhalefet": "SİYASET",
    
    # Foreign Policy
    "nato": "DIŞ POLİTİKA",
    "avrupa birliği": "AB",
    "ab": "AB",
    "suriye": "DIŞ POLİTİKA",
    "mülteci": "GÖÇ",
    "göç": "GÖÇ",
    
    # Social
    "eğitim": "EĞİTİM",
    "sağlık": "SAĞLIK",
    "emekli": "EMEKLİLİK",
    "emeklilik": "EMEKLİLİK",
    "ek gösterge": "EMEKLİLİK",
}


# =============================================================================
# Turkish Date Patterns
# =============================================================================

TURKISH_MONTHS = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4,
    "mayıs": 5, "haziran": 6, "temmuz": 7, "ağustos": 8,
    "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}

DATE_PATTERNS = [
    # 15 Ocak 2024
    r"(\d{1,2})\s+(ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık)\s+(\d{4})",
    # 2024 yılı, 2024 yılında
    r"(\d{4})\s*yıl[ıi]",
    # gelecek yıl, önümüzdeki yıl
    r"(gelecek|önümüzdeki|geçen|bu)\s+yıl",
    # 2024 sonunda, 2024 başında
    r"(\d{4})\s*(sonunda|başında|ortasında)",
]


# =============================================================================
# Entity Extractor
# =============================================================================

class EntityExtractor:
    """
    Extracts entities from Turkish political texts.
    
    Uses GLiNER for NER and rule-based extraction for topics/dates.
    
    Example:
        extractor = EntityExtractor()
        result = extractor.extract("Mehmet Şimşek enflasyon hakkında açıklama yaptı")
        print(result.persons)  # ["Mehmet Şimşek"]
        print(result.topics)   # ["ENFLASYON"]
    """
    
    LABELS = ["person", "organization", "location", "date"]
    
    def __init__(
        self,
        use_gliner: bool = True,
        gliner_model: str = "urchade/gliner_multi-v2.1",
    ):
        """
        Initialize entity extractor.
        
        Args:
            use_gliner: Whether to use GLiNER (False = rule-based only)
            gliner_model: GLiNER model name
        """
        self.use_gliner = use_gliner
        self.gliner_model = gliner_model
        self._model = None
        
        # Compile patterns
        self._date_patterns = [
            re.compile(p, re.IGNORECASE | re.UNICODE)
            for p in DATE_PATTERNS
        ]
        
        logger.info(f"EntityExtractor initialized (GLiNER: {use_gliner})")
    
    def _load_model(self):
        """Lazy-load GLiNER model."""
        if self._model is None and self.use_gliner:
            try:
                from gliner import GLiNER
                logger.info(f"Loading GLiNER model: {self.gliner_model}")
                self._model = GLiNER.from_pretrained(self.gliner_model)
                logger.info("GLiNER model loaded successfully")
            except ImportError:
                logger.warning("GLiNER not installed, falling back to rule-based extraction")
                self.use_gliner = False
            except Exception as e:
                logger.warning(f"Failed to load GLiNER: {e}, falling back to rule-based")
                self.use_gliner = False
    
    def extract(self, text: str) -> ExtractionResult:
        """
        Extract entities from text.
        
        Args:
            text: Input text
            
        Returns:
            ExtractionResult with extracted entities
        """
        if not text or not text.strip():
            return ExtractionResult(text=text)
        
        entities: list[ExtractedEntity] = []
        
        # 1. GLiNER extraction
        if self.use_gliner:
            entities.extend(self._extract_with_gliner(text))
        
        # 2. Rule-based topic extraction
        entities.extend(self._extract_topics(text))
        
        # 3. Rule-based date extraction
        entities.extend(self._extract_dates(text))
        
        # 4. Deduplicate and organize
        result = ExtractionResult(text=text, entities=entities)
        
        # Collect by type
        result.persons = list(set(
            e.normalized for e in entities if e.label == "PERSON"
        ))
        result.organizations = list(set(
            e.normalized for e in entities if e.label == "ORG"
        ))
        result.dates = list(set(
            e.normalized for e in entities if e.label == "DATE"
        ))
        result.topics = list(set(
            e.normalized for e in entities if e.label == "TOPIC"
        ))
        
        logger.debug(
            f"Extracted: {len(result.persons)} persons, "
            f"{len(result.topics)} topics, {len(result.dates)} dates"
        )
        
        return result
    
    def _extract_with_gliner(self, text: str) -> list[ExtractedEntity]:
        """Extract entities using GLiNER."""
        self._load_model()
        
        if self._model is None:
            return []
        
        entities = []
        
        try:
            predictions = self._model.predict_entities(text, self.LABELS)
            
            for pred in predictions:
                label_map = {
                    "person": "PERSON",
                    "organization": "ORG",
                    "location": "LOCATION",
                    "date": "DATE",
                }
                
                entities.append(ExtractedEntity(
                    text=pred["text"],
                    label=label_map.get(pred["label"], pred["label"].upper()),
                    start=pred.get("start", 0),
                    end=pred.get("end", 0),
                    confidence=pred.get("score", 0.0),
                    normalized=self._normalize_entity(pred["text"], pred["label"]),
                ))
                
        except Exception as e:
            logger.warning(f"GLiNER extraction failed: {e}")
        
        return entities
    
    def _extract_topics(self, text: str) -> list[ExtractedEntity]:
        """Extract topics using keyword matching."""
        entities = []
        text_lower = text.lower()
        
        for keyword, topic in TOPIC_KEYWORDS.items():
            if keyword in text_lower:
                # Find position
                idx = text_lower.find(keyword)
                entities.append(ExtractedEntity(
                    text=keyword,
                    label="TOPIC",
                    start=idx,
                    end=idx + len(keyword),
                    confidence=1.0,
                    normalized=topic,
                ))
        
        return entities
    
    def _extract_dates(self, text: str) -> list[ExtractedEntity]:
        """Extract dates using regex patterns."""
        entities = []
        
        for pattern in self._date_patterns:
            for match in pattern.finditer(text):
                date_text = match.group(0)
                normalized = self._normalize_date(match)
                
                entities.append(ExtractedEntity(
                    text=date_text,
                    label="DATE",
                    start=match.start(),
                    end=match.end(),
                    confidence=0.9,
                    normalized=normalized,
                ))
        
        return entities
    
    def _normalize_entity(self, text: str, label: str) -> str:
        """Normalize entity text."""
        # Basic normalization
        normalized = text.strip()
        
        # Person names: Title case
        if label == "person":
            normalized = " ".join(w.capitalize() for w in normalized.split())
        
        return normalized
    
    def _normalize_date(self, match: re.Match) -> str:
        """Normalize date to YYYY-MM-DD or description."""
        groups = match.groups()
        text = match.group(0).lower()
        
        # Check for relative dates
        if "gelecek yıl" in text:
            year = datetime.now().year + 1
            return f"{year}"
        elif "geçen yıl" in text:
            year = datetime.now().year - 1
            return f"{year}"
        elif "bu yıl" in text:
            return f"{datetime.now().year}"
        
        # Try to parse absolute date
        try:
            # Pattern: DD Month YYYY
            if len(groups) >= 3 and groups[1] in TURKISH_MONTHS:
                day = int(groups[0])
                month = TURKISH_MONTHS[groups[1]]
                year = int(groups[2])
                return f"{year}-{month:02d}-{day:02d}"
            
            # Pattern: YYYY yılı
            if len(groups) >= 1 and groups[0].isdigit():
                return groups[0]
                
        except (ValueError, IndexError):
            pass
        
        return match.group(0)
    
    def extract_speaker_topics(
        self,
        text: str,
        speaker: str,
    ) -> dict[str, Any]:
        """
        Extract entities with speaker context.
        
        Returns structured data for knowledge graph insertion.
        """
        result = self.extract(text)
        
        return {
            "speaker": speaker,
            "topics": result.topics,
            "dates": result.dates,
            "organizations": result.organizations,
            "persons": result.persons,
            "text": text,
        }


# =============================================================================
# Singleton accessor
# =============================================================================

_extractor_instance: Optional[EntityExtractor] = None


def get_entity_extractor() -> EntityExtractor:
    """Get or create singleton EntityExtractor."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = EntityExtractor()
    return _extractor_instance
