"""
ReguSense Main Pipeline.

Orchestrates the full data pipeline:
1. Scrape commission transcripts from TBMM (single or all commissions)
2. Extract text from downloaded PDFs
3. Analyze text for legislative risks (keyword matching)
4. AI verification with Google Gemini
5. Generate verified intelligence report

Usage:
    python main.py                      # Run for default commission
    python main.py --commission adalet  # Run for specific commission
    python main.py --all                # Run for ALL commissions
    python main.py --skip-scrape        # Use existing PDFs
    python main.py --skip-scrape --no-ai

Author: ReguSense Team
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dotenv import load_dotenv

load_dotenv()
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import (
    COMMISSION_SOURCES,
    COMMISSION_URLS,
    DEFAULT_COMMISSION,
    get_all_commissions,
    get_commission_url,
    settings,
)
from processors.pdf_processor import PDFProcessor
from intelligence.risk_engine import RiskEngine, Sector
from scrapers.commission_scraper import CommissionScraper

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


async def scrape_commission(
    commission_key: str,
    scraper: CommissionScraper,
) -> tuple[str, Optional[Path], Optional[str]]:
    """
    Scrape a single commission and return the result.
    
    Args:
        commission_key: Key from COMMISSION_SOURCES
        scraper: Active CommissionScraper instance
        
    Returns:
        Tuple of (commission_key, saved_path, error_message)
    """
    commission_info = COMMISSION_SOURCES.get(commission_key)
    if not commission_info:
        return (commission_key, None, f"Unknown commission: {commission_key}")
    
    url = commission_info["url"]
    name = commission_info["name"]
    
    print(f"\n   📌 {name}")
    print(f"      URL: {url[:60]}...")
    
    try:
        result = await scraper.download_latest_transcript(url)
        
        if result.success and result.saved_path:
            print(f"      ✅ Found {len(result.transcripts)} transcripts")
            if result.latest_transcript:
                print(f"      📄 Latest: {result.latest_transcript.title}")
            print(f"      💾 Saved: {result.saved_path.name}")
            return (commission_key, result.saved_path, None)
        else:
            error = result.error or "Unknown error"
            print(f"      ❌ Failed: {error}")
            return (commission_key, None, error)
            
    except Exception as e:
        print(f"      ❌ Exception: {e}")
        return (commission_key, None, str(e))


async def run_pipeline(
    commission: str = DEFAULT_COMMISSION.lower(),
    skip_scrape: bool = False,
    pdf_path: str | None = None,
    use_ai: bool = True,
    all_commissions: bool = False,
) -> None:
    """
    Run the complete ReguSense pipeline.

    Args:
        commission: Commission name to scrape (default: from settings)
        skip_scrape: If True, skip scraping and use existing PDF
        pdf_path: Optional path to existing PDF (required if skip_scrape=True)
        use_ai: Whether to run AI verification with Gemini
        all_commissions: If True, scrape all commissions
    """
    print("\n" + "=" * 70)
    print("  ReguSense - Legislative Risk Intelligence Platform")
    print("=" * 70)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {'All Commissions' if all_commissions else f'{commission.upper()} Commission'}")
    print(f"  AI Analysis: {'Enabled' if use_ai else 'Disabled'}")
    print("=" * 70 + "\n")

    transcript_paths: list[Path] = []
    
    # Step 1: Scrape or use existing PDFs
    if skip_scrape:
        if pdf_path:
            transcript_paths = [Path(pdf_path)]
        else:
            # Find all existing PDFs
            pdfs = list(settings.raw_contracts_dir.glob("*.pdf"))
            if pdfs:
                # Use the most recent PDF(s)
                pdfs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                transcript_paths = pdfs[:1]  # Just the latest for single mode
                print(f"📄 Using existing PDF: {transcript_paths[0]}")
            else:
                print("❌ No PDFs found. Run without --skip-scrape first.")
                return
    else:
        print("🔍 STEP 1: Scraping Commission Transcripts")
        print("-" * 50)
        
        commissions_to_scrape = (
            get_all_commissions() if all_commissions 
            else [commission.upper()]
        )
        
        print(f"   Commissions: {len(commissions_to_scrape)}")
        
        async with CommissionScraper(headless=True) as scraper:
            for comm_key in commissions_to_scrape:
                comm_key, saved_path, error = await scrape_commission(comm_key, scraper)
                if saved_path:
                    transcript_paths.append(saved_path)
        
        if not transcript_paths:
            print("\n❌ No transcripts were successfully scraped.")
            return
        
        print(f"\n✅ Successfully scraped {len(transcript_paths)} commission(s)")

    # Process each transcript
    all_hits = []
    total_pages = 0
    
    for transcript_path in transcript_paths:
        # Step 2: Extract text from PDF
        print(f"\n📖 STEP 2: Extracting Text from PDF")
        print(f"   File: {transcript_path.name}")
        print("-" * 50)

        processor = PDFProcessor()

        try:
            pages = processor.extract_text(transcript_path)
            total_pages += len(pages)
            print(f"✅ Extracted {len(pages)} pages with content")

            # Show sample
            if pages:
                sample = pages[0].text[:200].replace("\n", " ")
                print(f"\n   Sample from page 1:\n   \"{sample}...\"")

        except Exception as e:
            print(f"❌ PDF processing failed: {e}")
            continue

        # Step 3: Keyword-based risk detection
        print("\n🔎 STEP 3: Keyword-Based Risk Detection")
        print("-" * 50)

        engine = RiskEngine()

        # Convert to dict format for the engine
        page_dicts = [{"page": p.page, "text": p.text} for p in pages]
        analysis = engine.analyze_text(page_dicts)
        
        # Add source info to hits
        for hit in analysis.hits:
            hit.source_file = transcript_path.name

        all_hits.extend(analysis.hits)

        # Print keyword results summary
        print(f"✅ Found {len(analysis.hits)} raw risk hits")
        for sector in Sector:
            sector_hits = analysis.get_hits_by_sector(sector)
            if sector_hits:
                pages_list = sorted(set(h.page_number for h in sector_hits))
                print(f"   {sector.value}: {len(sector_hits)} hits on pages {pages_list}")

    # Step 4: AI Verification (if enabled)
    report = None
    if use_ai and all_hits:
        print("\n🤖 STEP 4: AI Verification (Google Gemini)")
        print("-" * 50)

        # Check for API key
        api_key = os.environ.get("REGUSENSE_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("⚠️  Warning: GEMINI_API_KEY not set. Skipping AI verification.")
            print("   Set environment variable: export GEMINI_API_KEY='your-key'")
            use_ai = False
        else:
            try:
                from intelligence.gemini_analyzer import GeminiAnalyst
                
                analyst = GeminiAnalyst(api_key=api_key)
                print(f"   Analyzing {len(all_hits)} hits with Gemini...")
                print()
                
                # Run AI analysis
                report = analyst.analyze_hits(all_hits)
                
                # Print the verified report
                report.print_report()
                
                # Export JSON report
                json_report = report.to_json()
                report_path = settings.processed_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                report_path.write_text(json_report, encoding="utf-8")
                print(f"\n📄 JSON Report saved to: {report_path}")
                
                # Generate PDF report
                try:
                    from reporting.pdf_generator import ReportGenerator
                    
                    pdf_generator = ReportGenerator()
                    pdf_path = pdf_generator.generate_report(str(report_path))
                    print(f"📑 PDF Report saved to: {pdf_path}")
                except Exception as pdf_error:
                    print(f"⚠️  PDF generation failed: {pdf_error}")
                
                # Print JSON to console
                print("\n📋 VERIFIED INTELLIGENCE REPORT (JSON):")
                print("-" * 50)
                print(json_report)
                
            except ImportError as e:
                print(f"❌ Failed to import GeminiAnalyst: {e}")
                use_ai = False
            except Exception as e:
                print(f"❌ AI analysis failed: {e}")
                use_ai = False

    # Final Summary
    print("\n" + "=" * 70)
    print("  PIPELINE COMPLETE")
    print("=" * 70)
    print(f"  Transcripts processed: {len(transcript_paths)}")
    for path in transcript_paths:
        print(f"    - {path.name}")
    print(f"  Total pages analyzed: {total_pages}")
    print(f"  Total raw risk hits: {len(all_hits)}")
    if use_ai and report:
        print(f"  Genuine risks (AI verified): {len(report.genuine_risks)}")
        print(f"  Noise filtered: {report.noise_filtered}")
    sectors_found = set(h.sector.value for h in all_hits)
    print(f"  Sectors affected: {', '.join(sectors_found) or 'None'}")
    print("=" * 70 + "\n")


def main() -> None:
    """Entry point for the pipeline."""
    import argparse

    parser = argparse.ArgumentParser(
        description="ReguSense Legislative Risk Intelligence Pipeline"
    )
    parser.add_argument(
        "--commission",
        "-c",
        default=DEFAULT_COMMISSION.lower(),
        choices=[k.lower() for k in COMMISSION_SOURCES.keys()],
        help=f"Commission to scrape (default: {DEFAULT_COMMISSION.lower()})",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        dest="all_commissions",
        help="Scrape ALL commissions (overrides --commission)",
    )
    parser.add_argument(
        "--skip-scrape",
        "-s",
        action="store_true",
        help="Skip scraping, use existing PDF",
    )
    parser.add_argument(
        "--pdf",
        "-p",
        type=str,
        help="Path to existing PDF (use with --skip-scrape)",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="Skip AI verification with Gemini",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available commissions and exit",
    )

    args = parser.parse_args()
    
    # List commissions if requested
    if args.list:
        print("\n📋 Available Commissions:")
        print("-" * 50)
        for key, info in COMMISSION_SOURCES.items():
            print(f"\n  {key.lower()}")
            print(f"    Name: {info['name']}")
            print(f"    Sectors: {', '.join(info['sectors'])}")
            print(f"    Focus: {info['focus']}")
        print()
        return

    # Find latest PDF if skip-scrape but no path specified
    if args.skip_scrape and not args.pdf:
        pdfs = list(settings.raw_contracts_dir.glob("*.pdf"))
        if pdfs:
            # Use the most recent PDF
            args.pdf = str(max(pdfs, key=lambda p: p.stat().st_mtime))
            print(f"Using most recent PDF: {args.pdf}")
        else:
            print("No PDFs found in data directory. Run without --skip-scrape first.")
            return

    asyncio.run(run_pipeline(
        commission=args.commission,
        skip_scrape=args.skip_scrape,
        pdf_path=args.pdf,
        use_ai=not args.no_ai,
        all_commissions=args.all_commissions,
    ))


if __name__ == "__main__":
    main()
