"""
Pydantic Models for Scraped Data.

Provides validation and serialization for all scraped content.
"""

from datetime import datetime
from typing import Optional, Any
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    """Source type enumeration."""
    TBMM_COMMISSION = "TBMM_COMMISSION"
    TBMM_GENERAL_ASSEMBLY = "TBMM_GENERAL_ASSEMBLY"
    SOCIAL_MEDIA = "SOCIAL_MEDIA"
    RESMI_GAZETE = "RESMI_GAZETE"
    TV_INTERVIEW = "TV_INTERVIEW"
    NEWS = "NEWS"
    EKAP = "EKAP"  # KİK Tender Platform
    TUIK_TSG = "TUIK_TSG"  # TÜİK Ticaret Sicil
    TOBB = "TOBB"  # TOBB Ticaret Sicil Gazetesi
    UNKNOWN = "UNKNOWN"


class ScrapedStatement(BaseModel):
    """
    Validated political statement from any source.
    
    This is the canonical format for ingestion into vector store.
    """
    
    text: str = Field(
        ...,
        min_length=10,
        max_length=50000,
        description="The statement text content",
    )
    speaker: str = Field(
        default="",
        max_length=200,
        description="Name of the speaker",
    )
    date: str = Field(
        default="",
        description="Date in YYYY-MM-DD format",
    )
    topic: str = Field(
        default="",
        max_length=200,
        description="Topic or category",
    )
    source: str = Field(
        default="",
        description="Source file or URL",
    )
    source_type: SourceType = Field(
        default=SourceType.UNKNOWN,
        description="Type of source",
    )
    page_number: int = Field(
        default=0,
        ge=0,
        description="Page number in source document",
    )
    
    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        """Validate date format if provided."""
        if not v:
            return v
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            # Try alternative formats
            for fmt in ["%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d"]:
                try:
                    dt = datetime.strptime(v, fmt)
                    return dt.strftime("%Y-%m-%d")
                except ValueError:
                    continue
            # Return as-is if no format matches
        return v
    
    def to_ingest_dict(self) -> dict[str, Any]:
        """Convert to dictionary for vector store ingestion."""
        return {
            "text": self.text,
            "speaker": self.speaker,
            "date": self.date,
            "topic": self.topic,
            "source": self.source,
            "source_type": self.source_type.value,
            "page_number": self.page_number,
        }


class ScrapedTweet(BaseModel):
    """Validated tweet data."""
    
    id: str = Field(
        ...,
        description="Tweet ID",
    )
    text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Tweet text",
    )
    username: str = Field(
        ...,
        description="Twitter username",
    )
    display_name: str = Field(
        default="",
        description="Display name",
    )
    created_at: str = Field(
        default="",
        description="Tweet creation timestamp",
    )
    retweets: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    is_retweet: bool = Field(default=False)
    url: str = Field(default="")
    
    def to_statement(self) -> ScrapedStatement:
        """Convert to ScrapedStatement for ingestion."""
        # Parse date if possible
        date = ""
        if self.created_at:
            try:
                # Try common formats
                for fmt in ["%Y-%m-%d", "%a %b %d %H:%M:%S %z %Y"]:
                    try:
                        dt = datetime.strptime(self.created_at, fmt)
                        date = dt.strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
            except Exception:
                pass
        
        return ScrapedStatement(
            text=self.text,
            speaker=self.display_name or self.username,
            date=date,
            source=self.url or f"https://twitter.com/{self.username}/status/{self.id}",
            source_type=SourceType.SOCIAL_MEDIA,
        )


class ScrapedTranscript(BaseModel):
    """Validated TBMM transcript data."""
    
    title: str = Field(
        ...,
        description="Transcript title",
    )
    date: str = Field(
        default="",
        description="Session date",
    )
    url: str = Field(
        ...,
        description="Source URL",
    )
    pdf_url: str = Field(
        default="",
        description="Direct PDF URL",
    )
    donem: int = Field(
        default=0,
        description="Legislative term (Dönem)",
    )
    yasama_yili: int = Field(
        default=0,
        description="Legislative year",
    )
    birlesim: int = Field(
        default=0,
        description="Session number",
    )
    content: str = Field(
        default="",
        description="Extracted text content",
    )
    source_type: SourceType = Field(
        default=SourceType.TBMM_GENERAL_ASSEMBLY,
    )
    
    def to_statement(self) -> ScrapedStatement:
        """Convert to ScrapedStatement for ingestion."""
        return ScrapedStatement(
            text=self.content or self.title,
            date=self.date,
            source=self.pdf_url or self.url,
            source_type=self.source_type,
            topic=f"Dönem {self.donem} - Birleşim {self.birlesim}" if self.donem else "",
        )


