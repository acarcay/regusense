"""
Modern Async Resmi Gazete (Official Gazette) Scraper.

Features:
- Playwright async for dynamic content
- Rate limiting
- User-agent rotation
- Proxy support
- Pydantic validation
- Async vector store ingestion

Scrapes official announcements, laws, and regulations from:
https://www.resmigazete.gov.tr

Author: ReguSense Team
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from urllib.parse import urljoin

from scrapers.base import BaseScraper, RateLimiter, ProxyManager
from scrapers.models import ScrapedStatement, ScrapeResult, SourceType
from core.logging import get_logger

logger = get_logger(__name__)


BASE_URL = "https://www.resmigazete.gov.tr"


class ResmiGazeteScraper(BaseScraper):
    """
    Async Playwright-based scraper for Turkish Official Gazette.
    
    Scrapes laws, regulations, and official announcements.
    
    Example:
        async with ResmiGazeteScraper() as scraper:
            result = await scraper.scrape_latest(days=7)
    """
    
    def __init__(
        self,
        output_dir: str = "data/raw/resmi_gazete",
        rate_limit: Optional[RateLimiter] = None,
        proxy_manager: Optional[ProxyManager] = None,
        headless: bool = True,
    ):
        """
        Initialize Resmi Gazete scraper.
        
        Args:
            output_dir: Directory to save scraped data
            rate_limit: Custom rate limiter (default: 15 req/min)
            proxy_manager: Optional proxy manager
            headless: Run browser headless
        """
        super().__init__(
            headless=headless,
            rate_limit=rate_limit or RateLimiter(max_requests=15, time_window=60),
            proxy_manager=proxy_manager,
            max_retries=3,
            page_timeout_ms=60000,
        )
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def scrape_date(self, date: datetime) -> list[ScrapedStatement]:
        """
        Scrape official gazette for a specific date.
        
        Args:
            date: Date to scrape
            
        Returns:
            List of ScrapedStatement objects
        """
        date_str = date.strftime("%Y%m%d")
        url = f"{BASE_URL}/eskiler/{date.strftime('%Y/%m')}/{date_str}.htm"
        
        statements: list[ScrapedStatement] = []
        
        async with self._create_page() as page:
            try:
                async def fetch_page():
                    response = await page.goto(url, wait_until="networkidle")
                    if response and response.status == 404:
                        return None
                    return await page.content()
                
                content = await self._retry_with_backoff(fetch_page, f"fetch {date_str}")
                
                if not content:
                    logger.debug(f"No gazette for {date_str}")
                    return []
                
                # Find law/regulation sections
                sections = await page.query_selector_all(".content-text, .mevzuat, .icerik")
                
                for section in sections:
                    try:
                        text = await section.inner_text()
                        text = text.strip()
                        
                        if len(text) < 100:
                            continue
                        
                        # Try to extract title
                        title = ""
                        h_elem = await section.query_selector("h1, h2, h3, .baslik")
                        if h_elem:
                            title = await h_elem.inner_text()
                        
                        statements.append(ScrapedStatement(
                            text=text[:10000],  # Limit length
                            topic=title.strip() if title else "Resmi Gazete",
                            date=date.strftime("%Y-%m-%d"),
                            source=url,
                            source_type=SourceType.RESMI_GAZETE,
                        ))
                        
                    except Exception as e:
                        logger.debug(f"Failed to parse section: {e}")
                        continue
                
                # Alternative: Get all main content
                if not statements:
                    main_content = await page.query_selector("#main, .main-content, body")
                    if main_content:
                        text = await main_content.inner_text()
                        if len(text) > 500:
                            statements.append(ScrapedStatement(
                                text=text[:20000],
                                topic="Resmi Gazete",
                                date=date.strftime("%Y-%m-%d"),
                                source=url,
                                source_type=SourceType.RESMI_GAZETE,
                            ))
                
            except Exception as e:
                logger.warning(f"Failed to scrape {date_str}: {e}")
        
        return statements
    
    async def scrape_latest(
        self,
        days: int = 7,
        ingest_to_memory: bool = True,
    ) -> ScrapeResult:
        """
        Scrape official gazette for the last N days.
        
        Args:
            days: Number of days to look back
            ingest_to_memory: Send to vector store
            
        Returns:
            ScrapeResult with statistics
        """
        start_time = datetime.now()
        all_statements: list[ScrapedStatement] = []
        
        try:
            for i in range(days):
                date = datetime.now() - timedelta(days=i)
                
                # Skip weekends (no gazette published)
                if date.weekday() >= 5:
                    continue
                
                statements = await self.scrape_date(date)
                all_statements.extend(statements)
                
                logger.info(f"Scraped {date.strftime('%Y-%m-%d')}: {len(statements)} items")
                await asyncio.sleep(1)  # Rate limit
            
            # Save to JSON
            if all_statements:
                output_file = self.output_dir / f"resmi_gazete_{datetime.now().strftime('%Y%m%d')}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [s.model_dump() for s in all_statements],
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            
            # Ingest to vector store
            ingested = 0
            if ingest_to_memory and all_statements:
                ingested = await self._ingest_statements(all_statements)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ScrapeResult(
                success=True,
                items_found=len(all_statements),
                items_saved=len(all_statements),
                items_ingested=ingested,
                duration_seconds=duration,
                saved_path=str(self.output_dir),
            )
            
        except Exception as e:
            logger.exception("Failed to scrape Resmi Gazete")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )
    
    async def _ingest_statements(self, statements: list[ScrapedStatement]) -> int:
        """Ingest statements to vector store."""
        try:
            from core.deps import get_memory
            
            memory = get_memory()
            dicts = [s.to_ingest_dict() for s in statements]
            
            ids = memory.ingest_batch(dicts)
            return len(ids)
            
        except Exception as e:
            logger.error(f"Failed to ingest: {e}")
            return 0
    
    async def scrape(self, days: int = 7) -> ScrapeResult:
        """Main scrape method."""
        return await self.scrape_latest(days)


# =============================================================================
# CLI
# =============================================================================

async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Resmi Gazete Scraper")
    parser.add_argument("--days", "-d", type=int, default=7)
    parser.add_argument("--output", "-o", default="data/raw/resmi_gazete")
    parser.add_argument("--no-ingest", action="store_true")
    
    args = parser.parse_args()
    
    async with ResmiGazeteScraper(output_dir=args.output) as scraper:
        result = await scraper.scrape_latest(
            days=args.days,
            ingest_to_memory=not args.no_ingest,
        )
        
        print(f"\n=== SONUÇ ===")
        print(f"Bulunan: {result.items_found}")
        print(f"Kaydedilen: {result.items_saved}")
        print(f"Ingested: {result.items_ingested}")
        print(f"Süre: {result.duration_seconds:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
