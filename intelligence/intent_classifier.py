"""
Political Intent Classifier.

Uses Gemini AI to classify the INTENT behind company mentions in political statements:
- CRITICIZE: Attack/criticism (opposition going after companies)
- ADVOCATE: Defense/support (potential conflict-of-interest)
- NEUTRAL: Procedural mention (no strong sentiment)

Key Innovation: "Power Filter" - Only government-bloc ADVOCATE is flagged as suspicious.

Author: ReguSense Team
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

# Load .env file if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed

try:
    import google.generativeai as genai
except ImportError:
    genai = None  # type: ignore

logger = logging.getLogger(__name__)


class PoliticalIntent(str, Enum):
    """Intent classification for company mentions."""
    CRITICIZE = "CRITICIZE"   # Attack/criticism
    ADVOCATE = "ADVOCATE"     # Defense/support
    NEUTRAL = "NEUTRAL"       # Procedural/neutral mention


@dataclass
class IntentResult:
    """
    Result of intent classification.
    
    Attributes:
        intent: CRITICIZE, ADVOCATE, or NEUTRAL
        confidence: 0.0 to 1.0 confidence score
        key_triggers: Keywords that led to classification
        is_conflict_candidate: True if ADVOCATE from government speaker
        explanation: Brief explanation of classification
    """
    intent: PoliticalIntent
    confidence: float
    key_triggers: list[str]
    is_conflict_candidate: bool
    explanation: str = ""
    raw_response: Optional[dict] = None


# Government bloc parties (for conflict detection)
GOVERNMENT_PARTIES = {"AKP", "MHP", "AK PARTİ", "AK PARTI"}
OPPOSITION_PARTIES = {"CHP", "İYİ", "İYİ PARTİ", "HDP", "DEM", "DEVA", "GP", "SAADET", "TİP"}


class IntentClassifier:
    """
    Gemini-powered classifier for political intent behind company mentions.
    
    Example:
        classifier = IntentClassifier()
        result = await classifier.classify(
            statement="Cengiz Holding ülkeyi talan ediyor!",
            company_name="Cengiz Holding",
            speaker_party="CHP",
        )
        print(result.intent)  # CRITICIZE
    """
    
    # Turkish political trigger keywords
    CRITICIZE_TRIGGERS = {
        "beşli çete", "talan", "sömürü", "peşkeş", "rant", "yandaş",
        "yolsuzluk", "rüşvet", "ihale", "kayırmacılık", "vurgun",
        "çevre tahribatı", "kamu zararı", "hesap sorulsun", "hesap verecek",
        "müteahhit", "rantçı", "beton", "ekolojik katliam", "soygun",
        "5'li çete", "beş'li çete", "hırsız", "yağma", "komisyon",
    }
    
    ADVOCATE_TRIGGERS = {
        "istihdam", "ekonomiye katkı", "yatırım", "kalkınma", "büyüme",
        "yerli ve milli", "ihracat", "başarı", "gurur", "öncü",
        "haksızlık yapılıyor", "karalama kampanyası", "iftira",
        "iş sağlıyor", "ekmek kapısı", "aş kapısı", "milli sermaye",
        "dünya markası", "yurt dışında", "başarılı", "örnek",
    }
    
    SYSTEM_PROMPT = """Sen Türk siyasi söylemini analiz eden kıdemli bir uzmansın.

**GÖREV:** Verilen beyanattaki şirket isminin HANGİ NİYETLE kullanıldığını tespit et.

**TERMİNOLOJİ:**
- "Beşli Çete", "Talan", "Rant", "Sömürü", "Peşkeş" = CRITICIZE sinyalleri
- "İstihdam", "Ekonomiye katkı", "Yerli ve milli", "Başarı" = ADVOCATE sinyalleri
- Prosedürel bahis, liste okuma = NEUTRAL

**BEYANAT:**
"{statement}"

**ŞİRKET:** {company}
**KONUŞMACI PARTİSİ:** {party}

