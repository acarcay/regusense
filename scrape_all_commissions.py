"""
Bulk Historical Commission Scraper.

Scrapes TBMM (Turkish Parliament) transcripts from ALL commissions
going back a specified number of years.

Features:
- All commissions from COMMISSION_SOURCES
- Pagination support for historical data
- Date filtering (e.g., last 5 years)
- Resume capability (skips already downloaded PDFs)
- Rate limiting to avoid overloading TBMM servers

Usage:
    python scrape_all_commissions.py                    # Default: all commissions, 5 years
    python scrape_all_commissions.py --years 3          # Last 3 years
    python scrape_all_commissions.py --commission ADALET # Single commission
    python scrape_all_commissions.py --dry-run          # Preview without downloading

Author: ReguSense Team
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
import aiohttp

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import COMMISSION_SOURCES, settings

# Configure logging
settings.ensure_directories()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.logs_dir / "bulk_scraper.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class TranscriptInfo:
    """Represents a transcript entry."""
    title: str
    date: datetime
    url: str
    transcript_id: str
    commission: str = ""
    
    @property
    def filename(self) -> str:
        """Generate filename for the transcript."""
        date_str = self.date.strftime("%Y-%m-%d")
        safe_title = re.sub(r"[^\w\s-]", "", self.title[:50]).strip().replace(" ", "_")
        return f"{date_str}_{self.transcript_id}_{safe_title}.pdf"


@dataclass
class ScrapeStats:
    """Statistics for a scraping session."""
    commissions_processed: int = 0
    transcripts_found: int = 0
    transcripts_downloaded: int = 0
    transcripts_skipped: int = 0  # Already exists
    transcripts_failed: int = 0
    errors: list = field(default_factory=list)


class BulkCommissionScraper:
    """Bulk scraper for historical TBMM transcripts.
    
    Scrapes all commissions going back a specified number of years,
    with pagination support and resume capability.
    """
    
    DATE_PATTERN = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
    TRANSCRIPT_URL_PATTERN = re.compile(r"/Tutanaklar/TutanakGoster/(\d+)")
    
    def __init__(
        self,
        years_back: int = 5,
        headless: bool = True,
        rate_limit_seconds: float = 2.0,
    ):
        """
        Initialize the bulk scraper.
        
        Args:
            years_back: Number of years of history to scrape
            headless: Run browser in headless mode
            rate_limit_seconds: Delay between requests
        """
        self.years_back = years_back
        self.headless = headless
        self.rate_limit = rate_limit_seconds
        self.cutoff_date = datetime.now() - timedelta(days=years_back * 365)
        
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        
        logger.info(f"Initialized scraper: {years_back} years back (cutoff: {self.cutoff_date.date()})")
    
    async def __aenter__(self):
        await self._start_browser()
        return self
    
    async def __aexit__(self, *args):
        await self._close_browser()
    
    async def _start_browser(self):
        """Start Playwright browser."""
        logger.info("Starting browser...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            accept_downloads=True,
        )
    
    async def _close_browser(self):
        """Close browser."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")
    
    async def _create_page(self) -> Page:
        """Create a new page."""
        page = await self._context.new_page()
        page.set_default_timeout(30000)
        return page
    
    def _parse_date(self, text: str) -> Optional[datetime]:
        """Extract date from Turkish DD.MM.YYYY format."""
        match = self.DATE_PATTERN.search(text)
        if match:
            day, month, year = match.groups()
            try:
                return datetime(int(year), int(month), int(day))
            except ValueError:
                pass
        return None
    
    def _extract_id(self, url: str) -> Optional[str]:
        """Extract transcript ID from URL."""
        match = self.TRANSCRIPT_URL_PATTERN.search(url)
        return match.group(1) if match else None
    
    async def _extract_transcripts(
        self,
        page: Page,
        commission_key: str,
    ) -> list[TranscriptInfo]:
        """Extract all transcript links from a page."""
        transcripts = []
        
        links = await page.query_selector_all("a[href*='TutanakGoster']")
        logger.debug(f"Found {len(links)} transcript links")
        
        for link in links:
            try:
                href = await link.get_attribute("href")
                text = await link.inner_text()
                
                if not href or not text:
                    continue
                
                transcript_id = self._extract_id(href)
                date = self._parse_date(text)
                
                if transcript_id and date:
                    # Check if within date range
                    if date < self.cutoff_date:
                        continue
                    
                    full_url = href if href.startswith("http") else f"{settings.tbmm_base_url}{href}"
                    
                    transcripts.append(TranscriptInfo(
                        title=text.strip(),
                        date=date,
                        url=full_url,
                        transcript_id=transcript_id,
                        commission=commission_key,
                    ))
                    
            except Exception as e:
                logger.debug(f"Error parsing link: {e}")
        
        transcripts.sort(key=lambda t: t.date, reverse=True)
        return transcripts
    
    async def _check_has_pagination(self, page: Page) -> bool:
        """Check if page has pagination controls."""
        # Common pagination selectors
        pagination_selectors = [
            ".pagination",
            ".pager",
            "nav[aria-label='pagination']",
            "[class*='pagination']",
            "a[href*='page=']",
            "a[href*='sayfa=']",
            ".next",
            ".sonraki",
        ]
        
        for selector in pagination_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    return True
            except:
                pass
        
        return False
    
    async def _get_all_page_urls(self, page: Page, base_url: str) -> list[str]:
        """Get URLs for all pages in pagination."""
        urls = [base_url]
        
        # Try to find pagination links
        try:
            # Look for page number links
            page_links = await page.query_selector_all("a[href*='sayfa='], a[href*='page=']")
            
            for link in page_links:
                href = await link.get_attribute("href")
                if href:
                    full_url = href if href.startswith("http") else f"{settings.tbmm_base_url}{href}"
                    if full_url not in urls:
                        urls.append(full_url)
            
            # Also try clicking "next" buttons if pagination links don't work
            # This is a fallback for JS-based pagination
            
        except Exception as e:
            logger.debug(f"Pagination extraction failed: {e}")
        
        return urls
    
    async def _download_pdf(self, transcript: TranscriptInfo) -> Optional[Path]:
        """Download PDF directly via HTTP."""
        # Check if already exists
        save_path = settings.raw_contracts_dir / transcript.filename
        if save_path.exists():
            logger.debug(f"Already exists: {save_path.name}")
            return None  # Indicate skip
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/pdf,*/*",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    transcript.url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to download {transcript.transcript_id}: HTTP {response.status}")
                        return None
                    
                    content = await response.read()
                    
                    # Verify it's a PDF
                    if not content.startswith(b"%PDF"):
                        logger.warning(f"Not a PDF: {transcript.transcript_id}")
                        return None
                    
                    save_path.write_bytes(content)
                    logger.info(f"Downloaded: {save_path.name} ({len(content)} bytes)")
                    return save_path
                    
        except Exception as e:
            logger.error(f"Download failed for {transcript.transcript_id}: {e}")
            return None
    
    async def scrape_commission(
        self,
        commission_key: str,
        commission_url: str,
        dry_run: bool = False,
    ) -> tuple[list[TranscriptInfo], ScrapeStats]:
        """
        Scrape all transcripts from a commission.
        
        Args:
            commission_key: Commission identifier
            commission_url: URL to the commission page
            dry_run: If True, don't download
            
        Returns:
            Tuple of (transcripts, stats)
        """
        stats = ScrapeStats()
        all_transcripts = []
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Scraping: {COMMISSION_SOURCES.get(commission_key, {}).get('name', commission_key)}")
        logger.info(f"URL: {commission_url[:60]}...")
        logger.info(f"{'='*60}")
        
        try:
            page = await self._create_page()
            
            # Navigate to commission page
            await page.goto(commission_url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(2)
            
            # Extract transcripts from current page
            transcripts = await self._extract_transcripts(page, commission_key)
            logger.info(f"Found {len(transcripts)} transcripts on main page")
            
            # Check for pagination
            has_pagination = await self._check_has_pagination(page)
            if has_pagination:
                logger.info("Pagination detected - extracting additional pages...")
                page_urls = await self._get_all_page_urls(page, commission_url)
                logger.info(f"Found {len(page_urls)} pages")
                
                # Scrape additional pages
                for i, page_url in enumerate(page_urls[1:], 2):
                    try:
                        await asyncio.sleep(self.rate_limit)
                        await page.goto(page_url, wait_until="networkidle", timeout=60000)
                        await asyncio.sleep(1)
                        
                        page_transcripts = await self._extract_transcripts(page, commission_key)
                        logger.info(f"Page {i}: Found {len(page_transcripts)} transcripts")
                        transcripts.extend(page_transcripts)
                        
                    except Exception as e:
                        logger.warning(f"Failed to scrape page {i}: {e}")
            
            await page.close()
            
            # Deduplicate by transcript_id
            seen_ids = set()
            unique_transcripts = []
            for t in transcripts:
                if t.transcript_id not in seen_ids:
                    seen_ids.add(t.transcript_id)
                    unique_transcripts.append(t)
            
            transcripts = unique_transcripts
            all_transcripts = transcripts
            stats.transcripts_found = len(transcripts)
            
            logger.info(f"Total unique transcripts: {len(transcripts)}")
            
            # Download PDFs
            if not dry_run and transcripts:
                logger.info("Starting downloads...")
                
                for i, transcript in enumerate(transcripts, 1):
                    # Rate limiting
                    if i > 1:
                        await asyncio.sleep(self.rate_limit)
                    
                    # Check if already exists
                    save_path = settings.raw_contracts_dir / transcript.filename
                    if save_path.exists():
                        stats.transcripts_skipped += 1
                        continue
                    
                    result = await self._download_pdf(transcript)
                    if result:
                        stats.transcripts_downloaded += 1
                    else:
                        stats.transcripts_failed += 1
                    
                    # Progress update
                    if i % 10 == 0:
                        logger.info(f"Progress: {i}/{len(transcripts)}")
            
            stats.commissions_processed = 1
            
        except Exception as e:
            logger.error(f"Error scraping {commission_key}: {e}")
            stats.errors.append(str(e))
        
        return all_transcripts, stats
    
    async def scrape_all_commissions(
        self,
        commissions: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> ScrapeStats:
        """
        Scrape all commissions.
        
        Args:
            commissions: Optional list of commission keys to scrape (default: all)
            dry_run: If True, don't download
            
        Returns:
            Aggregated stats
        """
        total_stats = ScrapeStats()
        
        if commissions is None:
            commissions = list(COMMISSION_SOURCES.keys())
        
        logger.info(f"\n{'#'*60}")
        logger.info(f"Bulk Historical Scraper")
        logger.info(f"Commissions: {len(commissions)}")
        logger.info(f"Years back: {self.years_back}")
        logger.info(f"Cutoff date: {self.cutoff_date.date()}")
        logger.info(f"Dry run: {dry_run}")
        logger.info(f"{'#'*60}\n")
        
        all_transcripts = []
        
        for commission_key in commissions:
            commission_info = COMMISSION_SOURCES.get(commission_key)
            if not commission_info:
                logger.warning(f"Unknown commission: {commission_key}")
                continue
            
            commission_url = commission_info["url"]
            
            transcripts, stats = await self.scrape_commission(
                commission_key,
                commission_url,
                dry_run=dry_run,
            )
            
            all_transcripts.extend(transcripts)
            
            # Aggregate stats
            total_stats.commissions_processed += stats.commissions_processed
            total_stats.transcripts_found += stats.transcripts_found
            total_stats.transcripts_downloaded += stats.transcripts_downloaded
            total_stats.transcripts_skipped += stats.transcripts_skipped
            total_stats.transcripts_failed += stats.transcripts_failed
            total_stats.errors.extend(stats.errors)
        
        # Save manifest of all transcripts
        if all_transcripts:
            manifest_path = settings.processed_dir / "transcript_manifest.json"
            import json
            manifest = [
                {
                    "id": t.transcript_id,
                    "title": t.title,
                    "date": t.date.isoformat(),
                    "commission": t.commission,
                    "filename": t.filename,
                }
                for t in all_transcripts
            ]
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Saved manifest: {manifest_path}")
        
        return total_stats


def print_summary(stats: ScrapeStats):
    """Print summary of scraping session."""
    print("\n" + "=" * 60)
    print("  SCRAPING SUMMARY")
    print("=" * 60)
    print(f"  Commissions processed: {stats.commissions_processed}")
    print(f"  Transcripts found: {stats.transcripts_found}")
    print(f"  Transcripts downloaded: {stats.transcripts_downloaded}")
    print(f"  Transcripts skipped (existing): {stats.transcripts_skipped}")
    print(f"  Transcripts failed: {stats.transcripts_failed}")
    if stats.errors:
        print(f"  Errors: {len(stats.errors)}")
        for err in stats.errors[:5]:
            print(f"    - {err[:80]}")
    print("=" * 60 + "\n")


async def main():
    parser = argparse.ArgumentParser(
        description="Bulk scrape TBMM commission transcripts"
    )
    parser.add_argument(
        "--years", "-y",
        type=int,
        default=5,
        help="Number of years of history to scrape (default: 5)",
    )
    parser.add_argument(
        "--commission", "-c",
        type=str,
        help="Specific commission key to scrape (default: all)",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Preview without downloading",
    )
    parser.add_argument(
        "--list-commissions",
        action="store_true",
        help="List available commissions and exit",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=2.0,
        help="Seconds between requests (default: 2.0)",
    )
    
    args = parser.parse_args()
    
    if args.list_commissions:
        print("\n📋 Available Commissions:")
        print("-" * 50)
        for key, info in COMMISSION_SOURCES.items():
            print(f"\n  {key}")
            print(f"    Name: {info['name']}")
            print(f"    Sectors: {', '.join(info['sectors'])}")
        print()
        return
    
    # Determine commissions to scrape
    commissions = None
    if args.commission:
        if args.commission.upper() not in COMMISSION_SOURCES:
            print(f"❌ Unknown commission: {args.commission}")
            print("Use --list-commissions to see available options")
            return
        commissions = [args.commission.upper()]
    
    print("\n" + "#" * 60)
    print("  TBMM Bulk Historical Scraper")
    print("#" * 60)
    print(f"  Years: {args.years}")
    print(f"  Commissions: {len(commissions) if commissions else len(COMMISSION_SOURCES)}")
    print(f"  Mode: {'Dry Run' if args.dry_run else 'Full Download'}")
    print("#" * 60 + "\n")
    
    async with BulkCommissionScraper(
        years_back=args.years,
        rate_limit_seconds=args.rate_limit,
    ) as scraper:
        stats = await scraper.scrape_all_commissions(
            commissions=commissions,
            dry_run=args.dry_run,
        )
        
        print_summary(stats)


if __name__ == "__main__":
    asyncio.run(main())