class ScrapeResult(BaseModel):
    """Generic scrape operation result."""
    
    success: bool = Field(
        default=False,
        description="Whether scrape was successful",
    )
    items_found: int = Field(
        default=0,
        ge=0,
        description="Number of items found",
    )
    items_saved: int = Field(
        default=0,
        ge=0,
        description="Number of items saved",
    )
    items_ingested: int = Field(
        default=0,
        ge=0,
        description="Number of items sent to vector store",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if failed",
    )
    duration_seconds: float = Field(
        default=0.0,
        ge=0,
        description="Total scrape duration",
    )
    saved_path: Optional[str] = Field(
        default=None,
        description="Path to saved file",
    )


# =============================================================================
# Government Data Models
# =============================================================================

class TenderResult(BaseModel):
    """EKAP tender result data from KİK."""
    
    ikn: str = Field(
        ...,
        description="İhale Kayıt Numarası (Tender Registration Number)",
    )
    title: str = Field(
        ...,
        description="İhale konusu (Tender subject)",
    )
    winner_company: str = Field(
        ...,
        description="Kazanan şirket adı",
    )
    winner_mersis: Optional[str] = Field(
        default=None,
        description="Winner company MERSIS number",
    )
    bid_amount: float = Field(
        ...,
        ge=0,
        description="Kazanan teklif tutarı",
    )
    currency: str = Field(
        default="TRY",
        description="Currency code",
    )
    tender_date: str = Field(
        ...,
        description="YYYY-MM-DD format",
    )
    sector: str = Field(
        default="CONSTRUCTION",
        description="Tender sector",
    )
    contracting_authority: str = Field(
        default="",
        description="İhaleyi yapan kurum",
    )
    source_url: str = Field(
        ...,
        description="EKAP URL",
    )
    
    def to_neo4j_params(self) -> dict[str, Any]:
        """Convert to Neo4j parameters for graph insertion."""
        return {
            "ikn": self.ikn,
            "title": self.title,
            "winner": self.winner_company,
            "mersis": self.winner_mersis,
            "amount": self.bid_amount,
            "currency": self.currency,
            "date": self.tender_date,
            "sector": self.sector,
            "authority": self.contracting_authority,
            "source": self.source_url,
        }


class BoardMember(BaseModel):
    """TÜİK TSG board member data."""
    
    company_mersis: str = Field(
        ...,
        description="Company MERSIS number",
    )
    company_name: str = Field(
        ...,
        description="Company official name",
    )
    member_name: str = Field(
        ...,
        description="Board member full name",
    )
    position: str = Field(
        ...,
        description="Yönetim Kurulu Başkanı, Üye, Genel Müdür, etc.",
    )
    start_date: Optional[str] = Field(
        default=None,
        description="Position start date YYYY-MM-DD",
    )
    end_date: Optional[str] = Field(
        default=None,
        description="Position end date if no longer active",
    )
    tc_kimlik: Optional[str] = Field(
        default=None,
        description="TC Kimlik if publicly available",
    )
    
    def to_neo4j_params(self) -> dict[str, Any]:
        """Convert to Neo4j parameters."""
        return {
            "mersis": self.company_mersis,
            "company": self.company_name,
            "name": self.member_name,
            "position": self.position,
            "start": self.start_date,
            "end": self.end_date,
        }


class CompanyUpdate(BaseModel):
    """TOBB Ticaret Sicil Gazetesi legal update."""
    
    company_name: str = Field(
        ...,
        description="Company name in announcement",
    )
    mersis_no: Optional[str] = Field(
        default=None,
        description="MERSIS number if available",
    )
    update_type: str = Field(
        ...,
        description="KURULUŞ, UNVAN DEĞİŞİKLİĞİ, TASFİYE, SERMAYE ARTIŞI, etc.",
    )
    gazette_date: str = Field(
        ...,
        description="Gazette publication date YYYY-MM-DD",
    )
    gazette_number: str = Field(
        ...,
        description="Gazette issue number",
    )
    summary: str = Field(
        default="",
        description="Brief summary of the update",
    )
    old_name: Optional[str] = Field(
        default=None,
        description="Previous company name (for name changes)",
    )
    capital: Optional[float] = Field(
        default=None,
        ge=0,
        description="Company capital amount",
    )
    
    def to_neo4j_params(self) -> dict[str, Any]:
        """Convert to Neo4j parameters."""
        return {
            "company": self.company_name,
            "mersis": self.mersis_no,
            "type": self.update_type,
            "gazette_date": self.gazette_date,
            "gazette_no": self.gazette_number,
            "summary": self.summary,
            "old_name": self.old_name,
            "capital": self.capital,
        }

