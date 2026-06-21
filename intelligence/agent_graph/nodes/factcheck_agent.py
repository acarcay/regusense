"""
FactCheckAgent Node: ChromaDB + LLM ile çelişki tespiti yapar.

Görev:
    - ``extracted_entities`` listesindeki her ``EntityBundle`` için:
        1. ChromaDB'den (``PoliticalMemory``) geçmiş ifadeleri çek
        2. Gemini Pro ile çelişki analizi yap
        3. Skor ≥ eşik değeri olanları ``ContradictionBundle`` olarak ekle
    - Düşük skorlu bulgular sessizce atlanır.

Eşik değeri: ``CONTRADICTION_THRESHOLD = 6``  (0–10 ölçeğinde)

Çıkış (state güncellemesi):
    contradictions : List[ContradictionBundle]
    checked_count  : int
    errors         : List[str]
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from config.settings import settings
from intelligence.agent_graph.state import (
    ContradictionBundle,
    EntityBundle,
    PipelineState,
)

logger = logging.getLogger(__name__)

CONTRADICTION_THRESHOLD = 6  # 0–10 skalası; 6+ = çelişki var

FACTCHECK_PROMPT = """Sen bir siyasi çelişki analisti'sin. Aşağıdaki iki açıklamayı karşılaştır.

## Konuşmacı
{speaker}

## Kanıt 1 — Geçmiş Açıklama
Tarih    : {past_date}
Kaynak   : {past_source}
Açıklama : "{past_text}"

## Kanıt 2 — Yeni Açıklama
Tarih    : {new_date}
Açıklama : "{new_text}"

## Görev
Tutarsızlığı 0–10 arasında puanla (0 = tamamen tutarlı, 10 = tam çelişki).

