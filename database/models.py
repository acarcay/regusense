"""
SQLAlchemy ORM Models for ReguSense.

Defines the core data models:
- Speaker: Political figures with normalized names
- Statement: Political statements with content hash for deduplication
- Source: Data sources (commissions, social media, etc.)
"""

from datetime import datetime
from typing import Optional, List
import hashlib
import unicodedata
import re

from sqlalchemy import (
    Column, String, Text, DateTime, Integer, ForeignKey, 
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
    
    content = f"{normalized_text}|{speaker_id}|{date}"
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
    party: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    statements: Mapped[List["Statement"]] = relationship("Statement", back_populates="speaker")
    
    def __repr__(self) -> str:
        return f"<Speaker(id={self.id}, name='{self.name}')>"


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
    speaker_id: Mapped[int] = mapped_column(ForeignKey("speakers.id"), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"), nullable=True)
    
    # Metadata
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
