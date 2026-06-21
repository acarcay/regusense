"""
Gemini AI Analyst Module.

Uses Google Gemini API to verify and classify risk hits detected by the
keyword-based RiskEngine, distinguishing real legislative threats from noise.

Now includes commission member data to identify speakers and their roles,
enhancing analysis with context about who is speaking (BAŞKAN, BAŞKANVEKİLİ, ÜYE).

Author: ReguSense Team
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    import google.generativeai as genai
except ImportError:
    genai = None  # type: ignore

from config.settings import settings
from intelligence.risk_engine import RiskHit, Sector

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk severity classification from AI analysis."""
    
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOISE = "NOISE"


@dataclass
class VerifiedRisk:
    """
    AI-verified risk assessment from Gemini analysis.
    
    Enhanced with Executive-Level Strategic Insights including:
    - Business impact analysis (operational/financial consequences)
    - Compliance difficulty assessment
    - Tone analysis (speaker's stance toward sector)
    - Likelihood of becoming law
    - Speaker identification and authority level
    
    Attributes:
        original_hit: The original RiskHit from keyword matching
        is_risk: Whether this is a genuine legislative risk
        risk_level: Severity classification (HIGH/MEDIUM/LOW/NOISE)
        summary: Executive summary of the specific threat (max 2 sentences)
        business_impact: Specific operational/financial consequences
        compliance_difficulty: How hard to comply (Hard/Medium/Easy)
        actionable_insight: Step-by-step recommendation for Legal/Product teams
        tone_analysis: Speaker's stance (Hostile/Neutral/Supportive)
        likelihood: Probability of becoming law (High/Low)
        speaker_identified: Detected speaker name and role
        raw_response: Raw JSON response from Gemini (for debugging)
    """
    
    original_hit: RiskHit
    is_risk: bool = False
    risk_level: RiskLevel = RiskLevel.NOISE
    summary: str = ""
    business_impact: str = ""
    compliance_difficulty: str = ""
    actionable_insight: str = ""
    tone_analysis: str = ""
    likelihood: str = ""
    speaker_identified: str = ""
    raw_response: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "sector": self.original_hit.sector.value,
            "page_number": self.original_hit.page_number,
            "is_risk": self.is_risk,
            "risk_level": self.risk_level.value,
            "summary": self.summary,
            "business_impact": self.business_impact,
            "compliance_difficulty": self.compliance_difficulty,
            "actionable_insight": self.actionable_insight,
            "tone_analysis": self.tone_analysis,
            "likelihood": self.likelihood,
            "speaker_identified": self.speaker_identified,
            "threat_keywords": {
                "sector": self.original_hit.sector_keyword,
                "threat": self.original_hit.threat_keyword,
            },
            "snippet": self.original_hit.snippet[:200] + "..." if len(self.original_hit.snippet) > 200 else self.original_hit.snippet,
        }


