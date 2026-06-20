"""
SQLAlchemy ORM Models for ReguSense.

Defines the core data models:
- Speaker: Political figures with normalized names
- Statement: Political statements with content hash for deduplication
- Source: Data sources (commissions, social media, etc.)
"""

from datetime import datetime, date, timezone
from typing import Optional, List
import hashlib
import unicodedata
import re

from sqlalchemy import (
    Column, String, Text, DateTime, Date, Integer, ForeignKey, 
    Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


def normalize_speaker_name(name: str) -> str:
    """
    Normalize speaker name for consistent matching.
    
    Handles:
    - Turkish characters (ş->s, ı->i, ç->c, ğ->g, ö->o, ü->u)
    - Case normalization
    - Whitespace cleanup
    - Twitter handles
    
    Example:
        "Mehmet Şimşek" -> "mehmet simsek"
        "@memetsimsek" -> "memetsimsek"
    """
    if not name:
        return ""
    
    # Remove @ for Twitter handles
    name = name.lstrip("@")
    
    # Turkish character mapping
    tr_map = {
        'ş': 's', 'Ş': 'S',
        'ı': 'i', 'İ': 'I',
        'ç': 'c', 'Ç': 'C',
        'ğ': 'g', 'Ğ': 'G',
        'ö': 'o', 'Ö': 'O',
        'ü': 'u', 'Ü': 'U',
    }
    
    for tr_char, ascii_char in tr_map.items():
        name = name.replace(tr_char, ascii_char)
    
    # NFD normalization to handle remaining accents
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    
    # Lowercase and clean whitespace
    name = name.lower().strip()
    name = re.sub(r'\s+', ' ', name)
    
    return name


def generate_content_hash(text: str, speaker_id: int, date: str) -> str:
    """
    Generate SHA-256 hash for content deduplication.
    
    Based on: normalized_text + speaker_id + date
    """
    # Normalize text: lowercase, strip, collapse whitespace
    normalized_text = re.sub(r'\s+', ' ', text.lower().strip())
    sp_id_str = str(speaker_id) if speaker_id else "unknown"
    
    content = f"{normalized_text}|{sp_id_str}|{date}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


class Speaker(Base):
    """
    Political figure or speaker.
    
    Stores both original and normalized names for fuzzy matching.
    """
    __tablename__ = "speakers"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    statements: Mapped[List["Statement"]] = relationship("Statement", back_populates="speaker")
    roles: Mapped[List["SpeakerRole"]] = relationship("SpeakerRole", back_populates="speaker", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<Speaker(id={self.id}, name='{self.name}')>"


class SpeakerRole(Base):
    """
    Temporal role or term for a politician.
    
    Tracks which party they belonged to and what title they held
    during a specific period (e.g., 27th Term MP for AKP).
    """
    __tablename__ = "speaker_roles"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    speaker_id: Mapped[int] = mapped_column(ForeignKey("speakers.id", ondelete="CASCADE"), index=True)
    
    party: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    term_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    speaker: Mapped["Speaker"] = relationship("Speaker", back_populates="roles")
    
    def __repr__(self) -> str:
        return f"<SpeakerRole(speaker_id={self.speaker_id}, party='{self.party}', title='{self.title}')>"


class Source(Base):
    """
    Data source (commission transcripts, social media, TV, etc.).
    """
    __tablename__ = "sources"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # TBMM_COMMISSION, SOCIAL_MEDIA, TV_INTERVIEW
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    statements: Mapped[List["Statement"]] = relationship("Statement", back_populates="source")
    
    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', type='{self.source_type}')>"


class Statement(Base):
    """
    Political statement with content hash for deduplication.
    
    The content_hash is a SHA-256 of (normalized_text + speaker_id + date)
    ensuring no duplicate statements are stored.
    """
    __tablename__ = "statements"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Foreign keys
    speaker_id: Mapped[Optional[int]] = mapped_column(ForeignKey("speakers.id"), nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"), nullable=True)
    raw_document_id: Mapped[Optional[int]] = mapped_column(ForeignKey("raw_documents.id"), nullable=True)
    
    # Metadata
    raw_speaker_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # YYYY-MM-DD
    topics: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)  # JSONB for flexibility
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # ChromaDB mapping (preserved vectors)
    chroma_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    speaker: Mapped["Speaker"] = relationship("Speaker", back_populates="statements")
    source: Mapped[Optional["Source"]] = relationship("Source", back_populates="statements")
    
    # Indexes and constraints
    __table_args__ = (
        Index('ix_statements_speaker_id', 'speaker_id'),
        Index('ix_statements_date', 'date'),
    )
    
    def __repr__(self) -> str:
        return f"<Statement(id={self.id}, speaker_id={self.speaker_id}, date='{self.date}')>"


# =============================================================================
# RawDocument – Ham Belgeler (TBMM Tutanağı, Sayıştay Raporu, vb.)
# =============================================================================

import enum as _enum


class DocumentStatus(str, _enum.Enum):
    """Ham belge işleme durumu."""
    PENDING    = "pending"     # Henüz işlenmedi
    PROCESSING = "processing"  # Aktif olarak işleniyor
    DONE       = "done"        # İşleme tamamlandı
    FAILED     = "failed"      # İşleme başarısız oldu
    SKIPPED    = "skipped"     # Kasıtlı olarak atlandı


class DocumentType(str, _enum.Enum):
    """
    Belge kaynak tipi.

    TBMM_TRANSCRIPT  : Genel Kurul veya Komisyon tutanakları
    SAYISTAY_REPORT  : Sayıştay denetim raporları
    EKAP_TENDER      : EKAP ihale ilanı / sonucu
    SOCIAL_MEDIA     : Twitter/X paylaşımı
    TV_INTERVIEW     : Televizyon röportajı transkripsiyonu
    PRESS_RELEASE    : Basın bülteni
    OTHER            : Sınıflandırılamamış belge
    """
    TBMM_TRANSCRIPT = "TBMM_TRANSCRIPT"
    SAYISTAY_REPORT  = "SAYISTAY_REPORT"
    EKAP_TENDER      = "EKAP_TENDER"
    RESMI_GAZETE     = "RESMI_GAZETE"
    SOCIAL_MEDIA     = "SOCIAL_MEDIA"
    TV_INTERVIEW     = "TV_INTERVIEW"
    PRESS_RELEASE    = "PRESS_RELEASE"
    OTHER            = "OTHER"


class RawDocument(Base):
    """
    Ham belge deposu.

    Pipeline'a giren her belge önce buraya kaydedilir; ardından işlenerek
    ``Statement`` satırlarına ve Neo4j düğümlerine dönüştürülür.

    Sütunlar:
        id                – Otomatik artan birincil anahtar
        doc_type          – Belge tipi (DocumentType enum değeri)
        title             – Belge başlığı (opsiyonel)
        source_url        – Ham belgenin URL'si (opsiyonel)
        file_path         – Sunucudaki yerel dosya yolu (opsiyonel)
        raw_text          – Ham metin içeriği
        content_hash      – SHA-256(raw_text) – yinelenen belge kontrolü
        session_id        – TBMM oturum no, EKAP IKN vb. (opsiyonel)
        date              – Belge tarihi YYYY-MM-DD (opsiyonel)
        processing_status – pending | processing | done | failed | skipped
        error_message     – Hata mesajı (başarısız olduğunda)
        metadata_json     – Ek yapılandırılmamış meta veri (JSONB)
        created_at        – Kayıt oluşturulma zamanı
        processed_at      – İşleme tamamlanma zamanı (opsiyonel)
    """
    __tablename__ = "raw_documents"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True
    )

    # ── Belge türü & kimlik ────────────────────────────────────────────────────
    doc_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=DocumentType.OTHER.value,
        index=True,
        comment="Belge tipi: TBMM_TRANSCRIPT | SAYISTAY_REPORT | EKAP_TENDER | ...",
    )
    title: Mapped[Optional[str]] = mapped_column(
        String(512),
        nullable=True,
        comment="Belge başlığı veya konu satırı",
    )

    # ── Kaynak konum ───────────────────────────────────────────────────────────
    source_url: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Ham belgenin indirildiği veya yayımlandığı URL",
    )
    file_path: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Sunucudaki yerel dosya yolu (PDF, TXT vb.)",
    )

    # ── İçerik ────────────────────────────────────────────────────────────────
    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Ham metin – hiçbir ön-işlem uygulanmamış",
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="SHA-256(raw_text) – yinelenen belge girişini engeller",
    )

    # ── Bağlam ────────────────────────────────────────────────────────────────
    session_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        comment="TBMM oturum numarası, EKAP IKN'si vb.",
    )
    date: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        comment="Belge tarihi – YYYY-MM-DD formatı",
    )

    # ── İşleme durumu ─────────────────────────────────────────────────────────
    processing_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DocumentStatus.PENDING.value,
        index=True,
        comment="pending | processing | done | failed | skipped",
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="İşleme sırasında oluşan hata mesajı",
    )

    # ── Ek meta veri ──────────────────────────────────────────────────────────
    metadata_json: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="Yapılandırılmamış ek meta veri (JSONB olarak saklanır)",
    )

    # ── Zaman damgaları ───────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        comment="İşleme tamamlandığında set edilir",
    )

    # ── Bileşik indeksler ─────────────────────────────────────────────────────
    __table_args__ = (
        Index("ix_raw_documents_type_status", "doc_type", "processing_status"),
    )

    # ── Yardımcı metotlar ─────────────────────────────────────────────────────
    @staticmethod
    def compute_hash(text: str) -> str:
        """Ham metin için SHA-256 hash üretir."""
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def mark_done(self) -> None:
        """Belgeyi başarıyla işlenmiş olarak işaretle."""
        self.processing_status = DocumentStatus.DONE.value
        self.processed_at = datetime.now(timezone.utc)

    def mark_failed(self, error: str) -> None:
        """Belgeyi başarısız olarak işaretle ve hatayı kaydet."""
        self.processing_status = DocumentStatus.FAILED.value
        self.error_message = error
        self.processed_at = datetime.now(timezone.utc)

    def __repr__(self) -> str:
        return (
            f"<RawDocument(id={self.id}, type='{self.doc_type}', "
            f"status='{self.processing_status}', date='{self.date}')>"
        )
