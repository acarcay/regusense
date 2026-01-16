"""
TBMM Genel Kurul Tutanakları Scraper (V2).

Downloads General Assembly (Genel Kurul) transcripts from TBMM website.
Fixed version: Navigates to session detail pages to get actual PDF URLs.

URL Pattern: 
  List: https://www.tbmm.gov.tr/Tutanaklar/DoneminTutanakMetinleri?Donem=28&YasamaYili=2
  Detail: https://www.tbmm.gov.tr/Tutanaklar/Tutanak?Id={UUID}
  PDF: https://cdn.tbmm.gov.tr/TbmmWeb/Tutanak/{Donem}/{Yil}/{Birlesim}/Tam/{UUID}.pdf

Author: ReguSense Team
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Base URLs
BASE_URL = "https://www.tbmm.gov.tr"
CDN_URL = "https://cdn.tbmm.gov.tr"
DONEM_URL = "https://www.tbmm.gov.tr/Tutanaklar/DoneminTutanakMetinleri?Donem={donem}&YasamaYili={yasama_yili}"


@dataclass
class TutanakInfo:
    """Information about a single transcript."""
    donem: int
    yasama_yili: int
    birlesim: int
    tarih: str
    pdf_url: str
    title: str
    detail_url: str = ""


class GenelKurulScraper:
    """Scraper for TBMM General Assembly transcripts.
    
    V2: Navigates to detail pages to extract actual PDF URLs.
    
    Example:
        >>> scraper = GenelKurulScraper(output_dir="data/raw/genel_kurul")
        >>> scraper.scrape_all(donem_start=28, yasama_yili_start=1)
    """
    
    def __init__(
        self,
        output_dir: str = "data/raw/genel_kurul",
        rate_limit: float = 1.5,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
        })
    
    def get_session_list(self, donem: int, yasama_yili: int) -> list[TutanakInfo]:
        """
        Get list of sessions (Birleşim) for a specific dönem and yasama yılı.
        
        Args:
            donem: Legislative term (e.g., 28)
            yasama_yili: Legislative year (e.g., 1, 2, 3)
            
        Returns:
            List of TutanakInfo objects with detail page URLs
        """
        url = DONEM_URL.format(donem=donem, yasama_yili=yasama_yili)
        logger.info(f"Fetching session list: Dönem {donem}, Yasama Yılı {yasama_yili}")
        
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch session list: {e}")
            return []
        
        soup = BeautifulSoup(response.text, "lxml")
        sessions = []
        
        # Find session links in the table
        # Pattern: /Tutanaklar/Tutanak?Id=...
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            
            if "/Tutanaklar/Tutanak?Id=" in href:
                # Extract title (usually "X. Birleşim")
                title = link.get_text(strip=True)
                
                # Try to extract birleşim number
                birlesim = 0
                birlesim_match = re.search(r"(\d+)\s*\.?\s*Birleşim", title, re.IGNORECASE)
                if birlesim_match:
                    birlesim = int(birlesim_match.group(1))
                
                # Try to find date in sibling cells
                tarih = ""
                parent_row = link.find_parent("tr")
                if parent_row:
                    cells = parent_row.find_all("td")
                    for cell in cells:
                        text = cell.get_text(strip=True)
                        # Look for date patterns like "16 Ağustos 2024"
                        date_match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
                        if date_match:
                            day, month_name, year = date_match.groups()
                            tarih = f"{year}-{self._month_to_num(month_name)}-{day.zfill(2)}"
                            break
                
                # Make absolute URL
                detail_url = urljoin(BASE_URL, href)
                
                sessions.append(TutanakInfo(
                    donem=donem,
                    yasama_yili=yasama_yili,
                    birlesim=birlesim,
                    tarih=tarih,
                    pdf_url="",  # Will be filled after visiting detail page
                    title=title,
                    detail_url=detail_url,
                ))
        
        # Remove duplicates (same birleşim number)
        seen = set()
        unique_sessions = []
        for s in sessions:
            if s.birlesim not in seen:
                seen.add(s.birlesim)
                unique_sessions.append(s)
        
        logger.info(f"Found {len(unique_sessions)} sessions")
        return unique_sessions
    
    def _month_to_num(self, month_name: str) -> str:
        """Convert Turkish month name to number."""
        months = {
            "ocak": "01", "şubat": "02", "mart": "03", "nisan": "04",
            "mayıs": "05", "haziran": "06", "temmuz": "07", "ağustos": "08",
            "eylül": "09", "ekim": "10", "kasım": "11", "aralık": "12",
        }
        return months.get(month_name.lower(), "01")
    
    def get_pdf_url_from_detail(self, detail_url: str) -> Optional[str]:
        """
        Get PDF URL from session detail page.
        
        Args:
            detail_url: URL of the session detail page
            
        Returns:
            PDF URL or None if not found
        """
        try:
            response = self.session.get(detail_url, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Failed to fetch detail page: {e}")
            return None
        
        soup = BeautifulSoup(response.text, "lxml")
        
        # Method 1: Look for embed tag with PDF
        embed = soup.find("embed", src=True)
        if embed:
            src = embed.get("src", "")
            if ".pdf" in src.lower():
                if src.startswith("http"):
                    return src
                return urljoin(CDN_URL, src)
        
        # Method 2: Look for iframe with PDF
        iframe = soup.find("iframe", src=True)
        if iframe:
            src = iframe.get("src", "")
            if ".pdf" in src.lower():
                if src.startswith("http"):
                    return src
                return urljoin(CDN_URL, src)
        
        # Method 3: Look for direct PDF links containing "Tam" (full transcript)
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if ".pdf" in href.lower() and "Tam" in href:
                if href.startswith("http"):
                    return href
                return urljoin(CDN_URL, href)
        
        # Method 4: Search for any cdn.tbmm.gov.tr PDF link
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "cdn.tbmm.gov.tr" in href and ".pdf" in href.lower():
                return href
        
        logger.warning(f"No PDF found on detail page: {detail_url}")
        return None
    
    def download_pdf(self, tutanak: TutanakInfo) -> Optional[Path]:
        """
        Download a single tutanak PDF.
        
        Args:
            tutanak: TutanakInfo object with pdf_url
            
        Returns:
            Path to downloaded file or None if failed
        """
        if not tutanak.pdf_url:
            logger.warning(f"No PDF URL for Birleşim {tutanak.birlesim}")
            return None
        
        # Create filename
        filename = f"gk_donem{tutanak.donem}_yy{tutanak.yasama_yili}_b{tutanak.birlesim:03d}"
        if tutanak.tarih:
            filename += f"_{tutanak.tarih}"
        filename += ".pdf"
        
        filepath = self.output_dir / filename
        
        # Skip if already downloaded
        if filepath.exists() and filepath.stat().st_size > 10000:
            logger.debug(f"Already exists: {filename}")
            return filepath
        
        try:
            response = self.session.get(tutanak.pdf_url, timeout=120)
            response.raise_for_status()
            
            # Verify it's actually a PDF
            if not response.content[:4] == b"%PDF":
                logger.warning(f"Not a valid PDF: {tutanak.pdf_url}")
                return None
            
            # Save file
            with open(filepath, "wb") as f:
                f.write(response.content)
            
            size_kb = filepath.stat().st_size // 1024
            logger.info(f"Downloaded: {filename} ({size_kb} KB)")
            return filepath
            
        except requests.RequestException as e:
            logger.error(f"Download failed: {tutanak.pdf_url} - {e}")
            return None
    
    def scrape_donem(
        self,
        donem: int,
        yasama_yili_start: int = 1,
        yasama_yili_end: int = 5,
        max_per_year: int = 50,
    ) -> dict:
        """
        Scrape all tutanaklar for a specific dönem.
        
        Args:
            donem: Legislative term
            yasama_yili_start: Starting yasama yılı
            yasama_yili_end: Ending yasama yılı
            max_per_year: Maximum sessions per year
            
        Returns:
            Stats dictionary
        """
        stats = {
            "donem": donem,
            "total_found": 0,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
        }
        
        for yy in range(yasama_yili_start, yasama_yili_end + 1):
            sessions = self.get_session_list(donem, yy)
            sessions = sessions[:max_per_year]  # Limit per year
            stats["total_found"] += len(sessions)
            
            for session in sessions:
                time.sleep(self.rate_limit)
                
                # Get PDF URL from detail page
                logger.info(f"Fetching PDF URL for Birleşim {session.birlesim}...")
                pdf_url = self.get_pdf_url_from_detail(session.detail_url)
                
                if pdf_url:
                    session.pdf_url = pdf_url
                    result = self.download_pdf(session)
                    
                    if result:
                        stats["downloaded"] += 1
                    else:
                        stats["failed"] += 1
                else:
                    stats["failed"] += 1
        
        return stats
    
    def scrape_all(
        self,
        donem_start: int = 28,
        donem_end: int = 28,
        yasama_yili_end: int = 5,
        max_per_year: int = 50,
    ) -> dict:
        """
        Scrape all tutanaklar for multiple dönemler.
        
        Args:
            donem_start: Starting dönem
            donem_end: Ending dönem
            yasama_yili_end: Max yasama yılı per dönem
            max_per_year: Max sessions per year
            
        Returns:
            Aggregated stats
        """
        total_stats = {
            "total_found": 0,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "donemler": [],
        }
        
        for donem in range(donem_start, donem_end + 1):
            logger.info(f"=== Dönem {donem} ===")
            stats = self.scrape_donem(
                donem,
                yasama_yili_end=yasama_yili_end,
                max_per_year=max_per_year,
            )
            
            total_stats["total_found"] += stats["total_found"]
            total_stats["downloaded"] += stats["downloaded"]
            total_stats["skipped"] += stats["skipped"]
            total_stats["failed"] += stats["failed"]
            total_stats["donemler"].append(stats)
        
        return total_stats


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Scrape TBMM Genel Kurul tutanakları (V2 - Detail Page Navigation)"
    )
    parser.add_argument(
        "--donem", "-d",
        type=int,
        default=28,
        help="Dönem number (default: 28 - current)",
    )
    parser.add_argument(
        "--yasama-yili", "-y",
        type=int,
        default=None,
        help="Specific yasama yılı (default: all)",
    )
    parser.add_argument(
        "--max-per-year", "-m",
        type=int,
        default=20,
        help="Maximum sessions per year (default: 20)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="data/raw/genel_kurul",
        help="Output directory",
    )
    parser.add_argument(
        "--rate-limit", "-r",
        type=float,
        default=1.5,
        help="Seconds between requests",
    )
    
    args = parser.parse_args()
    
    scraper = GenelKurulScraper(
        output_dir=args.output,
        rate_limit=args.rate_limit,
    )
    
    if args.yasama_yili:
        stats = scraper.scrape_donem(
            donem=args.donem,
            yasama_yili_start=args.yasama_yili,
            yasama_yili_end=args.yasama_yili,
            max_per_year=args.max_per_year,
        )
    else:
        stats = scraper.scrape_all(
            donem_start=args.donem,
            donem_end=args.donem,
            max_per_year=args.max_per_year,
        )
    
    print("\n=== SONUÇ ===")
    print(f"Toplam Bulunan: {stats['total_found']}")
    print(f"İndirilen: {stats['downloaded']}")
    print(f"Atlanan: {stats['skipped']}")
    print(f"Başarısız: {stats['failed']}")


if __name__ == "__main__":
    main()