@dataclass
class IntelligenceReport:
    """
    Complete AI-verified intelligence report.
    
    Attributes:
        verified_risks: List of verified risk assessments
        total_hits_analyzed: Number of raw hits sent to AI
        genuine_risks: Number of hits classified as actual risks
        noise_filtered: Number of hits classified as noise
    """
    
    verified_risks: list[VerifiedRisk] = field(default_factory=list)
    total_hits_analyzed: int = 0
    
    @property
    def genuine_risks(self) -> list[VerifiedRisk]:
        """Get only genuine risks (not NOISE)."""
        return [r for r in self.verified_risks if r.is_risk and r.risk_level != RiskLevel.NOISE]
    
    @property
    def noise_filtered(self) -> int:
        """Count of hits filtered as noise."""
        return len([r for r in self.verified_risks if r.risk_level == RiskLevel.NOISE])
    
    @property
    def high_priority(self) -> list[VerifiedRisk]:
        """Get HIGH priority risks."""
        return [r for r in self.verified_risks if r.risk_level == RiskLevel.HIGH]
    
    @property
    def medium_priority(self) -> list[VerifiedRisk]:
        """Get MEDIUM priority risks."""
        return [r for r in self.verified_risks if r.risk_level == RiskLevel.MEDIUM]
    
    def to_json(self) -> str:
        """Export report as formatted JSON."""
        report = {
            "summary": {
                "total_analyzed": self.total_hits_analyzed,
                "genuine_risks": len(self.genuine_risks),
                "noise_filtered": self.noise_filtered,
                "high_priority": len(self.high_priority),
                "medium_priority": len(self.medium_priority),
            },
            "verified_risks": [r.to_dict() for r in self.genuine_risks],
        }
        return json.dumps(report, indent=2, ensure_ascii=False)
    
    def print_report(self) -> None:
        """Print formatted executive-level report to console."""
        print("\n" + "=" * 70)
        print("  EXECUTIVE INTELLIGENCE REPORT (AI-Analyzed)")
        print("=" * 70)
        
        print(f"\n📊 Özet:")
        print(f"   Analiz edilen: {self.total_hits_analyzed}")
        print(f"   Gerçek risk: {len(self.genuine_risks)}")
        print(f"   Filtrelenen: {self.noise_filtered}")
        print(f"   HIGH öncelik: {len(self.high_priority)}")
        print(f"   MEDIUM öncelik: {len(self.medium_priority)}")
        
        if self.high_priority:
            print("\n🚨 YÜKSEK ÖNCELİKLİ RİSKLER:")
            print("-" * 50)
            for i, risk in enumerate(self.high_priority, 1):
                self._print_executive_risk(i, risk)
        
        if self.medium_priority:
            print("\n⚠️  ORTA ÖNCELİKLİ RİSKLER:")
            print("-" * 50)
            for i, risk in enumerate(self.medium_priority, 1):
                self._print_executive_risk(i, risk)
        
        print("\n" + "=" * 70)
    
    def _print_executive_risk(self, index: int, risk: VerifiedRisk) -> None:
        """Print a single risk with all executive-level details."""
        print(f"\n{index}. [{risk.original_hit.sector.value}] Sayfa {risk.original_hit.page_number}")
        
        if risk.speaker_identified:
            print(f"   👤 Konuşmacı: {risk.speaker_identified}")
        
        print(f"   📋 Özet: {risk.summary}")
        
        if risk.business_impact:
            print(f"   💰 İş Etkisi: {risk.business_impact}")
        
        if risk.compliance_difficulty:
            print(f"   ⚙️  Uyum Zorluğu: {risk.compliance_difficulty}")
        
        if risk.tone_analysis:
            print(f"   🎭 Ton: {risk.tone_analysis}")
        
        if risk.likelihood:
            print(f"   📈 Kanun Olasılığı: {risk.likelihood}")
        
        print(f"   ✅ Eylem: {risk.actionable_insight}")


