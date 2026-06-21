"""
PipelineState: Batch intelligence pipeline için paylaşılan durum.

Bu state, dört ajanın (IngestionAgent → ExtractionAgent → FactCheckAgent →
PublishingAgent) birbiri arasında taşıdığı tüm veriyi tutar.

Mevcut ``agents/state.py``'deki ``AgentState``'ten farklı olarak bu state,
tek bir sorgu yerine **toplu belge işleme** için tasarlanmıştır.

Annotated[List, operator.add] kullanımı LangGraph'ın paralel node'larda
listeleri güvenli şekilde birleştirmesini sağlar.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, List, Literal, Optional, TypedDict


# =============================================================================
# Veri Transfer Nesneleri (pipeline içinde taşınan lightweight objeler)
# =============================================================================

@dataclass
class StatementDTO:
    """
    PostgreSQL `statements` tablosundan gelen tekil ifade özeti.
    """
    stmt_id: int
    raw_document_id: int
    text: str
    speaker: str
    date: str
    page_number: int
    session_id: Optional[str]
    source_url: Optional[str]

    def short_text(self, n: int = 200) -> str:
        return self.text[:n] + ("…" if len(self.text) > n else "")


@dataclass
class EntityBundle:
    """
    ExtractionAgent'ın bir belgeden çıkardığı varlık seti.

    doc_id, kaynak ``RawDocumentDTO``'ya referans verir.
    """
    doc_id: int
    doc_type: str
    persons: List[str] = field(default_factory=list)       # Siyasetçi adları
    organizations: List[str] = field(default_factory=list) # Kurum/Şirket adları
    dates: List[str] = field(default_factory=list)         # Tarih ifadeleri
    topics: List[str] = field(default_factory=list)        # Konu etiketleri
    raw_text: str = ""
    speaker: str = ""
    statement_date: str = ""


@dataclass
class ContradictionBundle:
    """
    FactCheckAgent'ın ürettiği tek bir çelişki bulgusu.
    """
    doc_id: int
    speaker: str
    statement: str
    statement_date: str

    # Kanıtlar
    past_statement: str = ""
    past_date: str = ""
    past_source: str = ""

    # Skor
    contradiction_score: int = 0          # 0–10
    contradiction_type: str = "NONE"      # REVERSAL | BROKEN_PROMISE | ...
    explanation: str = ""
    key_conflict_points: List[str] = field(default_factory=list)

    # Risk seviyesi (PublishingAgent tarafından set edilir)
    risk_level: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"] = "NONE"

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "speaker": self.speaker,
            "statement": self.statement,
            "statement_date": self.statement_date,
            "past_statement": self.past_statement,
            "past_date": self.past_date,
            "past_source": self.past_source,
            "contradiction_score": self.contradiction_score,
            "contradiction_type": self.contradiction_type,
            "explanation": self.explanation,
            "key_conflict_points": self.key_conflict_points,
            "risk_level": self.risk_level,
        }


@dataclass
class InsightCard:
    """
    PublishingAgent'ın ürettiği yayına hazır içerik kartı.

    Her önemli çelişki için bir InsightCard oluşturulur.
    """
    doc_id: int
    speaker: str
    contradiction_score: int
    risk_level: str

    # Yayın formatları
    tweet_text: str = ""              # ≤280 karakter
    report_markdown: str = ""         # Tam analiz raporu
    short_summary: str = ""           # 1–2 cümle özet

    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "speaker": self.speaker,
            "contradiction_score": self.contradiction_score,
            "risk_level": self.risk_level,
            "tweet_text": self.tweet_text,
            "report_markdown": self.report_markdown,
            "short_summary": self.short_summary,
            "created_at": self.created_at,
        }


# =============================================================================
# Pipeline State
# =============================================================================

class PipelineState(TypedDict, total=False):
    """
    LangGraph StateGraph için paylaşılan durum.

    ``total=False`` → tüm alanlar opsiyonel; node'lar yalnızca
    güncelledikleri alanları döndürür.

    ``Annotated[List[X], operator.add]`` → LangGraph'ın append-only
    birleştirme semantiği; paralel node'lar aynı listeye güvenle ekler.
    """

    # ── Çalışma metadata ─────────────────────────────────────────────────────
    run_id: str                         # UUID (her çalıştırma için benzersiz)
    batch_size: int                     # Tek seferde işlenecek belge sayısı
    started_at: str                     # ISO timestamp
    completed_at: Optional[str]

    # ── Aşama 1: Ingest ──────────────────────────────────────────────────────
    statements: Annotated[List[StatementDTO], operator.add]
    # Toplam ingest edilen belge sayısı (özet için)
    ingested_count: int

    # ── Aşama 2: Extraction ──────────────────────────────────────────────────
    extracted_entities: Annotated[List[EntityBundle], operator.add]
    # Neo4j'e yazılan düğüm/ilişki sayısı
    neo4j_nodes_created: int
    neo4j_relationships_created: int

    # ── Aşama 3: FactCheck ───────────────────────────────────────────────────
    contradictions: Annotated[List[ContradictionBundle], operator.add]
    # Kaç açıklama kontrol edildi
    checked_count: int

    # ── Aşama 4: Publishing ──────────────────────────────────────────────────
    insight_cards: Annotated[List[InsightCard], operator.add]
    final_report: str                   # Genel markdown özet raporu

    # ── Hata izleme ──────────────────────────────────────────────────────────
    errors: Annotated[List[str], operator.add]


def create_pipeline_state(
    batch_size: int = 20,
    run_id: Optional[str] = None,
) -> PipelineState:
    """
    Boş bir PipelineState oluşturur.

    Args:
        batch_size: Tek seferde ingest edilecek belge sayısı (varsayılan: 20)
        run_id:     İsteğe bağlı run kimliği; verilmezse UUID üretilir

    Returns:
        Başlangıç değerleriyle dolu PipelineState
    """
    import uuid

    return PipelineState(
        run_id=run_id or str(uuid.uuid4()),
        batch_size=batch_size,
        started_at=datetime.now().isoformat(),
        completed_at=None,
        statements=[],
        ingested_count=0,
        extracted_entities=[],
        neo4j_nodes_created=0,
        neo4j_relationships_created=0,
        contradictions=[],
        checked_count=0,
        insight_cards=[],
        final_report="",
        errors=[],
    )
