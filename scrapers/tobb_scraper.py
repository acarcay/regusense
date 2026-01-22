"""
TOBB Ticaret Sicil Gazetesi Legal Updates Scraper.

Scrapes company registrations, name changes, and liquidations from TOBB.
URL: https://www.ticaretsicil.gov.tr/

Features:
- Playwright Stealth for anti-bot bypass
- Date range filtering
- Very conservative rate limiting (10 req/min)

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

from scrapers.base import BaseScraper, RateLimiter, ProxyManager
from scrapers.models import CompanyUpdate, ScrapeResult, SourceType
from core.logging import get_logger

logger = get_logger(__name__)


BASE_URL = "https://www.ticaretsicil.gov.tr"


class TobbScraper(BaseScraper):
    """
    TOBB Ticaret Sicil Gazetesi scraper for legal company updates.
    
    Scrapes company registrations, name changes, capital changes, liquidations.
    Uses Playwright Stealth to handle anti-bot measures.
    
    Example:
        async with TobbScraper() as scraper:
            updates = await scraper.scrape_latest(days=7)
    """
    
    # Update type patterns for classification
    UPDATE_PATTERNS = {
        "KURULUŞ": ["kuruluş", "tescil", "yeni şirket", "ana sözleşme"],
        "UNVAN DEĞİŞİKLİĞİ": ["unvan değişikliği", "isim değişikliği", "ticaret unvanı"],
        "TASFİYE": ["tasfiye", "fesih", "kapatma", "terkin"],
        "SERMAYE ARTIŞI": ["sermaye artırımı", "sermaye artışı", "capital increase"],
        "SERMAYE AZALIŞI": ["sermaye azaltımı", "sermaye azalışı"],
        "ADRES DEĞİŞİKLİĞİ": ["adres değişikliği", "merkez nakli"],
        "YÖNETİM DEĞİŞİKLİĞİ": ["yönetim kurulu", "müdür ataması", "temsil"],
        "BİRLEŞME": ["birleşme", "devir", "merger"],
    }
    
    def __init__(
        self,
        output_dir: str = "data/raw/tobb",
        rate_limit: Optional[RateLimiter] = None,
        proxy_manager: Optional[ProxyManager] = None,
        headless: bool = True,
    ):
        """
        Initialize TOBB scraper.
        
        Args:
            output_dir: Directory to save scraped data
            rate_limit: Custom rate limiter (default: 10 req/min - very conservative)
            proxy_manager: Optional proxy manager
            headless: Run browser headless
        """
        super().__init__(
            headless=headless,
            rate_limit=rate_limit or RateLimiter(max_requests=10, time_window=60),
            proxy_manager=proxy_manager,
            max_retries=5,  # More retries for anti-bot handling
            page_timeout_ms=90000,  # Longer timeout
        )
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def _start_browser(self) -> None:
        """Override to add stealth settings."""
        await super()._start_browser()
        
        # Apply stealth settings if available
        try:
            from playwright_stealth import stealth_async
            self._stealth_available = True
        except ImportError:
            self._stealth_available = False
            logger.warning("playwright-stealth not installed, using standard browser")
    
    async def _create_stealth_page(self):
        """Create a page with stealth settings applied."""
        page = await self._context.new_page()
        
        # Apply stealth if available
        if hasattr(self, '_stealth_available') and self._stealth_available:
            try:
                from playwright_stealth import stealth_async
                await stealth_async(page)
            except Exception as e:
                logger.debug(f"Failed to apply stealth: {e}")
        
        # Additional anti-detection measures
        await page.add_init_script("""
            // Overwrite navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Mock plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """)
        
        return page
    
    async def scrape_latest(
        self,
        days: int = 7,
    ) -> ScrapeResult:
        """
        Scrape recent company updates from Ticaret Sicil Gazetesi.
        
        Args:
            days: Number of days to look back
            
        Returns:
            ScrapeResult with statistics
        """
        start_time = datetime.now()
        all_updates: list[CompanyUpdate] = []
        
        try:
            page = await self._create_stealth_page()
            
            try:
                # Navigate with extra care
                await page.goto(BASE_URL, wait_until="domcontentloaded")
                await asyncio.sleep(3)  # Wait for JS to load
                
                # Check for CAPTCHA or blocking
                content = await page.content()
                if "captcha" in content.lower() or "robot" in content.lower():
                    logger.warning("CAPTCHA detected, may need manual intervention")
                    await page.close()
                    return ScrapeResult(
                        success=False,
                        error="CAPTCHA detected - requires manual intervention",
                        duration_seconds=(datetime.now() - start_time).total_seconds(),
                    )
                
                # Set date range
                end_date = datetime.now()
                start_date = end_date - timedelta(days=days)
                
                # Look for date inputs
                start_input = await page.query_selector(
                    "#txtBaslangicTarihi, input[name*='baslangic'], input[placeholder*='Başlangıç']"
                )
                end_input = await page.query_selector(
                    "#txtBitisTarihi, input[name*='bitis'], input[placeholder*='Bitiş']"
                )
                
                if start_input and end_input:
                    await start_input.fill(start_date.strftime("%d.%m.%Y"))
                    await end_input.fill(end_date.strftime("%d.%m.%Y"))
                
                # Submit search
                search_btn = await page.query_selector(
                    "#btnAra, button[type='submit'], .search-button"
                )
                if search_btn:
                    await search_btn.click()
                    await asyncio.sleep(5)  # Wait for results
                    await page.wait_for_load_state("networkidle")
                
                # Parse results pages
                page_num = 1
                max_pages = 5  # Conservative limit
                
                while page_num <= max_pages:
                    updates = await self._parse_gazette_entries(page)
                    all_updates.extend(updates)
                    
                    logger.info(f"Page {page_num}: Found {len(updates)} updates")
                    
                    # Check for next page
                    next_btn = await page.query_selector(
                        "a.next, .pagination a:has-text('>')"
                    )
                    if not next_btn:
                        break
                    
                    await next_btn.click()
                    await asyncio.sleep(3)  # Rate limit
                    page_num += 1
                
            finally:
                await page.close()
            
            # Save results
            if all_updates:
                output_file = self.output_dir / f"tobb_{datetime.now().strftime('%Y%m%d')}.json"
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [u.model_dump() for u in all_updates],
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            return ScrapeResult(
                success=True,
                items_found=len(all_updates),
                items_saved=len(all_updates),
                duration_seconds=duration,
                saved_path=str(self.output_dir),
            )
            
        except Exception as e:
            logger.exception("Failed to scrape TOBB")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )
    
    async def scrape_by_company(
        self,
        mersis_no: str,
    ) -> list[CompanyUpdate]:
        """
        Get legal updates for a specific company.
        
        Args:
            mersis_no: Company MERSIS number
            
        Returns:
            List of CompanyUpdate objects
        """
        updates: list[CompanyUpdate] = []
        
        page = await self._create_stealth_page()
        
        try:
            await page.goto(BASE_URL, wait_until="networkidle")
            await asyncio.sleep(2)
            
            # Look for MERSIS search field
            mersis_input = await page.query_selector(
                "#txtMersisNo, input[name*='mersis']"
            )
            
            if mersis_input:
                await mersis_input.fill(mersis_no)
                
                search_btn = await page.query_selector(
                    "#btnAra, button[type='submit']"
                )
                if search_btn:
                    await search_btn.click()
                    await asyncio.sleep(3)
                
                updates = await self._parse_gazette_entries(page)
            else:
                logger.warning("MERSIS search field not found on TOBB")
                
        except Exception as e:
            logger.error(f"Failed to scrape TOBB for {mersis_no}: {e}")
        finally:
            await page.close()
        
        return updates
    
    async def _parse_gazette_entries(
        self,
        page,
    ) -> list[CompanyUpdate]:
        """Parse gazette entries from results page."""
        updates: list[CompanyUpdate] = []
        
        # Find gazette entries
        entries = await page.query_selector_all(
            ".gazette-entry, .ilan-item, tr.result-row, .sicil-item"
        )
        
        # Fallback: get all table rows
        if not entries:
            entries = await page.query_selector_all("table tbody tr")
        
        for entry in entries:
            try:
                text = (await entry.inner_text()).strip()
                if not text or len(text) < 20:
                    continue
                
                # Extract company name
                company_name = ""
                company_elem = await entry.query_selector(
                    ".sirket-adi, .company-name, td:first-child"
                )
                if company_elem:
                    company_name = (await company_elem.inner_text()).strip()
                
                # Extract gazette info
                gazette_date = ""
                gazette_number = ""
                
                date_elem = await entry.query_selector(
                    ".tarih, .date, td:nth-child(2)"
                )
                if date_elem:
                    date_text = (await date_elem.inner_text()).strip()
                    gazette_date = self._parse_date(date_text)
                
                no_elem = await entry.query_selector(
                    ".sayi, .number, td:nth-child(3)"
                )
                if no_elem:
                    gazette_number = (await no_elem.inner_text()).strip()
                
                # Classify update type
                update_type = self._classify_update_type(text)
                
                # Extract MERSIS if available
                mersis = None
                match = re.search(r'\d{16}', text)
                if match:
                    mersis = match.group(0)
                
                # Extract capital if mentioned
                capital = None
                capital_match = re.search(r'(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*(?:TL|TRY)', text)
                if capital_match:
                    try:
                        capital_str = capital_match.group(1).replace('.', '').replace(',', '.')
                        capital = float(capital_str)
                    except ValueError:
                        pass
                
                if company_name:
                    updates.append(CompanyUpdate(
                        company_name=company_name,
                        mersis_no=mersis,
                        update_type=update_type,
                        gazette_date=gazette_date or datetime.now().strftime("%Y-%m-%d"),
                        gazette_number=gazette_number or "N/A",
                        summary=text[:500],  # First 500 chars as summary
                        capital=capital,
                    ))
                    
            except Exception as e:
                logger.debug(f"Failed to parse gazette entry: {e}")
                continue
        
        return updates
    
    def _classify_update_type(self, text: str) -> str:
        """Classify the type of legal update from text."""
        text_lower = text.lower()
        
        for update_type, keywords in self.UPDATE_PATTERNS.items():
            if any(kw in text_lower for kw in keywords):
                return update_type
        
        return "DİĞER"
    
    def _parse_date(self, date_text: str) -> str:
        """Parse date string to YYYY-MM-DD format."""
        for fmt in ["%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"]:
            try:
                dt = datetime.strptime(date_text.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return ""


# =============================================================================
# CLI
# =============================================================================

async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="TOBB Ticaret Sicil Scraper")
    parser.add_argument("--days", "-d", type=int, default=7)
    parser.add_argument("--mersis", "-m", type=str, help="Search by MERSIS")
    parser.add_argument("--output", "-o", default="data/raw/tobb")
    parser.add_argument("--no-headless", action="store_true", help="Run with visible browser")
    
    args = parser.parse_args()
    
    async with TobbScraper(
        output_dir=args.output,
        headless=not args.no_headless
    ) as scraper:
        if args.mersis:
            updates = await scraper.scrape_by_company(args.mersis)
            print(f"\nFound {len(updates)} updates for {args.mersis}")
            for u in updates:
                print(f"  - {u.gazette_date}: {u.update_type} - {u.company_name}")
        else:
            result = await scraper.scrape_latest(days=args.days)
            print(f"\n=== TOBB Scrape Complete ===")
            print(f"Success: {result.success}")
            print(f"Found: {result.items_found}")
            print(f"Duration: {result.duration_seconds:.1f}s")
            if result.error:
                print(f"Error: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