class GeminiAnalyst:
    """
    AI-powered risk verification using Google Gemini.
    
    Analyzes text snippets from RiskHits to determine if they represent
    genuine legislative threats or just general discussion/noise.
    
    Example:
        analyst = GeminiAnalyst(api_key="your-api-key")
        report = await analyst.analyze_hits(risk_hits)
        report.print_report()
    """
    
    # Sector-specific role descriptions for prompt engineering (Turkish)
    SECTOR_ROLES = {
        Sector.CRYPTO: "kripto para, blockchain ve dijital varlık",
        Sector.ENERGY: "enerji sektörü, EPDK ve şebeke hizmetleri",
        Sector.CONSTRUCTION: "inşaat, gayrimenkul ve kentsel dönüşüm",
        Sector.FINTECH: "finansal teknoloji, ödeme sistemleri ve bankacılık",
    }
    
    # Executive-Level Strategic Insight Prompt (Turkish)
    ANALYSIS_PROMPT = """Sen Fortune 500 şirketlerine danışmanlık yapan Kıdemli Regülasyon Strateji Danışmanısın.

{sector_description} sektöründe faaliyet gösteren bir müşteriyi korumak için yasama tutanaklarını analiz ediyorsun.

**GÖREV:** Sadece özetleme değil, İŞ ETKİSİNİ TAHMİN ET.

METİN:
\"\"\"
{text}
\"\"\"

BAĞLAM:
- Sektör: {sector_name}
- Anahtar kelimeler: "{sector_keyword}", "{threat_keyword}"
- Sayfa: {page_number}
{speaker_context}

AŞAĞIDAKİ ALANLARI İÇEREN BİR JSON DÖNDÜR:

{{
  "is_risk": true veya false,
  "risk_level": "HIGH" | "MEDIUM" | "LOW" | "NOISE",
  
  "summary": "Yönetici özeti - maksimum 2 cümle. Ne tartışılıyor ve neden önemli?",
  
  "business_impact": "KRİTİK: Spesifik operasyonel veya finansal sonuçları açıkla. Örnek: 'Yeni uyum ekipleri gerektirerek OPEX'i %15 artırır', 'Engelleme nedeniyle %5 gelir kaybı riski', 'Lisans iptali riski'",
  
  "compliance_difficulty": "Hard" | "Medium" | "Easy" - Bu düzenlemeye uyum sağlamak ne kadar zor?
  
  "actionable_insight": "Hukuk ve Ürün ekipleri için adım adım öneri. Örnek: '1. Hukuk ekibini bilgilendir, 2. Sektör derneğiyle lobi koordinasyonu yap, 3. Alternatif iş modeli hazırla'",
  
  "tone_analysis": "Hostile" | "Neutral" | "Supportive" - Konuşmacı sektöre karşı düşmanca mı, tarafsız mı yoksa destekleyici mi?
  
  "likelihood": "High" | "Low" - Konuşmacının otoritesine göre kanun olma olasılığı. Bakan/Başkan = High, Muhalefet = Low
  
  "speaker_identified": "Tespit edilen konuşmacı ve rolü. Örnek: 'Mehmet MUŞ (BAŞKAN, Samsun)', 'Bilinmiyor'"
}}

DEĞERLENDİRME KRİTERLERİ:

RİSK SEVİYESİ:
- HIGH: Oylama aşamasında, ceza miktarları belirtilmiş, BAŞKAN/VEKİL tarafından destekleniyor
- MEDIUM: Aktif tartışmada, komisyon üyelerinden destek var
- LOW: Erken aşama, sadece soru veya endişe dile getiriliyor
- NOISE: Gerçek risk yok, geçmiş olaylar veya genel sohbet

KONUŞMACI OTORİTESİ:
- BAŞKAN → Çok yüksek etki, kanun olasılığı HIGH
- BAŞKANVEKİLİ → Yüksek etki
- BAKAN → Çok yüksek etki, hükümet politikası
- ÜYE (İktidar partisi) → Orta-yüksek etki  
- ÜYE (Muhalefet) → Düşük etki, kanun olasılığı LOW
- Bilinmeyen → İçerik bazlı değerlendir

SADECE JSON nesnesiyle yanıt ver. Markdown veya ek açıklama ekleme."""

    # Pattern to extract speaker names from Turkish parliamentary transcripts
    # Format: "ADI SOYADI (Şehir)" or "BAŞKAN ADI SOYADI"
    SPEAKER_PATTERN = re.compile(
        r'(?:BAŞKAN\s+)?([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+)*\s+[A-ZÇĞİÖŞÜ]+)\s*(?:\(([^)]+)\))?',
        re.UNICODE
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-2.0-flash",
    ) -> None:
        """
        Initialize the Gemini analyst.
        
        Args:
            api_key: Google Gemini API key (or set REGUSENSE_GEMINI_API_KEY env var)
            model: Gemini model to use (default: gemini-2.0-flash)
        """
        if genai is None:
            raise ImportError(
                "google-generativeai package not installed. "
                "Run: pip install google-generativeai"
            )
        
        self.api_key = api_key or settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key required. Set REGUSENSE_GEMINI_API_KEY in .env, "
                "or pass api_key parameter."
            )
        
        self.model_name = model or settings.gemini_model
        
        # Configure the API
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel(self.model_name)
        
        # Load commission members database
        self.members_db = self._load_members_database()
        
        logger.info(f"GeminiAnalyst initialized with model: {self.model_name}")
        if self.members_db:
            total_members = sum(len(members) for members in self.members_db.values())
            logger.info(f"Loaded {total_members} commission members from {len(self.members_db)} commissions")
    
    def _load_members_database(self) -> dict:
        """Load commission members from JSON file."""
        # Try multiple possible locations
        possible_paths = [
            Path(__file__).parent.parent / "data" / "commission_members.json",
            Path("data/commission_members.json"),
        ]
        
        for path in possible_paths:
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    logger.info(f"Loaded commission members from: {path}")
                    return data
                except Exception as e:
                    logger.warning(f"Failed to load members from {path}: {e}")
        
        logger.warning("Commission members database not found - speaker identification disabled")
        return {}
    
    def _extract_speakers_from_text(self, text: str) -> list[dict]:
        """
        Extract speaker names and their constituencies from text.
        
        Returns list of dicts with 'name' and 'constituency' keys.
        """
        speakers = []
        seen = set()
        
        for match in self.SPEAKER_PATTERN.finditer(text):
            name = match.group(1).strip()
            constituency = match.group(2).strip() if match.group(2) else None
            
            # Normalize the name
            normalized = self._normalize_name(name)
            
            if normalized and normalized not in seen:
                seen.add(normalized)
                speakers.append({
                    "name": name,
                    "normalized_name": normalized,
                    "constituency": constituency,
                })
        
        return speakers
    
    def _normalize_name(self, name: str) -> str:
        """Normalize a name for comparison."""
        # Remove extra spaces and normalize Turkish characters
        name = " ".join(name.split())
        return name.upper()
    
    def _lookup_member(self, name: str, constituency: Optional[str] = None) -> Optional[dict]:
        """
        Look up a member in the database by name and optionally constituency.
        
        Returns member dict with role if found, None otherwise.
        """
        if not self.members_db:
            return None
        
        normalized_name = self._normalize_name(name)
        
        for commission_name, members in self.members_db.items():
            for member in members:
                member_normalized = self._normalize_name(member["name"])
                
                # Check if names match (allow partial match for common variations)
                if (member_normalized == normalized_name or 
                    normalized_name in member_normalized or 
                    member_normalized in normalized_name):
                    
                    # If constituency is provided, verify it matches
                    if constituency and member.get("constituency"):
                        if constituency.lower() != member["constituency"].lower():
                            continue
                    
                    return {
                        "name": member["name"],
                        "role": member["role"],
                        "constituency": member.get("constituency"),
                        "commission": commission_name,
                    }
        
        return None
    
    def _get_speaker_context(self, hit: RiskHit) -> str:
        """
        Extract and format speaker context from the hit text.
        
        Returns a formatted string describing who is speaking and their role.
        """
        text = hit.expanded_context if hit.expanded_context else hit.snippet
        speakers = self._extract_speakers_from_text(text)
        
        if not speakers:
            return ""
        
        speaker_info_list = []
        for speaker in speakers[:3]:  # Limit to first 3 speakers
            member = self._lookup_member(speaker["name"], speaker.get("constituency"))
            if member:
                role_weight = self._get_role_weight(member["role"])
                speaker_info_list.append(
                    f"- {member['name']} ({member['role']}, {member.get('constituency', 'N/A')}) "
                    f"[Ağırlık: {role_weight}]"
                )
            else:
                speaker_info_list.append(f"- {speaker['name']} (Rol bilinmiyor)")
        
        if speaker_info_list:
            return "\n".join(speaker_info_list)
        return ""
    
    def _get_role_weight(self, role: str) -> str:
        """Get the weight/importance of a role for risk assessment."""
        role_weights = {
            "BAŞKAN": "ÇOK YÜKSEK - Komisyon başkanının açıklamaları yasa için kritik",
            "BAŞKANVEKİLİ": "YÜKSEK - Başkanvekili yetkili konuşmacı",
            "SÖZCÜ": "ORTA-YÜKSEK - Komisyon sözcüsü resmi görüşleri aktarır",
            "KATİP": "ORTA - Prosedürel rol",
            "ÜYE": "ORTA - Komisyon üyesi tartışmaya katılır",
        }
        return role_weights.get(role, "BİLİNMİYOR")
    
    def _build_prompt(self, hit: RiskHit) -> str:
        """Build the analysis prompt for a specific hit, including speaker context."""
        sector_desc = self.SECTOR_ROLES.get(
            hit.sector, 
            f"{hit.sector.value.lower()} sector regulations"
        )
        
        # Use expanded context if available, otherwise fall back to snippet
        text = hit.expanded_context if hit.expanded_context else hit.snippet
        
        # Extract speaker context from the text
        speaker_context = self._get_speaker_context(hit)
        if speaker_context:
            speaker_section = f"\n\nTESPİT EDİLEN KONUŞMACILAR:\n{speaker_context}"
        else:
            speaker_section = "\n\nKONUŞMACI: Tespit edilemedi"
        
        return self.ANALYSIS_PROMPT.format(
            sector_description=sector_desc,
            sector_name=hit.sector.value,
            text=text,
            sector_keyword=hit.sector_keyword,
            threat_keyword=hit.threat_keyword,
            page_number=hit.page_number,
            speaker_context=speaker_section,
        )
    
    def _parse_response(self, response_text: str, hit: RiskHit) -> VerifiedRisk:
        """Parse Gemini response into VerifiedRisk object."""
        try:
            # Clean up the response (remove markdown code blocks if present)
            cleaned = response_text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            # Parse JSON
            data = json.loads(cleaned)
            
            # Map risk level
            risk_level_str = data.get("risk_level", "NOISE").upper()
            try:
                risk_level = RiskLevel(risk_level_str)
            except ValueError:
                risk_level = RiskLevel.NOISE
            
            return VerifiedRisk(
                original_hit=hit,
                is_risk=data.get("is_risk", False),
                risk_level=risk_level,
                summary=data.get("summary", ""),
                business_impact=data.get("business_impact", ""),
                compliance_difficulty=data.get("compliance_difficulty", ""),
                actionable_insight=data.get("actionable_insight", ""),
                tone_analysis=data.get("tone_analysis", ""),
                likelihood=data.get("likelihood", ""),
                speaker_identified=data.get("speaker_identified", ""),
                raw_response=data,
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Gemini response: {e}")
            logger.debug(f"Raw response: {response_text}")
            return VerifiedRisk(
                original_hit=hit,
                is_risk=False,
                risk_level=RiskLevel.NOISE,
                summary="Failed to analyze",
                actionable_insight="Manual review recommended",
                raw_response={"error": str(e), "raw": response_text},
            )
    
    def analyze_hit(self, hit: RiskHit) -> VerifiedRisk:
        """
        Analyze a single risk hit using Gemini.
        
        Args:
            hit: RiskHit to analyze
            
        Returns:
            VerifiedRisk with AI classification
        """
        prompt = self._build_prompt(hit)
        
        try:
            response = self.model.generate_content(prompt)
            result = self._parse_response(response.text, hit)
            
            logger.debug(
                f"Analyzed hit on page {hit.page_number}: "
                f"{result.risk_level.value} - {result.summary[:50]}..."
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Gemini API error for hit on page {hit.page_number}: {e}")
            return VerifiedRisk(
                original_hit=hit,
                is_risk=False,
                risk_level=RiskLevel.NOISE,
                summary=f"API error: {str(e)[:100]}",
                actionable_insight="Manual review recommended",
                raw_response={"error": str(e)},
            )
    
    def analyze_hits(self, hits: list[RiskHit]) -> IntelligenceReport:
        """
        Analyze multiple risk hits and generate an intelligence report.
        
        Args:
            hits: List of RiskHits to analyze
            
        Returns:
            IntelligenceReport with all verified risks
        """
        report = IntelligenceReport(total_hits_analyzed=len(hits))
        
        logger.info(f"Starting AI analysis of {len(hits)} hits...")
        
        for i, hit in enumerate(hits, 1):
            logger.info(f"Analyzing hit {i}/{len(hits)}: Page {hit.page_number} [{hit.sector.value}]")
            
            verified = self.analyze_hit(hit)
            report.verified_risks.append(verified)
            
            # Log progress
            if verified.is_risk and verified.risk_level != RiskLevel.NOISE:
                logger.info(f"  → {verified.risk_level.value}: {verified.summary[:60]}...")
            else:
                logger.info(f"  → NOISE (filtered)")
        
        logger.info(
            f"Analysis complete: {len(report.genuine_risks)} genuine risks, "
            f"{report.noise_filtered} noise filtered"
        )
        
        return report
    
    # =========================================================================
    # Political Contradiction Analysis (ReguSense-Politics)
    # =========================================================================
    
    POLITICAL_ANALYST_PROMPT = """Sen siyasi söylem analizi konusunda uzman bir siyaset analistisin.

**GÖREV:** Aşağıdaki YENİ AÇIKLAMAYI, FARKLI PLATFORMLARDAN elde edilen GEÇMİŞ AÇIKLAMALARLA karşılaştır.
Semantik çelişki, U-dönüşü veya tutarsızlık olup olmadığını tespit et.

**ÖNEMLİ - PLATFORM FARKLILIĞI ANALİZİ:**
Bu bir ÇOKLU KAYNAK analizidir. Geçmiş açıklamalar şu kaynaklardan gelebilir:
- 🏛️ TBMM_COMMISSION: Resmi komisyon tutanakları (teknik, uzman dile yakın)
- 🎤 TBMM_GENERAL_ASSEMBLY: Genel kurul konuşmaları (popülist, halkla iletişim odaklı)
- 📱 SOCIAL_MEDIA: Twitter/X paylaşımları (kısa, vurucu, halkı hedefleyen)
- 📺 TV_INTERVIEW: TV röportajları (detaylı, savunmacı veya açıklayıcı)

**YÜKSEK DEĞERLİ ÇELIŞKI:** Resmi komisyon toplantısındaki teknik/uzman pozisyonu ile 
Genel Kurul'daki popülist söylemi veya sosyal medyadaki halk söylemi arasındaki çelişkiler 
EN DEĞERLİ bulgulardır. Bu "PERSONA DEĞİŞİMİ" paternlerini özellikle işaretle.

**YENİ AÇIKLAMA (Statement A):**
"{new_statement}"

**KONUŞMACI:** {speaker}

**GEÇMİŞ AÇIKLAMALAR (Statement B - Historical):**
{historical_statements}

**DEĞERLENDİRME KRİTERLERİ:**
1. Zamansal bağlamı dikkate al (zaman geçtikçe görüşler değişebilir)
2. Politika pozisyonlarında doğrudan tersine dönüşleri ara
3. Halka verilen kırılan sözleri işaretle  
4. Gelişen görüşler vs. açık çelişkileri ayırt et
5. **PLATFORM/PERSONA FAR KI:** Resmi tutanak vs. sosyal medya tonu arasındaki çelişkiler

**ÖNEMLİ KURALLAR:**
- SADECE yukarıda sunulan metin parçalarını kullan.
- Çelişki bulamazsan UYDURMA - "NONE" olarak işaretle.
- Yanıtında her zaman geçmiş açıklamalardaki TARİHLERE ve KAYNAK TİPLERİNE (source_type) atıf yap.
- Belirsiz veya bağlam dışı karşılaştırmalardan kaçın.
- Platform farkı varsa "persona_shift" alanını true yap.

**ÇELİŞKİ TÜRLERİ:**
- REVERSAL: Önceki pozisyonun tam tersi
- BROKEN_PROMISE: Yerine getirilmemiş vaat
- INCONSISTENCY: Tutarsız ifadeler
- PERSONA_SHIFT: Farklı platformlarda farklı söylem (KOMİSYON vs GENEL KURUL gibi)
- NONE: Çelişki yok

**JSON FORMATINDA YANIT VER:**
{{
    "contradiction_score": 0-100 arası puan,
    "contradiction_type": "REVERSAL" | "BROKEN_PROMISE" | "INCONSISTENCY" | "PERSONA_SHIFT" | "NONE",
    "persona_shift": true veya false (platform farkı varsa true),
    "explanation": "Türkçe kısa açıklama (max 2 cümle)",
    "key_conflict_points": ["çelişki noktası 1", "çelişki noktası 2"],
    "source_comparison": "Hangi kaynaklar arasında çelişki var (örn: COMMISSION vs GENERAL_ASSEMBLY)"
}}

SADECE JSON döndür. Markdown veya ek açıklama ekleme."""

    def analyze_contradiction(
        self,
        new_statement: str,
        historical_statements: list[dict],
        speaker: str = "",
    ) -> dict:
        """
        Analyze a new statement for contradictions with historical statements.
        
        Used by ContradictionDetector for political analysis.
        
        Args:
            new_statement: The new statement to analyze
            historical_statements: List of historical statement dicts with keys:
                - text: Statement text
                - date: Date of statement
                - similarity: Semantic similarity score
            speaker: Name of the speaker
            
        Returns:
            Dictionary with analysis results:
                - contradiction_score: 0-100
                - contradiction_type: REVERSAL/BROKEN_PROMISE/INCONSISTENCY/NONE
                - explanation: Turkish explanation
                - key_conflict_points: List of conflict points
        """
        # Format historical statements for the prompt
        historical_text = ""
        for i, stmt in enumerate(historical_statements, 1):
            date = stmt.get("date", "Tarih bilinmiyor")
            similarity = stmt.get("similarity", 0)
            text = stmt.get("text", "")
            historical_text += f"\n{i}. [{date}] (Benzerlik: {similarity:.2%})\n   \"{text}\"\n"
        
        if not historical_text:
            return {
                "contradiction_score": 0,
                "contradiction_type": "NONE",
                "explanation": "Karşılaştırılacak geçmiş açıklama bulunamadı.",
                "key_conflict_points": [],
            }
        
        prompt = self.POLITICAL_ANALYST_PROMPT.format(
            new_statement=new_statement,
            speaker=speaker or "Bilinmiyor",
            historical_statements=historical_text,
        )
        
        try:
            response = self.model.generate_content(prompt)
            
            # Parse the JSON response
            cleaned = response.text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            return {
                "contradiction_score": int(data.get("contradiction_score", 0)),
                "contradiction_type": data.get("contradiction_type", "NONE"),
                "explanation": data.get("explanation", ""),
                "key_conflict_points": data.get("key_conflict_points", []),
            }
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse contradiction response: {e}")
            return {
                "contradiction_score": 0,
                "contradiction_type": "NONE",
                "explanation": f"Analiz hatası: JSON parse error",
                "key_conflict_points": [],
            }
        except Exception as e:
            logger.error(f"Contradiction analysis failed: {e}")
            return {
                "contradiction_score": 0,
                "contradiction_type": "NONE",
                "explanation": f"Analiz hatası: {str(e)[:100]}",
                "key_conflict_points": [],
            }


# Convenience function for quick analysis
def verify_risks(hits: list[RiskHit], api_key: Optional[str] = None) -> IntelligenceReport:
    """
    Convenience function to verify risk hits using Gemini AI.
    
    Args:
        hits: List of RiskHits from RiskEngine
        api_key: Optional Gemini API key
        
    Returns:
        IntelligenceReport with verified risks
    """
    analyst = GeminiAnalyst(api_key=api_key)
    return analyst.analyze_hits(hits)
