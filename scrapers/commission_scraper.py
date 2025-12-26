"""
TBMM Commission Transcript Scraper.

A sophisticated Playwright-based scraper for fetching commission meeting transcripts
from the Turkish Grand National Assembly (TBMM) website.

Features:
- Async Playwright navigation for dynamic JS-rendered pages
- Automatic date parsing and latest transcript detection
- Robust retry logic with exponential backoff
- Configurable timeouts and error handling
- Type-safe dataclasses for structured data

Usage:
    python -m scrapers.commission_scraper

Author: ReguSense Team
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

# Add parent directory to path for imports when running as module
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import COMMISSION_URLS, settings

# Ensure data directories exist before configuring logging
settings.ensure_directories()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.logs_dir / "commission_scraper.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class TranscriptInfo:
    """
    Represents a commission transcript entry.

    Attributes:
        title: The full title/description of the transcript
        date: Parsed date of the commission meeting
        url: Full URL to access the transcript
        transcript_id: Unique identifier extracted from the URL
        raw_text: Optional raw link text for debugging
    """

    title: str
    date: datetime
    url: str
    transcript_id: str
    raw_text: str = ""

    def __post_init__(self) -> None:
        """Validate transcript data after initialization."""
        if not self.url.startswith("http"):
            raise ValueError(f"Invalid URL format: {self.url}")
        if not self.transcript_id:
            raise ValueError("transcript_id cannot be empty")

    @property
    def filename(self) -> str:
        """Generate a safe filename for saving the transcript."""
        date_str = self.date.strftime("%Y-%m-%d")
        # Sanitize title for filename
        safe_title = re.sub(r"[^\w\s-]", "", self.title[:50]).strip().replace(" ", "_")
        return f"{date_str}_{self.transcript_id}_{safe_title}"
    
    def get_filename_with_ext(self, ext: str = "html") -> str:
        """Generate filename with specified extension."""
        return f"{self.filename}.{ext}"


@dataclass
class ScrapeResult:
    """
    Result of a scraping operation.

    Attributes:
        success: Whether the scrape was successful
        transcripts: List of discovered transcripts
        latest_transcript: The most recent transcript (if any)
        saved_path: Path where content was saved (if applicable)
        error: Error message if scrape failed
        duration_seconds: Time taken for the scrape operation
    """

    success: bool
    transcripts: list[TranscriptInfo] = field(default_factory=list)
    latest_transcript: Optional[TranscriptInfo] = None
    saved_path: Optional[Path] = None
    error: Optional[str] = None
    duration_seconds: float = 0.0


class CommissionScraper:
    """
    Playwright-based scraper for TBMM commission transcripts.

    This scraper handles dynamic JavaScript-rendered pages on the TBMM website,
    extracting transcript links, parsing dates, and downloading the latest transcript.

    Example:
        async with CommissionScraper() as scraper:
            result = await scraper.scrape_commission_page(
                "https://www.tbmm.gov.tr/ihtisas-komisyonlari/..."
            )
            if result.success:
                print(f"Found {len(result.transcripts)} transcripts")
                print(f"Latest: {result.latest_transcript.title}")
    """

    # Regex patterns for parsing transcript links
    DATE_PATTERN = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
    TRANSCRIPT_URL_PATTERN = re.compile(r"/Tutanaklar/TutanakGoster/(\d+)")

    def __init__(
        self,
        headless: bool = True,
        retry_attempts: int = 3,
        page_timeout_ms: int = 30000,
    ) -> None:
        """
        Initialize the commission scraper.

        Args:
            headless: Run browser in headless mode (default: True)
            retry_attempts: Number of retry attempts for failed operations
            page_timeout_ms: Page load timeout in milliseconds
        """
        self.headless = headless if settings.headless else settings.headless
        self.retry_attempts = retry_attempts or settings.retry_attempts
        self.page_timeout_ms = page_timeout_ms or settings.page_timeout_ms

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

        # Ensure data directories exist
        settings.ensure_directories()

    async def __aenter__(self) -> "CommissionScraper":
        """Context manager entry - start browser."""
        await self._start_browser()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close browser."""
        await self._close_browser()

    async def _start_browser(self) -> None:
        """Start Playwright browser instance."""
        logger.info("Starting Playwright browser...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            slow_mo=settings.slow_mo,
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            accept_downloads=True,
        )
        logger.info("Browser started successfully")

    async def _close_browser(self) -> None:
        """Close browser and cleanup resources."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")

    async def _create_page(self) -> Page:
        """Create a new page with configured timeouts."""
        if not self._context:
            raise RuntimeError("Browser context not initialized. Use async context manager.")

        page = await self._context.new_page()
        page.set_default_timeout(self.page_timeout_ms)
        page.set_default_navigation_timeout(settings.navigation_timeout_ms)
        return page

    def _parse_date_from_text(self, text: str) -> Optional[datetime]:
        """
        Extract and parse date from Turkish date format in text.

        Args:
            text: Text containing date in DD.MM.YYYY format

        Returns:
            Parsed datetime or None if no valid date found
        """
        match = self.DATE_PATTERN.search(text)
        if match:
            day, month, year = match.groups()
            try:
                return datetime(int(year), int(month), int(day))
            except ValueError as e:
                logger.warning(f"Invalid date values in '{text}': {e}")
        return None

    def _extract_transcript_id(self, url: str) -> Optional[str]:
        """
        Extract transcript ID from URL.

        Args:
            url: URL path like /Tutanaklar/TutanakGoster/843

        Returns:
            Transcript ID string or None if not found
        """
        match = self.TRANSCRIPT_URL_PATTERN.search(url)
        return match.group(1) if match else None

    async def _extract_transcript_links(self, page: Page) -> list[TranscriptInfo]:
        """
        Extract all transcript links from the loaded page.

        Args:
            page: Playwright page object with loaded content

        Returns:
            List of TranscriptInfo objects sorted by date (newest first)
        """
        transcripts: list[TranscriptInfo] = []

        # Find all links matching the transcript pattern
        links = await page.query_selector_all("a[href*='TutanakGoster']")
        logger.info(f"Found {len(links)} potential transcript links")

        for link in links:
            try:
                href = await link.get_attribute("href")
                text = await link.inner_text()

                if not href or not text:
                    continue

                # Parse the transcript info
                transcript_id = self._extract_transcript_id(href)
                date = self._parse_date_from_text(text)

                if transcript_id and date:
                    # Build full URL
                    full_url = (
                        href if href.startswith("http") else f"{settings.tbmm_base_url}{href}"
                    )

                    transcript = TranscriptInfo(
                        title=text.strip(),
                        date=date,
                        url=full_url,
                        transcript_id=transcript_id,
                        raw_text=text,
                    )
                    transcripts.append(transcript)
                    logger.debug(f"Parsed transcript: {transcript.title} ({transcript.date})")

            except Exception as e:
                logger.warning(f"Error parsing link: {e}")
                continue

        # Sort by date (newest first)
        transcripts.sort(key=lambda t: t.date, reverse=True)
        logger.info(f"Successfully parsed {len(transcripts)} transcripts")

        return transcripts

    async def _download_via_http(
        self, transcript: TranscriptInfo
    ) -> Optional[Path]:
        """
        Download transcript content directly via HTTP using aiohttp.
        
        This is used when the browser returns an image viewer wrapper instead of
        triggering a direct PDF download. The TutanakGoster URL actually returns
        PDF content when accessed directly via HTTP request.
        
        Args:
            transcript: TranscriptInfo with URL to download
            
        Returns:
            Path to saved PDF file, or None if download failed
        """
        import aiohttp
        
        logger.info(f"Attempting direct HTTP download from: {transcript.url}")
        
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/pdf,*/*",
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(transcript.url, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status != 200:
                        logger.error(f"HTTP download failed with status: {response.status}")
                        return None
                    
                    content_type = response.headers.get("Content-Type", "")
                    content = await response.read()
                    
                    logger.info(f"Downloaded {len(content)} bytes, Content-Type: {content_type}")
                    
                    # Check if content is actually a PDF
                    if content.startswith(b"%PDF") or "pdf" in content_type.lower():
                        save_path = settings.raw_contracts_dir / transcript.get_filename_with_ext("pdf")
                        save_path.write_bytes(content)
                        logger.info(f"Saved PDF via HTTP download: {save_path}")
                        return save_path
                    else:
                        # Not a PDF - might be an image or HTML
                        logger.warning(f"HTTP response is not a PDF (starts with: {content[:20]})")
                        
                        # If it's an image (JPEG/PNG), save as image
                        if content.startswith(b"\xff\xd8\xff") or content.startswith(b"\x89PNG"):
                            ext = "jpg" if content.startswith(b"\xff\xd8\xff") else "png"
                            save_path = settings.raw_contracts_dir / transcript.get_filename_with_ext(ext)
                            save_path.write_bytes(content)
                            logger.warning(f"Content is an image, saved as: {save_path}")
                            return save_path
                        
                        return None
                        
        except Exception as e:
            logger.error(f"HTTP download failed: {e}")
            return None

    async def _fetch_transcript_content(
        self, page: Page, transcript: TranscriptInfo
    ) -> tuple[Optional[str], Optional[Path]]:
        """
        Navigate to transcript URL and handle either page load or file download.

        The TBMM transcript links can trigger either:
        1. A direct file download (PDF, DOC, etc.)
        2. A page load with a "Download" button that triggers the PDF download
        3. A page with HTML content (fallback)

        This method handles all cases gracefully.

        Args:
            page: Playwright page object
            transcript: TranscriptInfo with URL to fetch

        Returns:
            Tuple of (content_string, downloaded_file_path)
            - For page content: (html_content, None)
            - For downloads: (None, path_to_saved_file)
            - On failure: (None, None)
        """
        logger.info(f"Fetching transcript content from: {transcript.url}")

        downloaded_path: Optional[Path] = None
        download_occurred = False

        async def handle_download(download):
            nonlocal downloaded_path, download_occurred
            download_occurred = True
            
            # Get the suggested filename from the server
            suggested_filename = download.suggested_filename
            logger.info(f"Download triggered: {suggested_filename}")
            
            # Determine extension from suggested filename
            ext = Path(suggested_filename).suffix.lstrip(".") or "pdf"
            
            # Save the download to our data directory
            save_path = settings.raw_contracts_dir / transcript.get_filename_with_ext(ext)
            await download.save_as(save_path)
            downloaded_path = save_path
            
            logger.info(f"Downloaded file saved to: {save_path}")

        # Register the download handler
        page.on("download", handle_download)

        try:
            # Navigate to the URL - this may trigger a download or load a page
            response = await page.goto(transcript.url, wait_until="commit", timeout=self.page_timeout_ms)
            
            # Give some time for download to be triggered
            await asyncio.sleep(3)
            
            if download_occurred and downloaded_path:
                return None, downloaded_path
            
            # No direct download - check if we're on a "Tutanak Görüntüleme" page
            # that has a separate download button
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
                
                # Look for PDF download links/buttons on the page
                # Try multiple selectors that might contain PDF download links
                pdf_selectors = [
                    # Direct PDF links
                    'a[href$=".pdf"]',
                    'a[href*="/pdf/"]',
                    'a[href*="download"]',
                    # Buttons with download text (Turkish)
                    'a:has-text("İndir")',
                    'button:has-text("İndir")',
                    'a:has-text("PDF")',
                    'button:has-text("PDF")',
                    'a:has-text("Dosya İndir")',
                    # Common download button classes
                    '.btn-download',
                    '.download-btn',
                    '[class*="download"]',
                    # TBMM specific selectors
                    'a.tutanak-indir',
                    '.tutanak-download a',
                ]
                
                for selector in pdf_selectors:
                    try:
                        download_link = await page.query_selector(selector)
                        if download_link:
                            logger.info(f"Found download element with selector: {selector}")
                            
                            # Check if it's a direct link or needs clicking
                            href = await download_link.get_attribute("href")
                            if href and (href.endswith(".pdf") or "/pdf/" in href or "download" in href.lower()):
                                logger.info(f"Found PDF link: {href}")
                                
                                # Start waiting for download before clicking
                                async with page.expect_download(timeout=30000) as download_info:
                                    await download_link.click()
                                download = await download_info.value
                                
                                # Handle the download
                                suggested_filename = download.suggested_filename
                                ext = Path(suggested_filename).suffix.lstrip(".") or "pdf"
                                save_path = settings.raw_contracts_dir / transcript.get_filename_with_ext(ext)
                                await download.save_as(save_path)
                                downloaded_path = save_path
                                logger.info(f"Downloaded PDF via button click: {save_path}")
                                return None, downloaded_path
                            
                            # Try clicking to trigger download
                            try:
                                async with page.expect_download(timeout=15000) as download_info:
                                    await download_link.click()
                                download = await download_info.value
                                
                                suggested_filename = download.suggested_filename
                                ext = Path(suggested_filename).suffix.lstrip(".") or "pdf"
                                save_path = settings.raw_contracts_dir / transcript.get_filename_with_ext(ext)
                                await download.save_as(save_path)
                                downloaded_path = save_path
                                logger.info(f"Downloaded file via button click: {save_path}")
                                return None, downloaded_path
                            except Exception as click_error:
                                logger.debug(f"Click didn't trigger download for {selector}: {click_error}")
                                continue
                                
                    except Exception as selector_error:
                        logger.debug(f"Selector {selector} not found or failed: {selector_error}")
                        continue
                
                # No download button found - check if this is an image viewer page
                # and try to download the URL directly via HTTP
                content = await page.content()
                
                # Check if the content is the Chrome image viewer wrapper
                if '<img' in content and 'TutanakGoster' in transcript.url and len(content) < 1000:
                    logger.info("Detected image viewer wrapper - trying direct HTTP download")
                    downloaded_path = await self._download_via_http(transcript)
                    if downloaded_path:
                        return None, downloaded_path
                
                logger.warning(f"No PDF download found - returning HTML content ({len(content)} bytes)")
                return content, None
                
            except Exception as e:
                # If we get here and no download happened, there might be an issue
                logger.warning(f"Could not process page content: {e}")
                
                # Final check for pending downloads
                await asyncio.sleep(2)
                if download_occurred and downloaded_path:
                    return None, downloaded_path
                    
                return None, None

        except Exception as e:
            # Check if download happened despite the error
            await asyncio.sleep(2)
            if download_occurred and downloaded_path:
                return None, downloaded_path
            
            logger.error(f"Error fetching transcript: {e}")
            return None, None
        finally:
            # Clean up the event handler
            page.remove_listener("download", handle_download)

    async def _save_content(
        self, content: str, transcript: TranscriptInfo
    ) -> Path:
        """
        Save transcript content to local file.

        Args:
            content: HTML/text content to save
            transcript: TranscriptInfo for filename generation

        Returns:
            Path to saved file
        """
        filepath = settings.raw_contracts_dir / transcript.filename
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"Saved transcript to: {filepath}")
        return filepath

    async def _retry_with_backoff(self, coro, operation_name: str):
        """
        Execute coroutine with exponential backoff retry.

        Args:
            coro: Coroutine to execute
            operation_name: Name for logging

        Returns:
            Result of coroutine or raises last exception
        """
        last_exception = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                return await coro
            except Exception as e:
                last_exception = e
                if attempt < self.retry_attempts:
                    delay = settings.retry_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        f"{operation_name} failed (attempt {attempt}/{self.retry_attempts}): {e}"
                    )
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"{operation_name} failed after {self.retry_attempts} attempts")

        raise last_exception  # type: ignore

    async def scrape_commission_page(self, url: str) -> ScrapeResult:
        """
        Scrape a commission transcript listing page.

        Navigates to the specified URL, extracts all transcript links,
        identifies the latest transcript by date, and returns structured results.

        Args:
            url: Full URL of the commission transcript listing page

        Returns:
            ScrapeResult with all discovered transcripts and latest transcript
        """
        start_time = datetime.now()
        logger.info(f"Starting scrape of: {url}")

        try:
            page = await self._create_page()

            # Navigate to the page with retry
            async def navigate():
                await page.goto(url, wait_until="networkidle")
                await page.wait_for_load_state("domcontentloaded")
                # Additional wait for dynamic content
                await asyncio.sleep(3)

            await self._retry_with_backoff(navigate(), "Page navigation")

            # Extract transcript links
            transcripts = await self._extract_transcript_links(page)

            if not transcripts:
                logger.warning("No transcripts found on page")
                await page.close()
                return ScrapeResult(
                    success=False,
                    error="No transcripts found on page",
                    duration_seconds=(datetime.now() - start_time).total_seconds(),
                )

            # Get the latest transcript (already sorted newest first)
            latest = transcripts[0]
            logger.info(f"Latest transcript: {latest.title} (Date: {latest.date.date()})")

            await page.close()

            return ScrapeResult(
                success=True,
                transcripts=transcripts,
                latest_transcript=latest,
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )

        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )

    async def download_latest_transcript(self, url: str, max_attempts: int = 3) -> ScrapeResult:
        """
        Scrape commission page and download the latest transcript content.

        This is the main entry point for fetching and saving the most recent
        transcript from a commission listing page. If the latest transcript
        returns non-PDF content (e.g., an image), it will try subsequent
        transcripts up to max_attempts.

        Args:
            url: Full URL of the commission transcript listing page
            max_attempts: Maximum number of transcripts to try before giving up

        Returns:
            ScrapeResult with saved file path if successful
        """
        start_time = datetime.now()
        
        # First, get the list of transcripts
        result = await self.scrape_commission_page(url)

        if not result.success or not result.transcripts:
            return result

        # Try transcripts until we find one that returns a PDF
        page = await self._create_page()
        
        try:
            for i, transcript in enumerate(result.transcripts[:max_attempts]):
                logger.info(f"Trying transcript {i+1}/{min(len(result.transcripts), max_attempts)}: {transcript.title}")
                
                content, downloaded_path = await self._fetch_transcript_content(page, transcript)

                if downloaded_path:
                    # Check if it's actually a PDF (not an image)
                    if downloaded_path.suffix.lower() == ".pdf":
                        result.saved_path = downloaded_path
                        result.latest_transcript = transcript
                        logger.info(f"Successfully downloaded PDF transcript: {downloaded_path}")
                        break
                    else:
                        # It's an image or other non-PDF - try next transcript
                        logger.warning(f"Transcript {transcript.title} returned non-PDF ({downloaded_path.suffix}) - trying next")
                        # Delete the non-PDF file
                        try:
                            downloaded_path.unlink()
                        except Exception:
                            pass
                        continue
                elif content:
                    # HTML content was retrieved - this might be the image viewer
                    # Try next transcript
                    if '<img' in content and len(content) < 1000:
                        logger.warning(f"Transcript {transcript.title} returned image viewer HTML - trying next")
                        continue
                    else:
                        # Real HTML content - save it
                        saved_path = await self._save_content(content, transcript)
                        result.saved_path = saved_path
                        result.latest_transcript = transcript
                        logger.info(f"Successfully saved transcript HTML to: {saved_path}")
                        break
                else:
                    # Failed to fetch - try next
                    logger.warning(f"Failed to fetch transcript {transcript.title} - trying next")
                    continue
            else:
                # Exhausted all attempts
                result.success = False
                result.error = f"Failed to find valid PDF in first {max_attempts} transcripts"

            await page.close()

        except Exception as e:
            logger.error(f"Download failed: {e}")
            result.success = False
            result.error = str(e)

        result.duration_seconds = (datetime.now() - start_time).total_seconds()
        return result


async def main() -> None:
    """
    Main entry point for the commission scraper.

    Demonstrates scraping the Adalet (Justice) Commission transcript page.
    """
    print("=" * 60)
    print("ReguSense Commission Transcript Scraper")
    print("=" * 60)

    # Get the Adalet Commission URL
    target_url = COMMISSION_URLS.get("adalet")
    if not target_url:
        print("ERROR: No URL configured for 'adalet' commission")
        return

    print(f"\nTarget: {target_url}\n")

    async with CommissionScraper(headless=True) as scraper:
        # Scrape and download the latest transcript
        result = await scraper.download_latest_transcript(target_url)

        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)

        if result.success:
            print(f"✓ Success! Found {len(result.transcripts)} transcripts")
            print(f"\n📋 Latest Transcript:")
            if result.latest_transcript:
                print(f"   Title: {result.latest_transcript.title}")
                print(f"   Date: {result.latest_transcript.date.strftime('%Y-%m-%d')}")
                print(f"   URL: {result.latest_transcript.url}")
            if result.saved_path:
                print(f"\n💾 Saved to: {result.saved_path}")
        else:
            print(f"✗ Failed: {result.error}")

        print(f"\n⏱  Duration: {result.duration_seconds:.2f} seconds")

        # List all discovered transcripts
        if result.transcripts:
            print(f"\n📑 All Transcripts ({len(result.transcripts)}):")
            for i, t in enumerate(result.transcripts[:10], 1):  # Show first 10
                print(f"   {i}. [{t.date.strftime('%Y-%m-%d')}] {t.title[:50]}...")
            if len(result.transcripts) > 10:
                print(f"   ... and {len(result.transcripts) - 10} more")


if __name__ == "__main__":
    asyncio.run(main())
