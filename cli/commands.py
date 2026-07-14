import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import settings
from pipeline.intelligence import run_intelligence_pipeline

logger = logging.getLogger(__name__)

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

def print_result(result) -> None:
    """Print a contradiction detection result to the console."""
    print(result)  # ContradictionResult.__str__ prints status/score/type/explanation
    if result.key_conflict_points:
        print("  Çelişki noktaları:")
        for point in result.key_conflict_points:
            print(f"   • {point}")
    for label, evidence in (("Kanıt 1", result.evidence_1), ("Kanıt 2", result.evidence_2)):
        if evidence:
            data = evidence.to_dict()
            text = str(data.get("text", ""))[:120]
            print(f"  {label}: {text} ({data.get('date', '?')} — {data.get('source', '?')})")


def load_sample_data(memory) -> int:
    """Load the built-in sample statements into memory. Returns count ingested."""
    ids = memory.ingest_batch(SAMPLE_POLITICAL_STATEMENTS)
    return len(ids)


def ingest_from_file(memory, path: str) -> int:
    """Ingest statements from a JSON or TXT file. Returns count ingested.

    JSON: a list of objects with keys text/speaker/date/topic/source.
    TXT:  one statement per line (no metadata).
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {path}")

    if file_path.suffix.lower() == ".json":
        items = json.loads(file_path.read_text(encoding="utf-8"))
        if not isinstance(items, list):
            raise ValueError("JSON dosyası bir liste içermeli ([{'text': ...}, ...])")
        ids = memory.ingest_batch(items)
        return len(ids)

    count = 0
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            memory.ingest_text(line, metadata={"source": file_path.name})
            count += 1
    return count


def generate_report(result) -> Optional[str]:
    """Generate a PDF insight card from the result."""
    from reporting.pdf_generator import ReportGenerator
    
    generator = ReportGenerator()
    pdf_path = generator.generate_insight_card(result.to_dict())
    
    return pdf_path

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

    # LangGraph Agent Arguments
    parser.add_argument(
        "--agent",
        action="store_true",
        help=(
            "Çoklu-ajan LangGraph analizini çalıştır (--query gerekli): "
            "Watchdog → Archivist → Searcher → Analyst → Editor → Human Approval"
        ),
    )
    parser.add_argument(
        "--date",
        type=str,
        default="",
        help="Açıklamanın tarihi (--agent ile kullanılır)",
    )
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("  ReguSense-Politics - Political Contradiction Detection")
    print("=" * 70)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70 + "\n")
    
    # Handle --agent (LangGraph multi-agent analysis)
    if args.agent:
        if not args.query:
            parser.error("--agent requires --query (the statement to analyze)")
        from agents.graph import run_analysis

        print("🤖 LangGraph Agent analizi başlatılıyor...")
        final_state = run_analysis(
            statement=args.query,
            speaker=args.speaker,
            date=args.date,
        )
        print(f"\n✅ Analiz tamamlandı (skor: {final_state.get('contradiction_score', 0)}/10)")
        report = final_state.get("final_report")
        if report:
            print(report)
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

