"""
TÜİK TSG (Ticaret Sicil Gazetesi) Board Member Scraper.

Scrapes company board member and management data from TÜİK.
URL: https://tsg.tuik.gov.tr/

Features:
- MERSIS-based company lookup
- Board member extraction
- Rate limiting (15 req/min)

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
from datetime import datetime
from pathlib import Path
from typing import Optional

from scrapers.base import BaseScraper, RateLimiter, ProxyManager
from scrapers.models import BoardMember, ScrapeResult, SourceType
from core.logging import get_logger

logger = get_logger(__name__)


BASE_URL = "https://tsg.tuik.gov.tr"


class TuikScraper(BaseScraper):
    """
    TÜİK TSG scraper for company board member data.
    
    Extracts management structure from Ticaret Sicil Gazetesi.
    
    Example:
        async with TuikScraper() as scraper:
            members = await scraper.scrape_by_company("1234567890123456")
    """
    
    # Position keywords for classification
    POSITION_KEYWORDS = {
        "BAŞKAN": "Yönetim Kurulu Başkanı",
        "GENEL MÜDÜR": "Genel Müdür",
        "ÜYE": "Yönetim Kurulu Üyesi",
        "MURAKIP": "Denetim Kurulu Üyesi",
        "İMZA YETKİLİ": "İmza Yetkilisi",
    }
    
    def __init__(
        self,
        output_dir: str = "data/raw/tuik",
        rate_limit: Optional[RateLimiter] = None,
        proxy_manager: Optional[ProxyManager] = None,
        headless: bool = True,
    ):
        """
        Initialize TÜİK scraper.
        
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
    
    async def scrape_by_company(
        self,
        mersis_no: str,
    ) -> list[BoardMember]:
        """
        Get board members for a company by MERSIS number.
        
        Args:
            mersis_no: 16-digit MERSIS number
            
        Returns:
            List of BoardMember objects
        """
        results: list[BoardMember] = []
        
        async with self._create_page() as page:
            try:
                # Navigate to search page
                async def navigate():
                    await page.goto(BASE_URL, wait_until="networkidle")
                    return True
                
                await self._retry_with_backoff(navigate, "navigate to TÜİK")
                
                # Look for MERSIS search field
                mersis_input = await page.query_selector(
                    "#txtMersisNo, input[name*='mersis'], input[placeholder*='MERSIS']"
                )
                
                if mersis_input:
                    await mersis_input.fill(mersis_no)
                    
                    # Submit search
                    search_btn = await page.query_selector(
                        "#btnAra, button[type='submit'], input[type='submit']"
                    )
                    if search_btn:
                        await search_btn.click()
                        await page.wait_for_load_state("networkidle")
                    
                    # Parse results
                    results = await self._parse_board_members(page, mersis_no)
                else:
                    logger.warning("MERSIS search field not found")
                
            except Exception as e:
                logger.error(f"Failed to scrape TÜİK for {mersis_no}: {e}")
        
        return results
    
    async def scrape_by_name(
        self,
        company_name: str,
    ) -> list[BoardMember]:
        """
        Search for board members by company name.
        
        Args:
            company_name: Company name to search
            
        Returns:
            List of BoardMember objects
        """
        results: list[BoardMember] = []
        
        async with self._create_page() as page:
            try:
                await page.goto(BASE_URL, wait_until="networkidle")
                
                # Look for company name search field
                name_input = await page.query_selector(
                    "#txtSirketAdi, input[name*='unvan'], input[placeholder*='Şirket']"
                )
                
                if name_input:
                    await name_input.fill(company_name)
                    
                    search_btn = await page.query_selector(
                        "#btnAra, button[type='submit']"
                    )
                    if search_btn:
                        await search_btn.click()
                        await page.wait_for_load_state("networkidle")
                    
                    # Find MERSIS from results and then get board members
                    mersis = await self._extract_mersis_from_results(page)
                    if mersis:
                        results = await self._parse_board_members(page, mersis)
                else:
                    logger.warning("Company name search field not found")
                
            except Exception as e:
                logger.error(f"Failed to scrape TÜİK for {company_name}: {e}")
        
        return results
    
    async def scrape_multiple(
        self,
        mersis_numbers: list[str],
    ) -> ScrapeResult:
        """
        Scrape board members for multiple companies.
        
        Args:
            mersis_numbers: List of MERSIS numbers
            
        Returns:
            ScrapeResult with statistics
        """
        start_time = datetime.now()
        all_members: list[BoardMember] = []
        
        try:
            for i, mersis in enumerate(mersis_numbers):
                logger.info(f"Processing {i+1}/{len(mersis_numbers)}: {mersis}")
                
                members = await self.scrape_by_company(mersis)
                all_members.extend(members)
                
                await asyncio.sleep(2)  # Rate limit between companies
            
            # Save results
            if all_members:
                output_file = self.output_dir / f"tuik_board_{datetime.now().strftime('%Y%m%d')}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [m.model_dump() for m in all_members],
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ScrapeResult(
                success=True,
                items_found=len(all_members),
                items_saved=len(all_members),
                duration_seconds=duration,
                saved_path=str(self.output_dir),
            )
            
        except Exception as e:
            logger.exception("Failed to scrape TÜİK batch")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )
    
    async def _parse_board_members(
        self,
        page,
        mersis_no: str,
    ) -> list[BoardMember]:
        """Parse board member data from company page."""
        members: list[BoardMember] = []
        
        # Get company name from page
        company_name = ""
        name_elem = await page.query_selector(
            ".sirket-adi, .company-name, h1, .unvan"
        )
        if name_elem:
            company_name = (await name_elem.inner_text()).strip()
        
        # Find board member sections
        # Look for tables or lists with board member data
        member_rows = await page.query_selector_all(
            "table.yonetim tr, .board-members tr, .yonetim-kurulu li, "
            "[class*='member'], [class*='yonetici']"
        )
        
        for row in member_rows:
            try:
                text = (await row.inner_text()).strip()
                if not text or len(text) < 5:
                    continue
                
                # Try to extract name and position
                cells = await row.query_selector_all("td, span, div")
                
                member_name = ""
                position = ""
                start_date = None
                
                if len(cells) >= 2:
                    member_name = (await cells[0].inner_text()).strip()
                    position = (await cells[1].inner_text()).strip()
                    if len(cells) >= 3:
                        date_text = (await cells[2].inner_text()).strip()
                        start_date = self._parse_date(date_text)
                else:
                    # Try to parse from single text
                    parts = text.split("-")
                    if len(parts) >= 2:
                        member_name = parts[0].strip()
                        position = parts[1].strip()
                
                if member_name and position:
                    # Normalize position
                    position = self._normalize_position(position)
                    
                    members.append(BoardMember(
                        company_mersis=mersis_no,
                        company_name=company_name or "Unknown",
                        member_name=member_name,
                        position=position,
                        start_date=start_date,
                    ))
                    
            except Exception as e:
                logger.debug(f"Failed to parse member row: {e}")
                continue
        
        return members
    
    async def _extract_mersis_from_results(self, page) -> Optional[str]:
        """Extract MERSIS number from search results."""
        mersis_elem = await page.query_selector(
            "[data-mersis], .mersis-no, td:has-text('MERSIS')"
        )
        if mersis_elem:
            text = await mersis_elem.inner_text()
            # Extract 16-digit number
            match = re.search(r'\d{16}', text)
            if match:
                return match.group(0)
        return None
    
    def _normalize_position(self, position: str) -> str:
        """Normalize position title."""
        position_upper = position.upper()
        for key, normalized in self.POSITION_KEYWORDS.items():
            if key in position_upper:
                return normalized
        return position
    
    def _parse_date(self, date_text: str) -> Optional[str]:
        """Parse date string to YYYY-MM-DD format."""
        for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
            try:
                dt = datetime.strptime(date_text.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None


# =============================================================================
# CLI
# =============================================================================

async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="TÜİK TSG Board Member Scraper")
    parser.add_argument("--mersis", "-m", type=str, help="MERSIS number to lookup")
    parser.add_argument("--company", "-c", type=str, help="Company name to search")
    parser.add_argument("--output", "-o", default="data/raw/tuik")
    parser.add_argument("--headless", action="store_true", default=True)
    
    args = parser.parse_args()
    
    async with TuikScraper(output_dir=args.output, headless=args.headless) as scraper:
        if args.mersis:
            members = await scraper.scrape_by_company(args.mersis)
            print(f"\nFound {len(members)} board members")
            for m in members:
                print(f"  - {m.member_name}: {m.position}")
        elif args.company:
            members = await scraper.scrape_by_name(args.company)
            print(f"\nFound {len(members)} board members for {args.company}")
            for m in members:
                print(f"  - {m.member_name}: {m.position}")
        else:
            print("Please provide --mersis or --company argument")


if __name__ == "__main__":
    asyncio.run(main())