**JSON FORMATINDA YANIT VER:**
{{
    "intent": "CRITICIZE" | "ADVOCATE" | "NEUTRAL",
    "confidence_score": 0.0 - 1.0,
    "key_triggers": ["tetikleyici kelimeler"],
    "explanation": "Kısa Türkçe açıklama (1 cümle)"
}}

**SINIFLANDIRMA KRİTERLERİ:**

CRITICIZE (Saldırı/Eleştiri):
- Şirket yolsuzluk, çevre tahribatı, haksız ihale bağlamında yeriliyor
- "Beşli çete" veya "rant" vurgusu var
- Şirket kamu zararıyla ilişkilendiriliyor

ADVOCATE (Savunma/Destek):
- Şirket istihdam, ekonomik kalkınma bağlamında övülüyor
- Şirkete yapılan eleştirilere karşı savunma yapılıyor
- "Haksızlık yapılıyor", "karalama" gibi ifadeler var

NEUTRAL (Nötr):
- Şirket ismi sadece prosedür gereği geçiyor
- Duygusal yükleme yok
- Liste okuma veya referans verme

SADECE JSON döndür. Markdown veya ek açıklama ekleme."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash",
    ) -> None:
        """
        Initialize intent classifier.
        
        Args:
            api_key: Gemini API key (or use GEMINI_API_KEY env var)
            model: Gemini model name
        """
        if genai is None:
            raise ImportError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )
        
        self.api_key = api_key or os.environ.get("REGUSENSE_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Gemini API key required. Set GEMINI_API_KEY environment variable.")
        
        self.model_name = model
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)
        
        logger.info(f"IntentClassifier initialized with model: {self.model_name}")
    
    def classify(
        self,
        statement: str,
        company_name: str,
        speaker_party: Optional[str] = None,
        speaker_is_opposition: Optional[bool] = None,
    ) -> IntentResult:
        """
        Classify the intent behind a company mention.
        
        Args:
            statement: The statement text
            company_name: Name of the company mentioned
            speaker_party: Political party of the speaker
            speaker_is_opposition: Whether speaker is opposition (override party check)
            
        Returns:
            IntentResult with classification
        """
        # First, try fast heuristic check
        heuristic_result = self._fast_heuristic(statement, company_name)
        if heuristic_result and heuristic_result.confidence >= 0.85:
            # High confidence heuristic, skip API call
            return self._apply_conflict_check(heuristic_result, speaker_party, speaker_is_opposition)
        
        # Fall back to Gemini API
        prompt = self.SYSTEM_PROMPT.format(
            statement=statement[:3000],  # Limit length
            company=company_name,
            party=speaker_party or "Bilinmiyor",
        )
        
        try:
            response = self.model.generate_content(prompt)
            result = self._parse_response(response.text, statement)
            return self._apply_conflict_check(result, speaker_party, speaker_is_opposition)
            
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            # Return NEUTRAL on error
            return IntentResult(
                intent=PoliticalIntent.NEUTRAL,
                confidence=0.0,
                key_triggers=[],
                is_conflict_candidate=False,
                explanation=f"Sınıflandırma hatası: {str(e)[:50]}",
            )
    
    def _fast_heuristic(
        self,
        statement: str,
        company_name: str,
    ) -> Optional[IntentResult]:
        """
        Fast keyword-based heuristic before calling API.
        
        Returns IntentResult if high confidence, None otherwise.
        """
        statement_lower = statement.lower()
        
        # Count trigger matches
        criticize_matches = []
        for trigger in self.CRITICIZE_TRIGGERS:
            if trigger in statement_lower:
                criticize_matches.append(trigger)
        
        advocate_matches = []
        for trigger in self.ADVOCATE_TRIGGERS:
            if trigger in statement_lower:
                advocate_matches.append(trigger)
        
        # Strong CRITICIZE signal
        if len(criticize_matches) >= 2 and len(advocate_matches) == 0:
            return IntentResult(
                intent=PoliticalIntent.CRITICIZE,
                confidence=0.90,
                key_triggers=criticize_matches[:5],
                is_conflict_candidate=False,
                explanation="Güçlü eleştirel anahtar kelimeler tespit edildi.",
            )
        
        # Strong ADVOCATE signal
        if len(advocate_matches) >= 2 and len(criticize_matches) == 0:
            return IntentResult(
                intent=PoliticalIntent.ADVOCATE,
                confidence=0.85,
                key_triggers=advocate_matches[:5],
                is_conflict_candidate=False,  # Will be set by _apply_conflict_check
                explanation="Savunma/destek anahtar kelimeleri tespit edildi.",
            )
        
        # Ambiguous case - need API
        return None
    
    def _parse_response(self, response_text: str, statement: str) -> IntentResult:
        """Parse Gemini JSON response."""
        try:
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            intent_str = data.get("intent", "NEUTRAL").upper()
            try:
                intent = PoliticalIntent(intent_str)
            except ValueError:
                intent = PoliticalIntent.NEUTRAL
            
            return IntentResult(
                intent=intent,
                confidence=float(data.get("confidence_score", 0.5)),
                key_triggers=data.get("key_triggers", []),
                is_conflict_candidate=False,  # Will be set by _apply_conflict_check
                explanation=data.get("explanation", ""),
                raw_response=data,
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse intent response: {e}")
            return IntentResult(
                intent=PoliticalIntent.NEUTRAL,
                confidence=0.3,
                key_triggers=[],
                is_conflict_candidate=False,
                explanation="JSON ayrıştırma hatası",
            )
    
    def _apply_conflict_check(
        self,
        result: IntentResult,
        speaker_party: Optional[str],
        speaker_is_opposition: Optional[bool],
    ) -> IntentResult:
        """
        Apply the "Power Filter" - mark government ADVOCATE as conflict candidate.
        
        Args:
            result: Initial classification result
            speaker_party: Party name
            speaker_is_opposition: Override for opposition check
        """
        if result.intent != PoliticalIntent.ADVOCATE:
            # Only ADVOCATE can be a conflict candidate
            result.is_conflict_candidate = False
            return result
        
        # Determine if speaker is government bloc
        is_opposition = speaker_is_opposition
        
        if is_opposition is None and speaker_party:
            party_upper = speaker_party.upper().strip()
            if party_upper in GOVERNMENT_PARTIES or "AKP" in party_upper or "MHP" in party_upper:
                is_opposition = False
            elif party_upper in OPPOSITION_PARTIES:
                is_opposition = True
            else:
                is_opposition = None  # Unknown party
        
        # Government ADVOCATE = Conflict Candidate
        if is_opposition is False:
            result.is_conflict_candidate = True
            result.explanation = f"{result.explanation} [İKTİDAR SAVUNMASI - ÇIKAR ÇATIŞMASI ADAYI]"
        else:
            result.is_conflict_candidate = False
        
        return result
    
    def classify_batch(
        self,
        items: list[dict],
    ) -> list[IntentResult]:
        """
        Classify multiple statement-company pairs.
        
        Args:
            items: List of dicts with keys:
                - statement: Statement text
                - company_name: Company name
                - speaker_party: Optional party name
                
        Returns:
            List of IntentResult objects
        """
        results = []
        for item in items:
            result = self.classify(
                statement=item["statement"],
                company_name=item["company_name"],
                speaker_party=item.get("speaker_party"),
                speaker_is_opposition=item.get("speaker_is_opposition"),
            )
            results.append(result)
        return results


# =============================================================================
# Utility Functions
# =============================================================================

def is_government_party(party: str) -> bool:
    """Check if party is in government bloc."""
    if not party:
        return False
    party_upper = party.upper().strip()
    return party_upper in GOVERNMENT_PARTIES or "AKP" in party_upper or "MHP" in party_upper


def is_opposition_party(party: str) -> bool:
    """Check if party is opposition."""
    if not party:
        return False
    party_upper = party.upper().strip()
    return party_upper in OPPOSITION_PARTIES
