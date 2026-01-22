"""
Graph Schema: Pydantic models for Neo4j nodes.

Generic nodes for multi-sector conflict detection:
- Politician, Organization, Sector, RegulatoryAction, Statement
"""

from datetime import date
from typing import Optional, Literal
from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================

SectorCode = Literal[
    "CONSTRUCTION",
    "ENERGY",
    "HEALTH",
    "MINING",
    "FINANCE",
    "AGRICULTURE",
    "DEFENSE",
    "TELECOM",
    "MEDIA",
    "OTHER",
]

ConnectionType = Literal[
    "spouse",
    "first_degree_relative",
    "board_member",
    "shareholder",
    "founder",
    "former_partner",
    "advisor",
    "lobbyist",
    "sector_acquaintance",
    "schoolmate",
    "unknown",
]

OrgType = Literal[
    "holding",
    "company",
    "foundation",
    "association",
    "public_institution",
]

ActionType = Literal[
    "tender",           # İhale
    "license",          # Lisans
    "incentive",        # Teşvik
    "zoning",           # İmar İzni
    "law_change",       # Kanun Değişikliği
    "sanction",         # Yaptırım
    "quota",            # Kota
    "other",
]


# =============================================================================
# Node Models
# =============================================================================

class PoliticianNode(BaseModel):
    """Politician node for Neo4j."""
    
    pg_id: int = Field(..., description="PostgreSQL ID")
    name: str
    normalized_name: str
    party: str = ""
    
    def to_cypher_props(self) -> dict:
        return self.model_dump()


class OrganizationNode(BaseModel):
    """Organization node (company, holding, foundation)."""
    
    name: str
    mersis_no: Optional[str] = Field(None, description="MERSİS registration number")
    vergi_no: Optional[str] = Field(None, description="Tax ID")
    org_type: OrgType = "company"
    
    def to_cypher_props(self) -> dict:
        return self.model_dump(exclude_none=True)


class SectorNode(BaseModel):
    """Sector node."""
    
    code: SectorCode
    name: str
    keywords: list[str] = Field(default_factory=list)
    
    def to_cypher_props(self) -> dict:
        return self.model_dump()


class RegulatoryActionNode(BaseModel):
    """Regulatory action (tender, license, incentive, etc.)."""
    
    action_type: ActionType
    date: date
    description: str
    source_url: Optional[str] = None
    content_hash: Optional[str] = None
    
    def to_cypher_props(self) -> dict:
        d = self.model_dump()
        d["date"] = self.date.isoformat()
        return d


class StatementNode(BaseModel):
    """Statement node linked from PostgreSQL."""
    
    pg_id: int = Field(..., description="PostgreSQL statement ID")
    text_hash: str
    date: date
    
    def to_cypher_props(self) -> dict:
        d = self.model_dump()
        d["date"] = self.date.isoformat()
        return d


# =============================================================================
# Relationship Models
# =============================================================================

class ConnectionRelationship(BaseModel):
    """CONNECTED_TO relationship between Politician and Organization."""
    
    connection_type: ConnectionType
    weight: float = Field(..., ge=0.0, le=1.0)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    last_verified: date = Field(default_factory=date.today)
    source: str = ""
    
    def to_cypher_props(self) -> dict:
        d = self.model_dump()
        if self.start_date:
            d["start_date"] = self.start_date.isoformat()
        if self.end_date:
            d["end_date"] = self.end_date.isoformat()
        d["last_verified"] = self.last_verified.isoformat()
        return d


class OperatesInRelationship(BaseModel):
    """OPERATES_IN relationship between Organization and Sector."""
    
    primary: bool = True


class AffectsRelationship(BaseModel):
    """AFFECTS relationship between RegulatoryAction and Sector."""
    
    impact_level: Literal["high", "medium", "low"] = "medium"


class AboutRelationship(BaseModel):
    """ABOUT relationship between Statement and Sector."""
    
    confidence: float = Field(..., ge=0.0, le=1.0)
    detected_keywords: list[str] = Field(default_factory=list)


# =============================================================================
# Sector Definitions
# =============================================================================

SECTOR_DEFINITIONS: list[SectorNode] = [
    SectorNode(
        code="CONSTRUCTION",
        name="İnşaat",
        keywords=["inşaat", "müteahhit", "ihale", "imar", "konut", "toki", "köprü", "otoyol"],
    ),
    SectorNode(
        code="ENERGY",
        name="Enerji",
        keywords=["enerji", "elektrik", "santral", "güneş", "rüzgar", "doğalgaz", "epdk", "lisans"],
    ),
    SectorNode(
        code="HEALTH",
        name="Sağlık",
        keywords=["sağlık", "ilaç", "hastane", "tıbbi", "cihaz", "titck", "sgk"],
    ),
    SectorNode(
        code="MINING",
        name="Madencilik",
        keywords=["maden", "kömür", "altın", "ruhsat", "mapeg", "ocak"],
    ),
    SectorNode(
        code="FINANCE",
        name="Finans",
        keywords=["banka", "finans", "kredi", "bddk", "spk", "borsa", "halka arz"],
    ),
    SectorNode(
        code="AGRICULTURE",
        name="Tarım",
        keywords=["tarım", "çiftçi", "tohum", "gübre", "ithalat", "kota", "hasat"],
    ),
    SectorNode(
        code="DEFENSE",
        name="Savunma",
        keywords=["savunma", "silah", "askeri", "ssb", "ihale"],
    ),
    SectorNode(
        code="TELECOM",
        name="Telekomünikasyon",
        keywords=["telekomünikasyon", "gsm", "internet", "btk", "frekans"],
    ),
    SectorNode(
        code="MEDIA",
        name="Medya",
        keywords=["medya", "televizyon", "gazete", "rtük", "yayın"],
    ),
]
