"""
Modern Async TBMM Genel Kurul (General Assembly) Scraper.

Features:
- Playwright async for dynamic content
- Rate limiting
- User-agent rotation
- Proxy support
- Pydantic validation
- Async vector store ingestion

Author: ReguSense Team
"""

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from scrapers.base import BaseScraper, RateLimiter, UserAgentRotator, ProxyManager
from scrapers.models import ScrapedTranscript, ScrapeResult, SourceType
from core.logging import get_logger

logger = get_logger(__name__)


# URLs
BASE_URL = "https://www.tbmm.gov.tr"
CDN_URL = "https://cdn.tbmm.gov.tr"
DONEM_URL = f"{BASE_URL}/Tutanaklar/DoneminTutanakMetinleri?Donem={{donem}}&YasamaYili={{yasama_yili}}"


class GenelKurulScraper(BaseScraper):
    """
    Async Playwright-based scraper for TBMM General Assembly transcripts.
    
    Example:
        async with GenelKurulScraper() as scraper:
            result = await scraper.scrape_donem(28, yasama_yili=2)
    """
    
    TURKISH_MONTHS = {
        "ocak": "01", "şubat": "02", "mart": "03", "nisan": "04",
        "mayıs": "05", "haziran": "06", "temmuz": "07", "ağustos": "08",
        "eylül": "09", "ekim": "10", "kasım": "11", "aralık": "12",
    }
    
    def __init__(
        self,
        output_dir: str = "data/raw/genel_kurul",
        rate_limit: Optional[RateLimiter] = None,
        proxy_manager: Optional[ProxyManager] = None,
        headless: bool = True,
    ):
        """
        Initialize General Assembly scraper.
        
        Args:
            output_dir: Directory to save downloaded PDFs
            rate_limit: Custom rate limiter (default: 20 req/min)
            proxy_manager: Optional proxy manager
            headless: Run browser headless
        """
        super().__init__(
            headless=headless,
            rate_limit=rate_limit or RateLimiter(max_requests=20, time_window=60),
            proxy_manager=proxy_manager,
            max_retries=3,
            page_timeout_ms=60000,
        )
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _parse_date(self, text: str) -> str:
        """Parse Turkish date to YYYY-MM-DD format."""
        match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
        if match:
            day, month_name, year = match.groups()
            month = self.TURKISH_MONTHS.get(month_name.lower(), "01")
            return f"{year}-{month}-{day.zfill(2)}"
        return ""
    
    async def scrape_session_list(
        self,
        donem: int,
        yasama_yili: int,
    ) -> list[ScrapedTranscript]:
        """
        Get list of sessions for a specific term and year.
        
        Args:
            donem: Legislative term (e.g., 28)
            yasama_yili: Legislative year
            
        Returns:
            List of ScrapedTranscript objects
        """
        url = DONEM_URL.format(donem=donem, yasama_yili=yasama_yili)
        logger.info(f"Fetching sessions: Dönem {donem}, Year {yasama_yili}")
        
        transcripts = []
        
        async with self._create_page() as page:
            async def fetch_list():
                await page.goto(url, wait_until="networkidle")
                return await page.content()
            
            await self._retry_with_backoff(fetch_list, "fetch session list")
            
            # Find all transcript links
            links = await page.query_selector_all("a[href*='/Tutanaklar/Tutanak?Id=']")
            
            for link in links:
                try:
                    href = await link.get_attribute("href") or ""
                    title = await link.inner_text()
                    
                    # Extract birleşim number
                    birlesim = 0
                    birlesim_match = re.search(r"(\d+)\s*\.?\s*Birleşim", title, re.IGNORECASE)
                    if birlesim_match:
                        birlesim = int(birlesim_match.group(1))
                    
                    # Find date in parent row
                    date = ""
                    parent = await link.evaluate_handle("el => el.closest('tr')")
                    if parent:
                        row_text = await parent.inner_text()
                        date = self._parse_date(row_text)
                    
                    transcripts.append(ScrapedTranscript(
                        title=title.strip(),
                        date=date,
                        url=urljoin(BASE_URL, href),
                        donem=donem,
                        yasama_yili=yasama_yili,
                        birlesim=birlesim,
                        source_type=SourceType.TBMM_GENERAL_ASSEMBLY,
                    ))
                    
                except Exception as e:
                    logger.debug(f"Failed to parse link: {e}")
                    continue
        
        # Remove duplicates
        seen = set()
        unique = []
        for t in transcripts:
            if t.birlesim not in seen:
                seen.add(t.birlesim)
                unique.append(t)
        
        logger.info(f"Found {len(unique)} unique sessions")
        return unique
    
    async def get_pdf_url(self, transcript: ScrapedTranscript) -> Optional[str]:
        """
        Get direct PDF URL from transcript detail page.
        
        Args:
            transcript: Transcript to get PDF for
            
        Returns:
            PDF URL or None
        """
        async with self._create_page() as page:
            async def fetch_detail():
                await page.goto(transcript.url, wait_until="networkidle")
                return await page.content()
            
            await self._retry_with_backoff(fetch_detail, "fetch detail page")
            
            # Method 1: Look for embed
            embed = await page.query_selector("embed[src*='.pdf']")
            if embed:
                src = await embed.get_attribute("src")
                if src:
                    return src if src.startswith("http") else urljoin(CDN_URL, src)
            
            # Method 2: Look for iframe
            iframe = await page.query_selector("iframe[src*='.pdf']")
            if iframe:
                src = await iframe.get_attribute("src")
                if src:
                    return src if src.startswith("http") else urljoin(CDN_URL, src)
            
            # Method 3: Look for PDF links
            pdf_links = await page.query_selector_all("a[href*='.pdf']")
            for link in pdf_links:
                href = await link.get_attribute("href") or ""
                if "Tam" in href:  # Full transcript
                    return href if href.startswith("http") else urljoin(CDN_URL, href)
            
            return None
    
    async def download_pdf(self, transcript: ScrapedTranscript) -> Optional[Path]:
        """
        Download transcript PDF.
        
        Args:
            transcript: Transcript to download
            
        Returns:
            Path to downloaded file or None
        """
        if not transcript.pdf_url:
            transcript.pdf_url = await self.get_pdf_url(transcript) or ""
        
        if not transcript.pdf_url:
            logger.warning(f"No PDF URL for: {transcript.title}")
            return None
        
        # Generate filename
        filename = f"gk_d{transcript.donem}_y{transcript.yasama_yili}_b{transcript.birlesim:03d}"
        if transcript.date:
            filename += f"_{transcript.date}"
        filename += ".pdf"
        
        filepath = self.output_dir / filename
        
        # Skip if exists
        if filepath.exists() and filepath.stat().st_size > 10000:
            logger.debug(f"Already exists: {filename}")
            return filepath
        
        # Download via browser
        async with self._create_page() as page:
            async def download():
                response = await page.goto(transcript.pdf_url)
                if response and response.ok:
                    content = await response.body()
                    if content[:4] == b"%PDF":
                        with open(filepath, "wb") as f:
                            f.write(content)
                        return filepath
                return None
            
            try:
                result = await self._retry_with_backoff(download, "download PDF")
                if result:
                    size_kb = filepath.stat().st_size // 1024
                    logger.info(f"Downloaded: {filename} ({size_kb} KB)")
                    return result
            except Exception as e:
                logger.error(f"Download failed: {transcript.pdf_url} - {e}")
        
        return None
    
    async def scrape_donem(
        self,
        donem: int,
        yasama_yili: int = 1,
        max_sessions: int = 50,
        ingest_to_memory: bool = False,
    ) -> ScrapeResult:
        """
        Scrape all transcripts for a specific term and year.
        
        Args:
            donem: Legislative term
            yasama_yili: Legislative year
            max_sessions: Maximum sessions to download
            ingest_to_memory: Send to vector store (requires PDF parsing)
            
        Returns:
            ScrapeResult with statistics
        """
        start_time = datetime.now()
        
        try:
            transcripts = await self.scrape_session_list(donem, yasama_yili)
            transcripts = transcripts[:max_sessions]
            
            downloaded = 0
            for transcript in transcripts:
                await asyncio.sleep(1)  # Rate limit
                path = await self.download_pdf(transcript)
                if path:
                    downloaded += 1
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ScrapeResult(
                success=True,
                items_found=len(transcripts),
                items_saved=downloaded,
                duration_seconds=duration,
                saved_path=str(self.output_dir),
            )
            
        except Exception as e:
            logger.exception(f"Failed to scrape dönem {donem}")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )
    
    async def scrape(
        self,
        donem: int = 28,
        yasama_yili_start: int = 1,
        yasama_yili_end: int = 5,
        max_per_year: int = 50,
    ) -> ScrapeResult:
        """
        Scrape multiple years.
        
        Args:
            donem: Legislative term
            yasama_yili_start: Start year
            yasama_yili_end: End year
            max_per_year: Max sessions per year
            
        Returns:
            Aggregated ScrapeResult
        """
        total_found = 0
        total_saved = 0
        start_time = datetime.now()
        
        for yy in range(yasama_yili_start, yasama_yili_end + 1):
            result = await self.scrape_donem(donem, yy, max_per_year)
            total_found += result.items_found
            total_saved += result.items_saved
        
        duration = (datetime.now() - start_time).total_seconds()
        
        return ScrapeResult(
            success=True,
            items_found=total_found,
            items_saved=total_saved,
            duration_seconds=duration,
            saved_path=str(self.output_dir),
        )


# =============================================================================
# CLI
# =============================================================================

async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="TBMM Genel Kurul Scraper")
    parser.add_argument("--donem", "-d", type=int, default=28)
    parser.add_argument("--yasama-yili", "-y", type=int, default=None)
    parser.add_argument("--max-per-year", "-m", type=int, default=20)
    parser.add_argument("--output", "-o", default="data/raw/genel_kurul")
    
    args = parser.parse_args()
    
    async with GenelKurulScraper(output_dir=args.output) as scraper:
        if args.yasama_yili:
            result = await scraper.scrape_donem(
                args.donem,
                args.yasama_yili,
                args.max_per_year,
            )
        else:
            result = await scraper.scrape(
                donem=args.donem,
                max_per_year=args.max_per_year,
            )
        
        print(f"\n=== SONUÇ ===")
        print(f"Bulunan: {result.items_found}")
        print(f"İndirilen: {result.items_saved}")
        print(f"Süre: {result.duration_seconds:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
