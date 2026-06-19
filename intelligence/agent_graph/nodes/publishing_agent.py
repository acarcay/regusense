"""
PublishingAgent Node: Çelişkileri Insight Card formatına çevirir.

Görev:
    - ``contradictions`` listesindeki her ``ContradictionBundle`` için:
        1. Tweet metni üret (≤280 karakter)
        2. Markdown rapor kartı üret
        3. Kısa özet cümlesi üret
        4. ``InsightCard`` olarak state'e ekle
    - Tüm kartları kapsayan genel markdown ``final_report`` üret.
    - JSON çıktıyı ``data/processed/`` klasörüne kaydet.

Çıkış (state güncellemesi):
    insight_cards : List[InsightCard]
    final_report  : str
    errors        : List[str]
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from intelligence.agent_graph.state import (
    ContradictionBundle,
    InsightCard,
    PipelineState,
)

logger = logging.getLogger(__name__)

# Risk rozetleri
_RISK_BADGE = {
    "CRITICAL": "🚨 KRİTİK",
    "HIGH":     "🔴 YÜKSEK",
    "MEDIUM":   "🟠 ORTA",
    "LOW":      "🟡 DÜŞÜK",
    "NONE":     "✅ YOK",
}

# Çelişki tipi açıklamaları (Türkçe)
_TYPE_LABEL = {
    "REVERSAL":       "Tam Dönüş",
    "BROKEN_PROMISE": "Tutulmayan Söz",
    "INCONSISTENCY":  "Tutarsızlık",
    "PERSONA_SHIFT":  "Kimlik Değişimi",
    "NONE":           "Tutarlı",
}

_TYPE_EMOJI = {
    "REVERSAL":       "🔄",
    "BROKEN_PROMISE": "💔",
    "INCONSISTENCY":  "⚠️",
    "PERSONA_SHIFT":  "🎭",
    "NONE":           "✅",
}


def _build_tweet(c: ContradictionBundle) -> str:
    """
    280 karakter sınırına uyan tweet metni üretir.

    Format:
        {emoji} {konuşmacı} | Skor: {X}/10 | {risk badge}
        {kısa açıklama}
        #ReguSense #SiyasiÇelişki
    """
    emoji = _TYPE_EMOJI.get(c.contradiction_type, "⚠️")
    badge = _RISK_BADGE.get(c.risk_level, "")
    hashtags = "#ReguSense #SiyasiÇelişki"

    header = f"{emoji} {c.speaker} | Skor: {c.contradiction_score}/10 | {badge}"
    footer = f"\n{hashtags}"

    # Açıklamayı sıkıştır
    max_exp_len = 280 - len(header) - len(footer) - 2
    explanation = (
        c.explanation[:max_exp_len] + "…"
        if len(c.explanation) > max_exp_len
        else c.explanation
    )

    tweet = f"{header}\n{explanation}{footer}"

    # Son kırpma garantisi
    if len(tweet) > 280:
        tweet = tweet[:277] + "…"

    return tweet


def _build_report_card(c: ContradictionBundle, run_id: str) -> str:
    """
    Tek bir çelişki için Markdown Insight Card üretir.
    """
    badge = _RISK_BADGE.get(c.risk_level, "")
    type_label = _TYPE_LABEL.get(c.contradiction_type, c.contradiction_type)
    emoji = _TYPE_EMOJI.get(c.contradiction_type, "⚠️")

    conflict_points = "\n".join(
        f"  - {p}" for p in c.key_conflict_points
    ) or "  - Belirtilmedi"

    return f"""---
## {emoji} Insight Card — {c.speaker}

| Alan               | Değer                          |
|--------------------|-------------------------------|
| **Risk Seviyesi**  | {badge}                       |
| **Çelişki Skoru**  | `{c.contradiction_score}/10`  |
| **Çelişki Tipi**   | {type_label}                  |
| **Konuşmacı**      | {c.speaker}                   |
| **Belge ID**       | #{c.doc_id}                   |
| **Run ID**         | `{run_id}`                    |
| **Oluşturulma**    | {datetime.now().strftime("%Y-%m-%d %H:%M")} |

### 📄 Yeni Açıklama *(Tarih: {c.statement_date or "Bilinmiyor"})*
> {c.statement[:400]}{"…" if len(c.statement) > 400 else ""}

### 📚 Geçmiş Açıklama *(Tarih: {c.past_date or "Bilinmiyor"} · Kaynak: {c.past_source or "Bilinmiyor"})*
> {c.past_statement[:400]}{"…" if len(c.past_statement) > 400 else ""}

### 💡 Analiz
{c.explanation}

