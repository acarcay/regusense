"""
EKAP (KİK) Tender Intelligence Scraper.

Scrapes completed tender results from the Turkish Public Procurement Authority.
URL: https://ekap.kik.gov.tr/EKAP/Ortak/IhaleArama/index.html

Features:
- Async Playwright-based scraping
- Form-based search by company or date
- Rate limiting (20 req/min)
- Pydantic validation

Author: ReguSense Team
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from scrapers.base import BaseScraper, RateLimiter, ProxyManager
from scrapers.models import TenderResult, ScrapeResult, SourceType
from core.logging import get_logger

logger = get_logger(__name__)


BASE_URL = "https://ekap.kik.gov.tr"
SEARCH_URL = f"{BASE_URL}/EKAP/Ortak/IhaleArama/index.html"


class EkapScraper(BaseScraper):
    """
    EKAP tender result scraper for KİK (Kamu İhale Kurumu).
    
    Scrapes completed government tender results.
    
    Example:
        async with EkapScraper() as scraper:
            tenders = await scraper.scrape_latest(days=30)
    """
    
    # Sector codes for filtering
    SECTOR_CODES = {
        "CONSTRUCTION": "45",  # İnşaat
        "ENERGY": "65",        # Enerji
        "IT": "72",            # Bilişim
    }
    
    def __init__(
        self,
        output_dir: str = "data/raw/ekap",
        rate_limit: Optional[RateLimiter] = None,
        proxy_manager: Optional[ProxyManager] = None,
        headless: bool = True,
    ):
        """
        Initialize EKAP scraper.
        
        Args:
            output_dir: Directory to save scraped data
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
    
    async def scrape_by_company(
        self,
        company_name: str,
        mersis_no: Optional[str] = None,
    ) -> list[TenderResult]:
        """
        Search for tenders won by a specific company.
        
        Args:
            company_name: Company name to search
            mersis_no: Optional MERSIS number for more precise matching
            
        Returns:
            List of TenderResult objects
        """
        results: list[TenderResult] = []
        
        async with self._create_page() as page:
            try:
                # Navigate to search page
                async def navigate():
                    await page.goto(SEARCH_URL, wait_until="networkidle")
                    return True
                
                await self._retry_with_backoff(navigate, "navigate to EKAP")
                
                # Wait for form to load
                await page.wait_for_selector("#txtYuklenici", timeout=10000)
                
                # Fill contractor field
                await page.fill("#txtYuklenici", company_name)
                
                # Select "Sonuçlanmış" (Completed) status
                status_select = await page.query_selector("#ddlIhaleDurumu")
                if status_select:
                    await status_select.select_option(value="3")  # Completed
                
                # Submit search
                search_btn = await page.query_selector("#btnAra, button[type='submit']")
                if search_btn:
                    await search_btn.click()
                    await page.wait_for_load_state("networkidle")
                
                # Parse results
                results = await self._parse_search_results(page, mersis_no)
                
            except Exception as e:
                logger.error(f"Failed to scrape EKAP for {company_name}: {e}")
        
        return results
    
    async def scrape_by_ikn(self, ikn: str) -> Optional[TenderResult]:
        """
        Get specific tender details by İKN (İhale Kayıt Numarası).
        
        Args:
            ikn: Tender registration number
            
        Returns:
            TenderResult or None if not found
        """
        async with self._create_page() as page:
            try:
                await page.goto(SEARCH_URL, wait_until="networkidle")
                await page.wait_for_selector("#txtIhaleKayitNumarasi", timeout=10000)
                
                # Fill IKN field
                await page.fill("#txtIhaleKayitNumarasi", ikn)
                
                # Submit
                search_btn = await page.query_selector("#btnAra, button[type='submit']")
                if search_btn:
                    await search_btn.click()
                    await page.wait_for_load_state("networkidle")
                
                # Parse single result
                results = await self._parse_search_results(page)
                return results[0] if results else None
                
            except Exception as e:
                logger.error(f"Failed to scrape IKN {ikn}: {e}")
                return None
    
    async def scrape_latest(
        self,
        days: int = 30,
        sectors: Optional[list[str]] = None,
    ) -> ScrapeResult:
        """
        Scrape recent completed tenders.
        
        Args:
            days: Number of days to look back
            sectors: List of sector codes to filter (default: CONSTRUCTION)
            
        Returns:
            ScrapeResult with statistics
        """
        start_time = datetime.now()
        sectors = sectors or ["CONSTRUCTION"]
        all_results: list[TenderResult] = []
        
        try:
            async with self._create_page() as page:
                # Navigate to search page
                await page.goto(SEARCH_URL, wait_until="networkidle")
                await page.wait_for_selector("#txtBaslangicTarihi", timeout=15000)
                
                # Set date range
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
                
                await page.fill("#txtBaslangicTarihi", start_date.strftime("%d.%m.%Y"))
                await page.fill("#txtBitisTarihi", end_date.strftime("%d.%m.%Y"))
                
                # Select completed status
                status_select = await page.query_selector("#ddlIhaleDurumu")
                if status_select:
                    await status_select.select_option(value="3")
                
                # Select sector if available
                for sector in sectors:
                    sector_code = self.SECTOR_CODES.get(sector)
                    if sector_code:
                        sector_select = await page.query_selector("#ddlSektorKodu")
                        if sector_select:
                            await sector_select.select_option(value=sector_code)
                
                # Submit search
                search_btn = await page.query_selector("#btnAra, button[type='submit']")
                if search_btn:
                    await search_btn.click()
                    await page.wait_for_load_state("networkidle")
                
                # Parse all pages
                page_num = 1
                while True:
                    results = await self._parse_search_results(page)
                    all_results.extend(results)
                    
                    logger.info(f"Page {page_num}: Found {len(results)} tenders")
                    
                    # Check for next page
                    next_btn = await page.query_selector("a.next, .pagination .next:not(.disabled)")
                    if not next_btn:
                        break
                    
                    await next_btn.click()
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(1)  # Rate limit
                    page_num += 1
                    
                    if page_num > 10:  # Safety limit
                        break
            
            # Save results
            if all_results:
                output_file = self.output_dir / f"ekap_{datetime.now().strftime('%Y%m%d')}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [r.model_dump() for r in all_results],
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ScrapeResult(
                success=True,
                items_found=len(all_results),
                items_saved=len(all_results),
                duration_seconds=duration,
                saved_path=str(self.output_dir),
            )
            
        except Exception as e:
            logger.exception("Failed to scrape EKAP")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )
    
    async def _parse_search_results(
        self,
        page,
        filter_mersis: Optional[str] = None,
    ) -> list[TenderResult]:
        """Parse tender results from search page."""
        results: list[TenderResult] = []
        
        # Find result table
        rows = await page.query_selector_all(
            "#gvIhaleSonuclari tr, .ihale-sonuc-table tr, table.results tbody tr"
        )
        
        for row in rows:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 5:
                    continue
                
                # Extract data (column order varies, this is approximate)
                ikn = await cells[0].inner_text()
                ikn = ikn.strip()
                
                if not ikn or ikn.startswith("İ"):  # Skip header-like rows
                    continue
                
                title = await cells[1].inner_text() if len(cells) > 1 else ""
                winner = await cells[3].inner_text() if len(cells) > 3 else ""
                amount_text = await cells[4].inner_text() if len(cells) > 4 else "0"
                date_text = await cells[2].inner_text() if len(cells) > 2 else ""
                
                # Parse amount
                amount = 0.0
                try:
                    amount_clean = re.sub(r'[^\d,.]', '', amount_text)
                    amount_clean = amount_clean.replace('.', '').replace(',', '.')
                    amount = float(amount_clean) if amount_clean else 0.0
                except ValueError:
                    pass
                
                # Parse date
                tender_date = ""
                try:
                    for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
                        try:
                            dt = datetime.strptime(date_text.strip(), fmt)
                            tender_date = dt.strftime("%Y-%m-%d")
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass
                
                # Get detail link
                link = await row.query_selector("a")
                source_url = ""
                if link:
                    href = await link.get_attribute("href")
                    source_url = urljoin(BASE_URL, href) if href else ""
                
                result = TenderResult(
                    ikn=ikn,
                    title=title.strip(),
                    winner_company=winner.strip(),
                    winner_mersis=None,  # Would need detail page
                    bid_amount=amount,
                    tender_date=tender_date or datetime.now().strftime("%Y-%m-%d"),
                    source_url=source_url or SEARCH_URL,
                )
                
                # Filter by MERSIS if provided
                if filter_mersis:
                    # Would need to check detail page for MERSIS match
                    pass
                
                results.append(result)
                
            except Exception as e:
                logger.debug(f"Failed to parse row: {e}")
                continue
        
        return results
    
    async def scrape(self, days: int = 30) -> ScrapeResult:
        """Main scrape method."""
        return await self.scrape_latest(days)


# =============================================================================
# CLI
# =============================================================================

async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="EKAP Tender Scraper")
    parser.add_argument("--days", "-d", type=int, default=30)
    parser.add_argument("--company", "-c", type=str, help="Search by company name")
    parser.add_argument("--ikn", type=str, help="Search by IKN")
    parser.add_argument("--output", "-o", default="data/raw/ekap")
    parser.add_argument("--headless", action="store_true", default=True)
    
    args = parser.parse_args()
    
    async with EkapScraper(output_dir=args.output, headless=args.headless) as scraper:
        if args.ikn:
            result = await scraper.scrape_by_ikn(args.ikn)
            if result:
                print(f"Found: {result.title} - {result.winner_company} - {result.bid_amount}")
            else:
                print("Not found")
        elif args.company:
            results = await scraper.scrape_by_company(args.company)
            print(f"Found {len(results)} tenders for {args.company}")
            for r in results[:5]:
                print(f"  - {r.ikn}: {r.bid_amount:,.0f} TRY")
        else:
            result = await scraper.scrape_latest(days=args.days)
            print(f"\n=== EKAP Scrape Complete ===")
            print(f"Found: {result.items_found}")
            print(f"Duration: {result.duration_seconds:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
