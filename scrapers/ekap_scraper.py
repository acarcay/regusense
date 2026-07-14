"""
EKAP (KİK) Tender Intelligence Scraper - STEALTH MODE.

Scrapes completed tender results from the Turkish Public Procurement Authority.
URL: https://ekap.kik.gov.tr/EKAP/Ortak/IhaleArama/index.html

Features:
- Async Playwright-based scraping with STEALTH mode
- Human emulation (random delays, curved mouse movements)
- Error recovery with block type diagnosis (CAPTCHA/WAF)
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
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Literal
from urllib.parse import urljoin
from enum import Enum
from sqlalchemy.exc import IntegrityError

from database.postgres_client import get_session
from database.models import RawDocument, DocumentType

import numpy as np
try:
    import bezier
    BEZIER_AVAILABLE = True
except ImportError:
    BEZIER_AVAILABLE = False

try:
    from playwright_stealth import Stealth
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

from scrapers.base import BaseScraper, RateLimiter, ProxyManager, UserAgentRotator
from scrapers.models import TenderResult, ScrapeResult, SourceType
from core.logging import get_logger

logger = get_logger(__name__)


BASE_URL = "https://ekapv2.kik.gov.tr"
SEARCH_URL = f"{BASE_URL}/ekap/search"
SCREENSHOT_DIR = Path("data/raw/ekap/screenshots")



# =============================================================================
# Block Type Detection
# =============================================================================

class BlockType(str, Enum):
    """Type of blocking mechanism detected."""
    CAPTCHA = "CAPTCHA"
    WAF = "WAF"  # Web Application Firewall
    IP_BLOCK = "IP_BLOCK"
    RATE_LIMIT = "RATE_LIMIT"
    UNKNOWN = "UNKNOWN"


# =============================================================================
# Human Emulation Utilities
# =============================================================================

async def human_delay(min_sec: float = 1.0, max_sec: float = 4.0) -> float:
    """
    Simulate human "thinking" time with random delay.
    
    Returns:
        Actual delay time in seconds
    """
    delay = random.uniform(min_sec, max_sec)
    logger.debug(f"Human delay: {delay:.2f}s")
    await asyncio.sleep(delay)
    return delay


async def human_mouse_move(page, target_x: int, target_y: int, steps: int = 25) -> None:
    """
    Move mouse in a curved (bezier) path to simulate human movement.
    
    Args:
        page: Playwright Page object
        target_x: Target X coordinate
        target_y: Target Y coordinate
        steps: Number of intermediate steps
    """
    if not BEZIER_AVAILABLE:
        # Fallback: direct move
        await page.mouse.move(target_x, target_y)
        return
    
    try:
        # Get current mouse position (approximated from viewport center if unknown)
        viewport = page.viewport_size or {"width": 1920, "height": 1080}
        start_x = viewport["width"] // 2 + random.randint(-100, 100)
        start_y = viewport["height"] // 2 + random.randint(-100, 100)
        
        # Create bezier curve control points
        # Control point adds natural curve to movement
        ctrl_x = (start_x + target_x) // 2 + random.randint(-50, 50)
        ctrl_y = (start_y + target_y) // 2 + random.randint(-100, 100)
        
        # Define bezier curve nodes
        nodes = np.asfortranarray([
            [start_x, ctrl_x, target_x],
            [start_y, ctrl_y, target_y],
        ])
        curve = bezier.Curve(nodes, degree=2)
        
        # Move along the curve
        for i in range(steps + 1):
            t = i / steps
            point = curve.evaluate(t)
            x, y = int(point[0][0]), int(point[1][0])
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.01, 0.03))
        
        logger.debug(f"Mouse move completed: ({start_x},{start_y}) → ({target_x},{target_y})")
        
    except Exception as e:
        logger.warning(f"Bezier mouse move failed, using direct: {e}")
        await page.mouse.move(target_x, target_y)


async def diagnose_block(page) -> BlockType:
    """
    Analyze page content to determine type of blocking mechanism.
    
    Returns:
        BlockType enum indicating the detected block type
    """
    try:
        content = await page.content()
        content_lower = content.lower()
        
        # CAPTCHA indicators
        captcha_indicators = [
            "captcha", "recaptcha", "hcaptcha", "güvenlik doğrulaması",
            "robot değilim", "i'm not a robot", "doğrulama kodu"
        ]
        if any(indicator in content_lower for indicator in captcha_indicators):
            return BlockType.CAPTCHA
        
        # WAF indicators (Cloudflare, Incapsula, etc.)
        waf_indicators = [
            "cloudflare", "incapsula", "blocked", "access denied",
            "erişim engellendi", "web application firewall", "ddos protection"
        ]
        if any(indicator in content_lower for indicator in waf_indicators):
            return BlockType.WAF
        
        # Rate limit indicators
        rate_indicators = [
            "too many requests", "rate limit", "çok fazla istek",
            "429", "lütfen bekleyin", "please wait"
        ]
        if any(indicator in content_lower for indicator in rate_indicators):
            return BlockType.RATE_LIMIT
        
        # IP block indicators
        ip_indicators = [
            "ip address", "ip adresi", "banned", "yasaklandı",
            "permanently blocked", "kalıcı olarak engellendi"
        ]
        if any(indicator in content_lower for indicator in ip_indicators):
            return BlockType.IP_BLOCK
        
        return BlockType.UNKNOWN
        
    except Exception as e:
        logger.error(f"Block diagnosis failed: {e}")
        return BlockType.UNKNOWN


async def save_error_screenshot(page, error_type: str) -> Optional[Path]:
    """
    Save screenshot for debugging blocked/errored pages.
    
    Args:
        page: Playwright Page object
        error_type: Type of error (for filename)
        
    Returns:
        Path to saved screenshot or None
    """
    try:
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = SCREENSHOT_DIR / f"{error_type}_{timestamp}.png"
        await page.screenshot(path=str(filename), full_page=True)
        logger.info(f"Error screenshot saved: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Failed to save screenshot: {e}")
        return None




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
                # Apply stealth mode if available
                if STEALTH_AVAILABLE:
                    await Stealth().apply_stealth_async(page)
                    logger.info("🥷 Stealth mode activated")
                
                # Human emulation: initial delay before navigation
                await human_delay(1.0, 2.5)
                
                # Navigate to search page
                async def navigate():
                    await page.goto(SEARCH_URL, wait_until="networkidle")
                    return True
                
                await self._retry_with_backoff(navigate, "navigate to EKAP")
                
                # Human delay after page load
                await human_delay(1.5, 3.0)
                
                # Wait for form to load
                await page.wait_for_selector("#txtYuklenici", timeout=10000)
                
                # Human emulation: move to input field before typing
                input_element = await page.query_selector("#txtYuklenici")
                if input_element:
                    box = await input_element.bounding_box()
                    if box:
                        await human_mouse_move(page, int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2))
                        await human_delay(0.3, 0.8)
                
                # Fill contractor field with human-like typing delay
                await page.fill("#txtYuklenici", company_name)
                await human_delay(0.5, 1.0)
                
                # Select "Sonuçlanmış" (Completed) status
                status_select = await page.query_selector("#ddlIhaleDurumu")
                if status_select:
                    await status_select.select_option(value="3")  # Completed
                    await human_delay(0.3, 0.7)
                
                # Human emulation: move to search button
                search_btn = await page.query_selector("#btnAra, button[type='submit']")
                if search_btn:
                    box = await search_btn.bounding_box()
                    if box:
                        await human_mouse_move(page, int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2))
                        await human_delay(0.2, 0.5)
                    await search_btn.click()
                    await page.wait_for_load_state("networkidle")
                
                # Human delay after results load
                await human_delay(1.0, 2.0)
                
                # Parse results
                results = await self._parse_search_results(page, mersis_no)
                logger.info(f"✅ Found {len(results)} tenders for {company_name}")
                
            except TimeoutError as e:
                # Error recovery: diagnose block type and save screenshot
                logger.error(f"Timeout scraping EKAP for {company_name}: {e}")
                block_type = await diagnose_block(page)
                logger.warning(f"🚫 Block type detected: {block_type.value}")
                await save_error_screenshot(page, f"timeout_{block_type.value.lower()}")
                
            except Exception as e:
                logger.error(f"Failed to scrape EKAP for {company_name}: {e}")
                await save_error_screenshot(page, "error")
        
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
                # Apply stealth mode
                if STEALTH_AVAILABLE:
                    await Stealth().apply_stealth_async(page)
                
                await human_delay(1.0, 2.0)
                await page.goto(SEARCH_URL, wait_until="networkidle")
                await human_delay(1.0, 2.5)
                await page.wait_for_selector("#txtIhaleKayitNumarasi", timeout=10000)
                
                # Fill IKN field with human emulation
                await page.fill("#txtIhaleKayitNumarasi", ikn)
                await human_delay(0.5, 1.0)
                
                # Submit with mouse movement
                search_btn = await page.query_selector("#btnAra, button[type='submit']")
                if search_btn:
                    box = await search_btn.bounding_box()
                    if box:
                        await human_mouse_move(page, int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2))
                        await human_delay(0.2, 0.5)
                    await search_btn.click()
                    await page.wait_for_load_state("networkidle")
                
                await human_delay(1.0, 2.0)
                
                # Parse single result
                results = await self._parse_search_results(page)
                logger.info(f"✅ Found tender for IKN {ikn}" if results else f"❌ No tender for IKN {ikn}")
                return results[0] if results else None
                
            except TimeoutError as e:
                logger.error(f"Timeout scraping IKN {ikn}: {e}")
                block_type = await diagnose_block(page)
                logger.warning(f"🚫 Block type: {block_type.value}")
                await save_error_screenshot(page, f"ikn_timeout_{block_type.value.lower()}")
                return None
                
            except Exception as e:
                logger.error(f"Failed to scrape IKN {ikn}: {e}")
                await save_error_screenshot(page, "ikn_error")
                return None
    
    async def scrape_latest(
        self,
        days: int = 30,
        sectors: Optional[list[str]] = None,
    ) -> ScrapeResult:
        """
        Scrape recent tenders from EKAP v2.

        EKAP v2 structure (confirmed via screenshot):
          - Left sidebar: Alım Türü buttons (Mal/Yapım/Hizmet/Danışmanlık)
          - İhale Tarihi: 'Tarih Aralığı' radio reveals date pickers
          - 'Filtrele' button applies filters
          - Right panel: lazy-loaded result cards

        Args:
            days: Number of days to look back
            sectors: ['CONSTRUCTION'] → Yapım, ['GOODS'] → Mal, etc.
        """
        SECTOR_BTN = {
            "GOODS":        "filter-button-1",
            "CONSTRUCTION": "filter-button-2",
            "SERVICES":     "filter-button-3",
            "CONSULTANCY":  "filter-button-4",
        }

        start_time = datetime.now()
        sectors = sectors or ["CONSTRUCTION"]
        all_results: list[TenderResult] = []

        try:
            async with self._create_page() as page:
                if STEALTH_AVAILABLE:
                    await Stealth().apply_stealth_async(page)
                    logger.info("🥷 Stealth mode activated")

                # ── Load page ────────────────────────────────────────────────
                await human_delay(1.0, 2.0)
                await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                await human_delay(3.0, 5.0)  # wait for JS widgets to render

                # ── Select Alım Türü (deselect all first via Tümünü Temizle) ─
                try:
                    clear = page.locator("button#clear-button")
                    await clear.click(timeout=5000)
                    await human_delay(0.5, 1.0)
                except Exception:
                    pass  # might not be visible

                for sector in sectors:
                    btn_id = SECTOR_BTN.get(sector)
                    if btn_id:
                        try:
                            btn = page.locator(f"button#{btn_id}")
                            await btn.click(timeout=5000)
                            await human_delay(0.3, 0.7)
                            logger.info(f"Sector selected: {sector}")
                        except Exception:
                            logger.warning(f"Could not select sector: {sector}")

                # ── Set İhale Tarihi (Bypass complex DevExtreme logic) ──────
                # Instead of fighting DevExtreme's date widget, we just use the default
                # "Bugünden İtibaren" or no date filter, relying on pagination to get 
                # recent tenders.
                try:
                    # Optional: Just make sure we are not stuck in a bad state
                    await human_delay(1.0, 1.5)
                except Exception as e:
                    pass

                # ── Click Filtrele ───────────────────────────────────────────
                try:
                    filtrele = page.locator("button", has_text="Filtrele").first
                    await filtrele.click(timeout=8000)
                    logger.info("Clicked Filtrele button")
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception as e:
                    logger.warning(f"Could not click Filtrele: {e}")

                await human_delay(3.0, 5.0)

                # ── Paginate ─────────────────────────────────────────────────
                page_num = 1
                while True:
                    results = await self._parse_search_results(page)
                    all_results.extend(results)
                    logger.info(f"Page {page_num}: {len(results)} tenders")

                    try:
                        next_btn = page.locator(
                            ".dx-navigate-button.dx-next-button:not(.dx-state-disabled)"
                        ).first
                        if not await next_btn.is_visible(timeout=2000):
                            break
                        await next_btn.click()
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        await human_delay(1.5, 3.0)
                        page_num += 1
                    except Exception:
                        break

                    if page_num > 10:
                        break

            # ── Save to PostgreSQL ────────────────────────────────────────────
            items_saved = 0
            if all_results:
                async with get_session() as session:
                    for r in all_results:
                        try:
                            raw_text = (
                                f"İhale Kayıt No (İKN): {r.ikn}\n"
                                f"Başlık: {r.title}\n"
                                f"Kazanan: {r.winner_company}\n"
                                f"Tutar: {r.bid_amount} TRY\n"
                                f"Tarih: {r.tender_date}"
                            )
                            content_hash = RawDocument.compute_hash(raw_text)
                            doc = RawDocument(
                                doc_type=DocumentType.EKAP_TENDER.value,
                                title=r.title,
                                source_url=r.source_url,
                                raw_text=raw_text,
                                content_hash=content_hash,
                                session_id=r.ikn,
                                date=r.tender_date,
                                metadata_json=r.model_dump(),
                                processing_status="pending",
                            )
                            session.add(doc)
                            await session.flush()
                            items_saved += 1
                        except IntegrityError:
                            await session.rollback()
                            logger.debug(f"Duplicate skipped: {r.ikn}")
                        except Exception as e:
                            await session.rollback()
                            logger.error(f"Failed to save {r.ikn}: {e}")

            duration = (datetime.now() - start_time).total_seconds()
            return ScrapeResult(
                success=True,
                items_found=len(all_results),
                items_saved=items_saved,
                duration_seconds=duration,
                saved_path="PostgreSQL: RawDocument",
            )

        except Exception as e:
            logger.exception("Failed to scrape EKAP")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )


        # Map our sector names to EKAP v2 button IDs
        SECTOR_BTN = {
            "GOODS": "filter-button-1",
            "CONSTRUCTION": "filter-button-2",
            "SERVICES": "filter-button-3",
            "CONSULTANCY": "filter-button-4",
        }

        start_time = datetime.now()
        sectors = sectors or ["CONSTRUCTION"]
        all_results: list[TenderResult] = []

        try:
            async with self._create_page() as page:
                if STEALTH_AVAILABLE:
                    await Stealth().apply_stealth_async(page)
                    logger.info("🥷 Stealth mode activated for latest scan")

                await human_delay(1.0, 2.5)
                await page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=30000)
                await human_delay(2.0, 4.0)

                # ── Click sector filter buttons ──────────────────────────────
                for sector in sectors:
                    btn_id = SECTOR_BTN.get(sector)
                    if btn_id:
                        try:
                            btn = page.locator(f"button#{btn_id}")
                            await btn.click(timeout=5000)
                            await human_delay(0.3, 0.7)
                            logger.info(f"Sector filter selected: {sector}")
                        except Exception:
                            logger.warning(f"Could not click sector button: {sector}")

                # ── Set date range ────────────────────────────────────────────
                try:
                    # Click 'Tarih Aralığı' radio to reveal date inputs
                    date_range_radio = page.locator(
                        "text=Tarih Aralığı"
                    ).first
                    await date_range_radio.click(timeout=5000)
                    await human_delay(0.5, 1.0)

                    end_date = datetime.now()
                    start_date = end_date - timedelta(days=days)
                    fmt = "%d.%m.%Y"

                    start_input = page.locator(
                        "input.dx-texteditor-input"
                    ).first
                    await start_input.fill(start_date.strftime(fmt))
                    await human_delay(0.3, 0.6)

                    end_input = page.locator(
                        "input.dx-texteditor-input"
                    ).nth(1)
                    await end_input.fill(end_date.strftime(fmt))
                    await human_delay(0.3, 0.6)

                    logger.info(f"Date range set: {start_date.strftime(fmt)} – {end_date.strftime(fmt)}")
                except Exception as e:
                    logger.warning(f"Could not set date range, scraping without: {e}")

                # ── Click search button ───────────────────────────────────────
                try:
                    search_btn = page.locator("button#search-ihale, button.search-button").first
                    await search_btn.click(timeout=8000)
                    await page.wait_for_load_state("networkidle", timeout=20000)
                except Exception:
                    logger.warning("Could not click search button, parsing current results")

                await human_delay(2.0, 3.0)

                # ── Paginate through results ──────────────────────────────────
                page_num = 1
                while True:
                    results = await self._parse_search_results(page)
                    all_results.extend(results)
                    logger.info(f"Page {page_num}: {len(results)} tenders")

                    # Check for next page button
                    try:
                        next_btn = page.locator(
                            ".dx-navigate-button.dx-next-button:not(.dx-state-disabled), "
                            "button.next-page:not([disabled])"
                        ).first
                        if not await next_btn.is_visible(timeout=2000):
                            break
                        await next_btn.click()
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        await human_delay(1.0, 2.0)
                        page_num += 1
                    except Exception:
                        break  # No more pages

                    if page_num > 10:
                        break

            # ── Save to PostgreSQL ────────────────────────────────────────────
            items_saved = 0
            if all_results:
                async with get_session() as session:
                    for r in all_results:
                        try:
                            raw_text = (
                                f"İhale Kayıt No (İKN): {r.ikn}\n"
                                f"Başlık: {r.title}\n"
                                f"Kazanan: {r.winner_company}\n"
                                f"Tutar: {r.bid_amount} TRY\n"
                                f"Tarih: {r.tender_date}"
                            )
                            content_hash = RawDocument.compute_hash(raw_text)

                            doc = RawDocument(
                                doc_type=DocumentType.EKAP_TENDER.value,
                                title=r.title,
                                source_url=r.source_url,
                                raw_text=raw_text,
                                content_hash=content_hash,
                                session_id=r.ikn,
                                date=r.tender_date,
                                metadata_json=r.model_dump(),
                                processing_status="pending",
                            )
                            session.add(doc)
                            await session.flush()
                            items_saved += 1
                        except IntegrityError:
                            await session.rollback()
                            logger.debug(f"Duplicate EKAP tender skipped: {r.ikn}")
                        except Exception as e:
                            await session.rollback()
                            logger.error(f"Failed to save EKAP tender {r.ikn}: {e}")

            duration = (datetime.now() - start_time).total_seconds()
            return ScrapeResult(
                success=True,
                items_found=len(all_results),
                items_saved=items_saved,
                duration_seconds=duration,
                saved_path="PostgreSQL: RawDocument",
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
        """
        Parse tender cards from EKAP v2 card-based result layout.

        EKAP v2 uses DevExtreme widgets with card components instead of
        a traditional HTML table.
        """
        results: list[TenderResult] = []

        try:
            # Wait briefly for results to render
            await asyncio.sleep(1.5)

            # Each result card contains a dx-button with id='advert-button'
            # We target the outermost ancestor containing exactly one such button
            cards = await page.query_selector_all(
                "[id='advert-button']"
            )

            if not cards:
                # Fallback: try generic card selectors
                cards = await page.query_selector_all(
                    ".ihale-card, .card-item, dx-list-item, .result-card"
                )

            logger.info(f"Found {len(cards)} result elements on page")

            for card_btn in cards:
                try:
                    # Walk up to the card wrapper (3 levels up from the button)
                    card = card_btn
                    for _ in range(4):
                        parent = await card.evaluate_handle("el => el.parentElement")
                        if parent:
                            card = parent

                    text = await card.inner_text()
                    lines = [l.strip() for l in text.splitlines() if l.strip()]

                    # Extract IKN (format: YYYY/NNNNN)
                    ikn = ""
                    for line in lines:
                        if re.match(r'^\d{4}/\d+', line):
                            ikn = line
                            break

                    if not ikn:
                        continue

                    # Extract date (DD.MM.YYYY)
                    tender_date_raw = ""
                    for line in lines:
                        if re.search(r'\d{2}\.\d{2}\.\d{4}', line):
                            m = re.search(r'(\d{2}\.\d{2}\.\d{4})', line)
                            if m:
                                tender_date_raw = m.group(1)
                            break

                    tender_date = ""
                    if tender_date_raw:
                        try:
                            dt = datetime.strptime(tender_date_raw, "%d.%m.%Y")
                            tender_date = dt.strftime("%Y-%m-%d")
                        except ValueError:
                            pass

                    # Title is usually the line after IKN
                    ikn_idx = lines.index(ikn) if ikn in lines else -1
                    title = lines[ikn_idx + 1] if ikn_idx >= 0 and ikn_idx + 1 < len(lines) else ""

                    # Agency is typically the last meaningful line
                    agency = lines[-1] if lines else ""

                    # Get detail URL from the advert button
                    source_url = SEARCH_URL
                    try:
                        href = await card_btn.get_attribute("href")
                        if href:
                            source_url = urljoin(BASE_URL, href)
                    except Exception:
                        pass

                    result = TenderResult(
                        ikn=ikn,
                        title=title,
                        winner_company=agency,  # winner info needs detail page
                        winner_mersis=None,
                        bid_amount=0.0,          # amount needs detail page
                        tender_date=tender_date or datetime.now().strftime("%Y-%m-%d"),
                        source_url=source_url,
                    )
                    results.append(result)

                except Exception as e:
                    logger.debug(f"Failed to parse card: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to parse search results: {e}")

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