### 🔍 Çelişki Noktaları
{conflict_points}
"""


def _build_short_summary(c: ContradictionBundle) -> str:
    """1–2 cümlelik kısa özet."""
    badge = _RISK_BADGE.get(c.risk_level, "")
    type_label = _TYPE_LABEL.get(c.contradiction_type, c.contradiction_type)
    return (
        f"{badge} — {c.speaker} için {type_label} ({c.contradiction_score}/10). "
        f"{c.explanation[:200]}"
    )


def _build_final_report(
    cards: list[InsightCard],
    state: PipelineState,
) -> str:
    """
    Tüm Insight Card'ları kapsayan genel pipeline raporu.
    """
    run_id = state.get("run_id", "?")
    started = state.get("started_at", "?")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ingested = state.get("ingested_count", 0)
    checked = state.get("checked_count", 0)
    extracted = len(state.get("extracted_entities", []))
    contradictions = state.get("contradictions", [])
    errors = state.get("errors", [])

    critical = sum(1 for c in contradictions if c.risk_level == "CRITICAL")
    high = sum(1 for c in contradictions if c.risk_level == "HIGH")
    medium = sum(1 for c in contradictions if c.risk_level == "MEDIUM")

    header = f"""# 🔬 ReguSense Intelligence Pipeline Raporu

**Run ID:** `{run_id}`
**Başlangıç:** {started}
**Tamamlanma:** {now}

---

## 📊 Özet İstatistikler

| Metrik                      | Değer        |
|-----------------------------|-------------|
| İngest edilen belge         | {ingested}   |
| Entity çıkarılan belge      | {extracted}  |
| Çelişki kontrol edilen      | {checked}    |
| Toplam çelişki bulgusu      | {len(contradictions)} |
| 🚨 KRİTİK                  | {critical}   |
| 🔴 YÜKSEK                  | {high}       |
| 🟠 ORTA                    | {medium}     |
| ❌ Hata                    | {len(errors)} |

---

## 🃏 Insight Cards

"""
    if not cards:
        body = "_Bu çalıştırmada önemli çelişki bulunamadı._\n"
    else:
        body = "\n".join(c.report_markdown for c in cards)

    footer = ""
    if errors:
        error_list = "\n".join(f"- `{e}`" for e in errors[:20])
        footer = f"\n---\n## ⚠️ Hatalar\n\n{error_list}\n"

    return header + body + footer


def _save_output(
    cards: list[InsightCard],
    final_report: str,
    run_id: str,
) -> None:
    """Çıktıları disk'e yazar (JSON + Markdown)."""
    try:
        out_dir = Path("data/processed")
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON
        json_path = out_dir / f"insight_cards_{ts}_{run_id[:8]}.json"
        json_path.write_text(
            json.dumps(
                [c.to_dict() for c in cards],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        # Markdown rapor
        md_path = out_dir / f"pipeline_report_{ts}_{run_id[:8]}.md"
        md_path.write_text(final_report, encoding="utf-8")

        logger.info(
            "PublishingAgent: Çıktılar kaydedildi → %s | %s",
            json_path, md_path,
        )

    except Exception as exc:
        logger.warning("PublishingAgent: Disk yazma hatası: %s", exc)


def publishing_agent(state: PipelineState) -> dict[str, Any]:
    """
    LangGraph node — Çelişki bulgularını Insight Card'a çevirir.

    Args:
        state: Mevcut PipelineState (``contradictions`` dolu olmalı)

    Returns:
        State güncellemesi: ``insight_cards``, ``final_report``,
        ``completed_at``, ``errors``
    """
    run_id = state.get("run_id", "unknown")
    contradictions: list[ContradictionBundle] = state.get("contradictions", [])

    logger.info(
        "PublishingAgent [run=%s]: %d çelişki için kart üretiliyor",
        run_id, len(contradictions),
    )

    cards: list[InsightCard] = []
    errors: list[str] = []

    for c in contradictions:
        try:
            tweet = _build_tweet(c)
            report_md = _build_report_card(c, run_id)
            summary = _build_short_summary(c)

            card = InsightCard(
                doc_id=c.doc_id,
                speaker=c.speaker,
                contradiction_score=c.contradiction_score,
                risk_level=c.risk_level,
                tweet_text=tweet,
                report_markdown=report_md,
                short_summary=summary,
            )
            cards.append(card)

            logger.info(
                "PublishingAgent: ✅ Kart oluşturuldu | %s | %s | skor=%d",
                c.speaker, _RISK_BADGE.get(c.risk_level, ""), c.contradiction_score,
            )

        except Exception as exc:
            msg = f"PublishingAgent kart oluşturma hatası (belge {c.doc_id}): {exc}"
            logger.exception(msg)
            errors.append(msg)

    # ── Genel rapor ───────────────────────────────────────────────────────
    final_report = _build_final_report(cards, state)

    # ── Disk'e kaydet ─────────────────────────────────────────────────────
    _save_output(cards, final_report, run_id)

    logger.info(
        "PublishingAgent [run=%s]: %d kart üretildi, pipeline tamamlandı.",
        run_id, len(cards),
    )

    return {
        "insight_cards": cards,
        "final_report": final_report,
        "completed_at": datetime.now().isoformat(),
        "errors": errors,
    }