## Yanıt Formatı (sadece geçerli JSON döndür)
{{
    "contradiction_score": <0-10>,
    "contradiction_type": "<REVERSAL|BROKEN_PROMISE|INCONSISTENCY|PERSONA_SHIFT|NONE>",
    "explanation": "<Türkçe 1-2 cümle açıklama>",
    "key_conflict_points": ["<nokta 1>", "<nokta 2>"]
}}"""


def _call_gemini(prompt: str) -> dict:
    """
    Gemini Pro API'yi çağırır ve JSON yanıtı ayrıştırır.

    Hata durumunda boş/nötr skor döner; pipeline çökmez.
    """
    api_key = settings.gemini_api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("FactCheckAgent: Gemini API key bulunamadı — .env dosyasını kontrol et")
        return {"contradiction_score": 0, "contradiction_type": "NONE",
                "explanation": "API key yok", "key_conflict_points": []}

    try:
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=api_key,
            temperature=0.2,
        )
        response = llm.invoke(prompt)
        raw = response.content.strip()

        # Markdown kod bloğunu temizle
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE)

        return json.loads(raw.strip())

    except json.JSONDecodeError as exc:
        logger.warning("FactCheckAgent: JSON ayrıştırma hatası: %s", exc)
    except Exception as exc:
        logger.error("FactCheckAgent: Gemini çağrısı başarısız: %s", exc)

    return {
        "contradiction_score": 0,
        "contradiction_type": "NONE",
        "explanation": "LLM analizi başarısız",
        "key_conflict_points": [],
    }


def _search_chromadb(
    query_text: str,
    speaker: Optional[str],
    top_k: int = 5,
) -> list[dict]:
    """
    ChromaDB'de semantik arama yapar.

    Returns:
        List of dicts with keys: text, date, source, source_type, similarity
    """
    try:
        from memory.vector_store import PoliticalMemory

        memory = PoliticalMemory()
        matches = memory.search(
            query_text=query_text,
            top_k=top_k,
            speaker_filter=speaker if speaker else None,
        )

        return [
            {
                "text": m.text,
                "date": m.date,
                "source": m.source,
                "source_type": m.source_type,
                "similarity": m.similarity,
            }
            for m in matches
        ]

    except Exception as exc:
        logger.warning("FactCheckAgent: ChromaDB arama hatası: %s", exc)
        return []


def _determine_risk_level(score: int) -> str:
    """Çelişki skoruna göre risk seviyesi döner."""
    if score >= 9:
        return "CRITICAL"
    if score >= 7:
        return "HIGH"
    if score >= CONTRADICTION_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def _check_bundle(bundle: EntityBundle) -> Optional[ContradictionBundle]:
    """
    Tek bir EntityBundle için çelişki kontrolü yapar.

    Returns:
        ContradictionBundle (skor ≥ eşik) veya None
    """
    if not bundle.raw_text.strip() or not bundle.speaker:
        return None

    # ── Geçmiş ifadeleri çek ──────────────────────────────────────────────
    past_matches = _search_chromadb(
        query_text=bundle.raw_text,
        speaker=bundle.speaker,
        top_k=5,
    )

    if not past_matches:
        logger.debug(
            "FactCheckAgent: Belge %d için geçmiş ifade bulunamadı (%s)",
            bundle.doc_id, bundle.speaker,
        )
        return None

    # En yüksek benzerlik puanlı eşleşmeyi kullan
    best_match = max(past_matches, key=lambda m: m["similarity"])

    # ── LLM çelişki analizi ───────────────────────────────────────────────
    prompt = FACTCHECK_PROMPT.format(
        speaker=bundle.speaker,
        past_date=best_match.get("date", "Bilinmiyor"),
        past_source=best_match.get("source_type", "Bilinmiyor"),
        past_text=best_match["text"][:800],
        new_date=bundle.statement_date or "Bugün",
        new_text=bundle.raw_text[:800],
    )

    analysis = _call_gemini(prompt)

    score = min(10, max(0, int(analysis.get("contradiction_score", 0))))

    if score < CONTRADICTION_THRESHOLD:
        logger.debug(
            "FactCheckAgent: Belge %d skor=%d (eşik altı, atlanıyor)",
            bundle.doc_id, score,
        )
        return None

    return ContradictionBundle(
        doc_id=bundle.doc_id,
        speaker=bundle.speaker,
        statement=bundle.raw_text[:1000],
        statement_date=bundle.statement_date,
        past_statement=best_match["text"][:1000],
        past_date=best_match.get("date", ""),
        past_source=best_match.get("source_type", ""),
        contradiction_score=score,
        contradiction_type=analysis.get("contradiction_type", "NONE"),
        explanation=analysis.get("explanation", ""),
        key_conflict_points=analysis.get("key_conflict_points", []),
        risk_level=_determine_risk_level(score),
    )


def factcheck_agent(state: PipelineState) -> dict[str, Any]:
    """
    LangGraph node — Her EntityBundle için çelişki kontrolü yapar.

    Senkron node (GLiNER/ChromaDB bağımlılıkları async olmadığından).
    LangGraph async graph kullanıyorsa ``asyncio.to_thread`` ile sarmalanabilir.

    Args:
        state: Mevcut PipelineState

    Returns:
        State güncellemesi: ``contradictions``, ``checked_count``, ``errors``
    """
    run_id = state.get("run_id", "unknown")
    bundles: list[EntityBundle] = state.get("extracted_entities", [])

    logger.info(
        "FactCheckAgent [run=%s]: %d bundle kontrol edilecek",
        run_id, len(bundles),
    )

    if not bundles:
        logger.info("FactCheckAgent: İncelenecek entity bundle yok.")
        return {
            "contradictions": [],
            "checked_count": 0,
            "errors": [],
        }

    found: list[ContradictionBundle] = []
    errors: list[str] = []
    checked = 0

    for bundle in bundles:
        try:
            result = _check_bundle(bundle)
            checked += 1

            if result:
                found.append(result)
                logger.info(
                    "FactCheckAgent: ⚠️ Çelişki! Belge %d | skor=%d | "
                    "tip=%s | risk=%s | konuşmacı=%s",
                    result.doc_id,
                    result.contradiction_score,
                    result.contradiction_type,
                    result.risk_level,
                    result.speaker,
                )

        except Exception as exc:
            msg = f"FactCheckAgent belge {bundle.doc_id} hata: {exc}"
            logger.exception(msg)
            errors.append(msg)

    logger.info(
        "FactCheckAgent [run=%s]: %d/%d kontrol edildi, "
        "%d çelişki bulundu",
        run_id, checked, len(bundles), len(found),
    )

    return {
        "contradictions": found,
        "checked_count": checked,
        "errors": errors,
    }
