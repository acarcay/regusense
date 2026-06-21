"""
ReguSense-Politics: Political Contradiction Detection System.

Detects contradictions between new political statements and historical records
using semantic search (RAG) and LLM verification.

Workflow:
1. Initialize PoliticalMemory (ChromaDB vector store)
2. Load historical data if DB is empty
3. Accept new statement input
4. Detect contradictions using ContradictionDetector
5. Generate PDF insight card if contradiction score > threshold

Usage:
    python main.py                                    # Interactive mode
    python main.py --query "statement" --speaker "Name"  # Direct query
    python main.py --ingest data/statements.json     # Ingest data file
    python main.py --stats                           # Show memory stats

Author: ReguSense Team
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings

# Ensure directories exist
settings.ensure_directories()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.logs_dir / "pipeline.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# Sample Data for Initial Population
# ============================================================================

SAMPLE_POLITICAL_STATEMENTS = [
    {
        "text": "Enflasyon yüzde 70 civarında kalacak, düşürmek zaman alacak.",
        "speaker": "Mehmet Şimşek",
        "date": "2023-06-15",
        "topic": "Ekonomi",
        "source": "Basın Açıklaması",
    },
    {
        "text": "Faiz oranlarını yükseltmek zorundayız, başka çaremiz yok.",
        "speaker": "Mehmet Şimşek",
        "date": "2023-07-20",
        "topic": "Ekonomi",
        "source": "TBMM",
    },
    {
        "text": "Dolar kuru kontrol altında, endişeye gerek yok.",
        "speaker": "Mehmet Şimşek",
        "date": "2023-08-10",
        "topic": "Ekonomi",
        "source": "Televizyon Röportajı",
    },
    {
        "text": "Enflasyonla mücadele en önemli önceliğimiz.",
        "speaker": "Mehmet Şimşek",
        "date": "2023-09-05",
        "topic": "Ekonomi",
        "source": "G20 Zirvesi",
    },
    {
        "text": "Asgari ücret artışı enflasyonun altında kalabilir.",
        "speaker": "Mehmet Şimşek",
        "date": "2023-10-01",
        "topic": "Ekonomi",
        "source": "Basın Açıklaması",
    },
    {
        "text": "Kripto paralar yasaklanmalı, finans sistemini tehdit ediyor.",
        "speaker": "BDDK Başkanı",
        "date": "2022-04-15",
        "topic": "Finans",
        "source": "TBMM Komisyon",
    },
    {
        "text": "Dijital varlıklar için düzenleme şart, yasak çözüm değil.",
        "speaker": "BDDK Başkanı",
        "date": "2023-11-20",
        "topic": "Finans",
        "source": "Basın Toplantısı",
    },
]


def initialize_memory():
    """Initialize and return the PoliticalMemory instance."""
    from memory.vector_store import PoliticalMemory
    
    memory = PoliticalMemory()
    logger.info(f"PoliticalMemory initialized with {memory.count()} documents")
    return memory


def load_sample_data(memory) -> int:
    """Load sample political statements into memory."""
    ids = memory.ingest_batch(SAMPLE_POLITICAL_STATEMENTS)
    logger.info(f"Loaded {len(ids)} sample statements into memory")
    return len(ids)


def ingest_from_file(memory, file_path: str) -> int:
    """Ingest statements from a JSON or TXT file."""
    from scrapers.political_scraper import ManualDataIngest
    
    ingest = ManualDataIngest()
    path = Path(file_path)
    
    if path.suffix.lower() == ".json":
        statements = ingest.load_json(path)
    elif path.suffix.lower() == ".txt":
        statements = ingest.load_txt(path)
    else:
        logger.error(f"Unsupported file format: {path.suffix}")
        return 0
    
    if not statements:
        logger.warning(f"No statements found in {file_path}")
        return 0
    
    # Convert to dict format for ingestion
    items = [s.to_dict() for s in statements]
    ids = memory.ingest_batch(items)
    
    logger.info(f"Ingested {len(ids)} statements from {file_path}")
    return len(ids)


def run_detection(
    memory,
    query: str,
    speaker: str = "",
    threshold: int = 70,
):
    """Run contradiction detection on a query."""
    from intelligence.contradiction_engine import ContradictionDetector
    from intelligence.gemini_analyzer import GeminiAnalyst
    
    # Check for API key
    api_key = settings.gemini_api_key
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        raise ValueError("GEMINI_API_KEY environment variable required")
    
    # Initialize components
    analyzer = GeminiAnalyst(api_key=api_key)
    detector = ContradictionDetector(memory, analyzer, contradiction_threshold=threshold)
    
    # Run detection
    result = detector.detect(query, speaker=speaker)
    
    return result


def generate_report(result) -> Optional[str]:
    """Generate a PDF insight card from the result."""
    from reporting.pdf_generator import ReportGenerator
    
    generator = ReportGenerator()
    pdf_path = generator.generate_insight_card(result.to_dict())
    
    return pdf_path


# =============================================================================
# Intelligence Pipeline Orchestration
# =============================================================================

# =============================================================================
# LangGraph Agent Pipeline
# =============================================================================

async def run_agent_pipeline(
    batch_size: int = 20,
    dry_run: bool = False,
) -> dict:
    """
    ReguSense Intelligence Pipeline'ını LangGraph üzerinden çalıştırır.

    Akış:
        IngestionAgent  → PostgreSQL'den pending RawDocument'ları çeker
        ExtractionAgent → Entity çıkarır, Neo4j'e yazar
        FactCheckAgent  → ChromaDB + LLM ile çelişki tespiti
        PublishingAgent → Insight Card (tweet + rapor) üretir

    Args:
        batch_size: Tek çalıştırmada işlenecek belge sayısı (varsayılan: 20)
        dry_run:    True ise sadece ingest + extraction; FactCheck atlanır

    Returns:
        Pipeline'ın final state özeti (dict)
    """
    from intelligence.agent_graph import run_pipeline_async

    logger.info("=" * 70)
    logger.info("🤖 LANGGRAPH AGENT PIPELINE BAŞLIYOR")
    logger.info("   batch_size=%d | dry_run=%s", batch_size, dry_run)
    logger.info("=" * 70)

    if dry_run:
        logger.info("⚠️  Dry-run modu: FactCheck ve Publishing atlanıyor.")
        # Dry-run: yalnızca ingest + extraction pipeline'ı çalıştır
        # (graph conditional edges zaten belge yoksa durduruyor)

    final_state = await run_pipeline_async(batch_size=batch_size)

    # Özet çıktı
    cards = final_state.get("insight_cards", [])
    contradictions = final_state.get("contradictions", [])
    errors = final_state.get("errors", [])

    summary = {
        "run_id":             final_state.get("run_id"),
        "ingested_count":     final_state.get("ingested_count", 0),
        "extracted_count":    len(final_state.get("extracted_entities", [])),
        "contradiction_count": len(contradictions),
        "insight_card_count": len(cards),
        "error_count":        len(errors),
        "completed_at":       final_state.get("completed_at"),
    }

    logger.info("📊 Pipeline özeti: %s", summary)
    return summary


async def run_intelligence_pipeline(
    ekap_days: int = 30,
    hunter_max: Optional[int] = None,
    temporal_window: int = 15,
) -> dict:
    """
    Run the full intelligence pipeline: EKAP → Hunter → Temporal Analysis.
    
    This orchestrates all 4 modules:
    1. Stealth EKAP Scraper - Fetch recent tenders
    2. Hunter Scan - Find company mentions with intent classification
    3. Dynamic Ambiguity - Automatically handled by Hunter
    4. Temporal Conflict Analysis - Detect tender-advocacy timing correlations
    
    Args:
        ekap_days: Days to look back for EKAP tenders
        hunter_max: Max statements to scan (None = all)
        temporal_window: Days window for temporal conflict detection
        
    Returns:
        Summary dict with statistics from each stage
    """
    logger.info("=" * 70)
    logger.info("🚀 INTELLIGENCE PIPELINE STARTING")
    logger.info("=" * 70)
    
    from typing import Any
    summary: dict[str, Any] = {
        "ekap": {"success": False, "tenders_found": 0},
        "hunter": {"success": False, "matches": 0, "conflicts": 0},
        "temporal": {"success": False, "critical_conflicts": 0},
    }
    
    start_time = datetime.now()
    
    # Stage 1: EKAP Stealth Scraper
    logger.info("\n" + "=" * 50)
    logger.info("📋 STAGE 1: EKAP Stealth Scraper")
    logger.info("=" * 50)
    
    try:
        from scrapers.ekap_scraper import EkapScraper
        
        async with EkapScraper(headless=True) as scraper:
            result = await scraper.scrape_latest(days=ekap_days)
            summary["ekap"]["success"] = result.success
            summary["ekap"]["tenders_found"] = result.items_found
            logger.info(f"✅ EKAP: {result.items_found} tenders found in {result.duration_seconds:.1f}s")
    except Exception as e:
        logger.error(f"❌ EKAP stage failed: {e}")
    
    # Stage 2: Hunter Scan with Intent Classification
    logger.info("\n" + "=" * 50)
    logger.info("🎯 STAGE 2: Hunter Scan (Intent Classification)")
    logger.info("=" * 50)
    
    try:
        from scripts.hunter_scan import run_hunter_scan
        
        await run_hunter_scan(
            batch_size=1000,
            max_statements=hunter_max,
            create_pending_threshold=3,
        )
        summary["hunter"]["success"] = True
        logger.info("✅ Hunter scan complete")
    except Exception as e:
        logger.error(f"❌ Hunter stage failed: {e}")
    
    # Stage 3: Temporal Conflict Analysis
    logger.info("\n" + "=" * 50)
    logger.info("🔥 STAGE 3: Temporal Conflict Analysis")
    logger.info("=" * 50)
    
    try:
        from database import neo4j_client
        
        conflicts = await neo4j_client.find_all_temporal_conflicts(window_days=temporal_window)
        
        critical_count = sum(1 for c in conflicts if c.get("risk_level") == "CRITICAL")
        summary["temporal"]["success"] = True
        summary["temporal"]["conflicts_found"] = len(conflicts)
        summary["temporal"]["critical_conflicts"] = critical_count
        
        if critical_count > 0:
            logger.warning(f"🚨 {critical_count} CRITICAL temporal conflicts detected!")
            for c in conflicts[:5]:  # Show top 5
                if c.get("risk_level") == "CRITICAL":
                    logger.warning(
                        f"  🔥 {c.get('politician_name')} ({c.get('party')}) → "
                        f"{c.get('company_name')} ({c.get('days_difference')} days)"
                    )
        else:
            logger.info("✅ No critical temporal conflicts found")
            
    except Exception as e:
        logger.error(f"❌ Temporal analysis stage failed: {e}")
    
    # Summary
    duration = (datetime.now() - start_time).total_seconds()
    
    logger.info("\n" + "=" * 70)
    logger.info("📊 INTELLIGENCE PIPELINE COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Duration: {duration:.1f}s")
    logger.info(f"  EKAP Tenders: {summary['ekap']['tenders_found']}")
    logger.info(f"  Hunter Success: {summary['hunter']['success']}")
    logger.info(f"  Temporal Conflicts: {summary['temporal'].get('conflicts_found', 0)}")
    logger.info(f"  CRITICAL Risks: {summary['temporal']['critical_conflicts']}")
    logger.info("=" * 70)
    
    # Save summary
    summary["duration_seconds"] = duration
    summary["completed_at"] = datetime.now().isoformat()
    
    summary_path = settings.processed_dir / f"intelligence_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"📄 Summary saved: {summary_path}")
    
    return summary



def print_result(result) -> None:
    """Print the detection result to console."""
    print("\n" + "=" * 70)
    print("  ReguSense-Politics: Contradiction Analysis")
    print("=" * 70)
    
    status = "⚠️  ÇELİŞKİ TESPİT EDİLDİ" if result.is_contradiction else "✓ TUTARLI"
    print(f"\n{status}")
    print(f"  Skor: {result.contradiction_score}/100")
    print(f"  Tip: {result.contradiction_type.value}")
    
    if result.speaker:
        print(f"  Konuşmacı: {result.speaker}")
    
    print(f"\n📄 Yeni Açıklama:")
    print(f"   \"{result.new_statement}\"")
    
    if result.historical_matches:
        print(f"\n📚 En Yakın Geçmiş Açıklamalar ({len(result.historical_matches)} adet):")
        for i, match in enumerate(result.historical_matches[:3], 1):
            print(f"\n   {i}. [{match.get('date', 'N/A')}] (Benzerlik: {match.get('similarity', 0):.0%})")
            print(f"      \"{match.get('text', '')[:100]}...\"")
    
    if result.explanation:
        print(f"\n💡 Analiz:")
        print(f"   {result.explanation}")
    
    if result.key_conflict_points:
        print(f"\n🔍 Çelişki Noktaları:")
        for point in result.key_conflict_points:
            print(f"   • {point}")
    
    print("\n" + "=" * 70)


def interactive_mode(memory) -> None:
    """Run in interactive mode for testing."""
    print("\n" + "=" * 70)
    print("  ReguSense-Politics: Interactive Mode")
    print("=" * 70)
    print(f"\n  Veritabanında {memory.count()} kayıt bulunuyor.")
    print("  Çıkmak için 'q' yazın.\n")
    
    while True:
        try:
            query = input("📝 Yeni açıklama girin: ").strip()
            if query.lower() == 'q':
                break
            if not query:
                continue
            
            speaker = input("👤 Konuşmacı (opsiyonel): ").strip()
            
            print("\n⏳ Analiz ediliyor...")
            result = run_detection(memory, query, speaker)
            
            print_result(result)
            
            if result.is_contradiction:
                generate_pdf = input("\n📄 PDF rapor oluşturulsun mu? (e/h): ").strip().lower()
                if generate_pdf == 'e':
                    pdf_path = generate_report(result)
                    print(f"✅ PDF oluşturuldu: {pdf_path}")
            
            print()
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"❌ Hata: {e}")
    
    print("\n👋 Hoşçakalın!\n")


def main() -> None:
    """Entry point for the pipeline."""
    parser = argparse.ArgumentParser(
        description="ReguSense-Politics: Political Contradiction Detection System"
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        help="New statement to analyze for contradictions",
    )
    parser.add_argument(
        "--speaker", "-s",
        type=str,
        default="",
        help="Speaker name for the query",
    )
    parser.add_argument(
        "--ingest", "-i",
        type=str,
        help="Path to JSON/TXT file to ingest into memory",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=70,
        help="Contradiction score threshold for reporting (default: 70)",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show memory statistics and exit",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear all data from memory",
    )
    parser.add_argument(
        "--load-sample",
        action="store_true",
        help="Load sample political statements",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Don't generate PDF report for contradictions",
    )
    
    # Intelligence Pipeline Arguments
    parser.add_argument(
        "--intelligence-scan",
        action="store_true",
        help="Run full intelligence pipeline: EKAP → Hunter → Temporal Analysis",
    )
    parser.add_argument(
        "--ekap-days",
        type=int,
        default=30,
        help="Days to look back for EKAP tenders (default: 30)",
    )
    parser.add_argument(
        "--hunter-max",
        type=int,
        default=None,
        help="Max statements to scan in Hunter (default: all)",
    )

    # LangGraph Agent Pipeline Arguments
    parser.add_argument(
        "--agent-pipeline",
        action="store_true",
        help=(
            "LangGraph çoklu-ajan pipeline'ını çalıştır: "
            "IngestionAgent → ExtractionAgent → FactCheckAgent → PublishingAgent"
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Agent pipeline'ında tek seferde işlenecek belge sayısı (varsayılan: 20)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sadece ingest + extraction; FactCheck ve Publishing atla",
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("  ReguSense-Politics - Political Contradiction Detection")
    print("=" * 70)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")
    
    # Handle --agent-pipeline (LangGraph multi-agent)
    if args.agent_pipeline:
        import asyncio
        print("🤖 LangGraph Agent Pipeline başlatılıyor...")
        print(f"   batch_size={args.batch_size} | dry_run={args.dry_run}")
        summary = asyncio.run(
            run_agent_pipeline(
                batch_size=args.batch_size,
                dry_run=args.dry_run,
            )
        )
        print("\n✅ Pipeline tamamlandı:")
        for k, v in summary.items():
            print(f"   {k}: {v}")
        return

    # Handle --intelligence-scan (run before memory init as it's separate)
    if args.intelligence_scan:
        import asyncio
        print("🚀 Starting Intelligence Pipeline...")
        asyncio.run(run_intelligence_pipeline(
            ekap_days=args.ekap_days,
            hunter_max=args.hunter_max,
        ))
        return
    
    # Initialize memory
    memory = initialize_memory()
    
    # Handle --clear
    if args.clear:
        confirm = input("⚠️  Tüm veriler silinecek. Emin misiniz? (evet): ").strip()
        if confirm.lower() == "evet":
            memory.clear()
            print("✅ Tüm veriler silindi.")
        else:
            print("❌ İptal edildi.")
        return
    
    # Handle --stats
    if args.stats:
        stats = memory.get_stats()
        print("📊 Memory Statistics:")
        print(f"   Collection: {stats['collection_name']}")
        print(f"   Documents: {stats['document_count']}")
        print(f"   Persist Dir: {stats['persist_dir']}")
        print(f"   Model: {stats['model_name']}")
        return
    
    # Handle --load-sample
    if args.load_sample:
        count = load_sample_data(memory)
        print(f"✅ {count} örnek açıklama yüklendi.")
        return
    
    # Handle --ingest
    if args.ingest:
        count = ingest_from_file(memory, args.ingest)
        print(f"✅ {count} açıklama içe aktarıldı.")
        return
    
    # Check if DB is empty and load sample data
    if memory.count() == 0:
        print("📭 Veritabanı boş. Örnek veriler yükleniyor...")
        load_sample_data(memory)
        print(f"✅ {memory.count()} örnek açıklama yüklendi.\n")
    
    # Handle --query
    if args.query:
        print(f"🔍 Sorgu: \"{args.query}\"")
        if args.speaker:
            print(f"👤 Konuşmacı: {args.speaker}")
        print()
        
        try:
            result = run_detection(memory, args.query, args.speaker, args.threshold)
            print_result(result)
            
            # Generate PDF if contradiction detected
            if result.is_contradiction and not args.no_pdf:
                pdf_path = generate_report(result)
                print(f"\n📄 PDF Rapor: {pdf_path}")
            
            # Save JSON result
            json_path = settings.processed_dir / f"contradiction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            json_path.write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"📋 JSON Rapor: {json_path}")
            
        except Exception as e:
            print(f"❌ Hata: {e}")
            logger.exception("Detection failed")
        
        return
    
    # Default: Interactive mode
    interactive_mode(memory)


if __name__ == "__main__":
    main()
