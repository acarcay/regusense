"""
Political Scraper Module.

Provides scrapers for fetching political statements from:
- News RSS feeds
- Local JSON/TXT files (for prototype phase)
- TBMM transcripts

Author: ReguSense Team
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """Represents a news headline or statement.
    
    Attributes:
        title: The headline or statement text
        source: News source (e.g., "Hürriyet", "NTV")
        date: Publication date
        url: Source URL
        speaker: Extracted speaker name (if applicable)
    """
    title: str
    source: str = ""
    date: str = ""
    url: str = ""
    speaker: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for ingestion."""
        return {
            "text": self.title,
            "source": self.source,
            "date": self.date,
            "speaker": self.speaker,
            "topic": "news",
        }


@dataclass
class StatementItem:
    """Represents a parsed political statement.
    
    Attributes:
        text: The statement text
        speaker: Name of the speaker
        date: Date of the statement
        topic: Topic/category
        source: Source of the statement
    """
    text: str
    speaker: str = ""
    date: str = ""
    topic: str = ""
    source: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for ingestion."""
        return {
            "text": self.text,
            "speaker": self.speaker,
            "date": self.date,
            "topic": self.topic,
            "source": self.source,
        }


class NewsScraper:
    """Scraper for news RSS feeds and headlines.
    
    Fetches political news headlines from various Turkish news sources.
    Can filter by politician name for targeted monitoring.
    
    Example:
        >>> scraper = NewsScraper()
        >>> items = await scraper.fetch_google_news("Mehmet Şimşek ekonomi")
        >>> for item in items:
        ...     print(item.title)
    """
    
    # Common Turkish news RSS feeds
    RSS_FEEDS = {
        "ntv": "https://www.ntv.com.tr/ekonomi.rss",
        "hurriyet": "https://www.hurriyet.com.tr/rss/ekonomi",
        "haberturk": "https://www.haberturk.com/rss/ekonomi.xml",
    }
    
    # Google News RSS base URL
    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
    
    def __init__(
        self,
        timeout_seconds: int = 30,
        politician_filters: Optional[list[str]] = None,
    ):
        """
        Initialize the news scraper.
        
        Args:
            timeout_seconds: Request timeout
            politician_filters: Optional list of politician names to filter for
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.politician_filters = politician_filters or []
    
    async def fetch_rss_feed(self, feed_url: str, source_name: str = "") -> list[NewsItem]:
        """
        Fetch and parse an RSS feed.
        
        Args:
            feed_url: URL of the RSS feed
            source_name: Name of the source for metadata
            
        Returns:
            List of NewsItem objects
        """
        items = []
        
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(feed_url) as response:
                    if response.status != 200:
                        logger.warning(f"RSS feed returned {response.status}: {feed_url}")
                        return items
                    
                    content = await response.text()
                    
            # Parse XML
            root = ElementTree.fromstring(content)
            
            # Handle different RSS formats
            for item in root.findall(".//item"):
                title_elem = item.find("title")
                link_elem = item.find("link")
                pubdate_elem = item.find("pubDate")
                
                if title_elem is None or not title_elem.text:
                    continue
                
                title = title_elem.text.strip()
                
                # Filter by politician if filters are set
                if self.politician_filters:
                    if not any(pol.lower() in title.lower() for pol in self.politician_filters):
                        continue
                
                # Extract speaker from title if possible
                speaker = self._extract_speaker_from_title(title)
                
                items.append(NewsItem(
                    title=title,
                    source=source_name,
                    date=pubdate_elem.text if pubdate_elem is not None else "",
                    url=link_elem.text if link_elem is not None else "",
                    speaker=speaker,
                ))
                
        except Exception as e:
            logger.error(f"Error fetching RSS feed {feed_url}: {e}")
        
        return items
    
    async def fetch_google_news(self, query: str, max_results: int = 10) -> list[NewsItem]:
        """
        Fetch news from Google News RSS.
        
        Args:
            query: Search query (e.g., "Mehmet Şimşek ekonomi")
            max_results: Maximum number of results to return
            
        Returns:
            List of NewsItem objects
        """
        import urllib.parse
        
        # Build Google News RSS URL
        encoded_query = urllib.parse.quote(query)
        feed_url = f"{self.GOOGLE_NEWS_RSS}?q={encoded_query}&hl=tr&gl=TR&ceid=TR:tr"
        
        items = await self.fetch_rss_feed(feed_url, source_name="Google News")
        return items[:max_results]
    
    async def fetch_all_feeds(self) -> list[NewsItem]:
        """
        Fetch news from all configured RSS feeds.
        
        Returns:
            Combined list of NewsItem objects from all feeds
        """
        all_items = []
        
        for source_name, feed_url in self.RSS_FEEDS.items():
            items = await self.fetch_rss_feed(feed_url, source_name)
            all_items.extend(items)
            logger.info(f"Fetched {len(items)} items from {source_name}")
        
        return all_items
    
    def _extract_speaker_from_title(self, title: str) -> str:
        """
        Try to extract the speaker name from a news title.
        
        Looks for patterns like:
        - "Mehmet Şimşek: ..."
        - "Bakan Şimşek'ten açıklama: ..."
        - "'...' dedi Erdoğan"
        
        Returns:
            Extracted speaker name or empty string
        """
        # Pattern: "Name: ..." or "Name'den: ..."
        match = re.match(r"^([A-ZÇĞİÖŞÜa-zçğıöşü\s]+)(?:'[a-z]+)?:\s", title)
        if match:
            return match.group(1).strip()
        
        # Pattern: "... dedi Name"
        match = re.search(r"dedi\s+([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+)?)", title)
        if match:
            return match.group(1).strip()
        
        # Pattern: "Bakan/Başkan Name'den ..."
        match = re.match(r"(?:Bakan|Başkan|Cumhurbaşkanı)\s+([A-ZÇĞİÖŞÜa-zçğıöşü]+)", title)
        if match:
            return match.group(1).strip()
        
        # Check against politician filters
        for pol in self.politician_filters:
            if pol.lower() in title.lower():
                return pol
        
        return ""


class ManualDataIngest:
    """Helper for loading local JSON/TXT files.
    
    Provides methods to parse various formats of political statement data
    for the prototype phase before live API integration.
    
    Supported formats:
    - JSON: List of statement objects
    - TXT: Line-separated statements
    - TBMM transcript format
    
    Example:
        >>> ingest = ManualDataIngest()
        >>> statements = ingest.load_json("data/statements.json")
        >>> for stmt in statements:
        ...     print(stmt.speaker, stmt.text)
    """
    
    def __init__(self, default_source: str = "manual"):
        """
        Initialize the ingester.
        
        Args:
            default_source: Default source label for ingested data
        """
        self.default_source = default_source
    
    def load_json(self, file_path: str | Path) -> list[StatementItem]:
        """
        Load statements from a JSON file.
        
        Expected JSON format:
        [
            {
                "text": "statement text",
                "speaker": "speaker name",
                "date": "2024-01-15",
                "topic": "economy"
            },
            ...
        ]
        
        Args:
            file_path: Path to the JSON file
            
        Returns:
            List of StatementItem objects
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            items = []
            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict) and entry.get("text"):
                        items.append(StatementItem(
                            text=entry["text"],
                            speaker=entry.get("speaker", ""),
                            date=entry.get("date", ""),
                            topic=entry.get("topic", ""),
                            source=entry.get("source", self.default_source),
                        ))
            
            logger.info(f"Loaded {len(items)} statements from {file_path}")
            return items
            
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {file_path}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return []
    
    def load_txt(
        self,
        file_path: str | Path,
        speaker: str = "",
        date: str = "",
    ) -> list[StatementItem]:
        """
        Load statements from a plain text file.
        
        Each non-empty line is treated as a separate statement.
        Lines starting with # are treated as comments and skipped.
        
        Args:
            file_path: Path to the TXT file
            speaker: Default speaker for all statements
            date: Default date for all statements
            
        Returns:
            List of StatementItem objects
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            items = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#"):
                    items.append(StatementItem(
                        text=line,
                        speaker=speaker,
                        date=date,
                        source=self.default_source,
                    ))
            
            logger.info(f"Loaded {len(items)} statements from {file_path}")
            return items
            
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return []
    
    def load_tbmm_transcript(
        self,
        file_path: str | Path,
        commission_name: str = "",
    ) -> list[StatementItem]:
        """
        Load statements from a TBMM transcript text file.
        
        Parses the transcript format looking for speaker patterns like:
        "MEHMET ŞİMŞEK (İstanbul) - ..."
        
        Args:
            file_path: Path to the transcript file
            commission_name: Name of the commission for metadata
            
        Returns:
            List of StatementItem objects
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return []
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            items = []
            
            # Pattern for speaker with constituency: "NAME SURNAME (City) - statement"
            speaker_pattern = r"([A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü\s]+)\s*\([A-ZÇĞİÖŞÜa-zçğıöşü]+\)\s*[-–—]\s*(.+?)(?=\n[A-ZÇĞİÖŞÜ][A-ZÇĞİÖŞÜa-zçğıöşü\s]+\s*\([A-ZÇĞİÖŞÜa-zçğıöşü]+\)\s*[-–—]|\Z)"
            
            matches = re.findall(speaker_pattern, content, re.MULTILINE | re.DOTALL)
            
            for speaker, text in matches:
                text = text.strip()
                if len(text) > 50:  # Skip very short fragments
                    items.append(StatementItem(
                        text=text,
                        speaker=speaker.strip(),
                        topic=commission_name,
                        source="TBMM",
                    ))
            
            # If pattern didn't match, fall back to paragraph extraction
            if not items:
                paragraphs = content.split("\n\n")
                for para in paragraphs:
                    para = para.strip()
                    if len(para) > 100:  # Skip short paragraphs
                        items.append(StatementItem(
                            text=para,
                            topic=commission_name,
                            source="TBMM",
                        ))
            
            logger.info(f"Loaded {len(items)} statements from TBMM transcript {file_path}")
            return items
            
        except Exception as e:
            logger.error(f"Error loading TBMM transcript {file_path}: {e}")
            return []
    
    def load_directory(
        self,
        dir_path: str | Path,
        pattern: str = "*.json",
    ) -> list[StatementItem]:
        """
        Load all matching files from a directory.
        
        Args:
            dir_path: Path to the directory
            pattern: Glob pattern for files to load
            
        Returns:
            Combined list of StatementItem objects
        """
        dir_path = Path(dir_path)
        
        if not dir_path.exists() or not dir_path.is_dir():
            logger.warning(f"Directory not found: {dir_path}")
            return []
        
        all_items = []
        
        for file_path in dir_path.glob(pattern):
            if file_path.suffix.lower() == ".json":
                items = self.load_json(file_path)
            elif file_path.suffix.lower() == ".txt":
                items = self.load_txt(file_path)
            else:
                continue
            
            all_items.extend(items)
        
        logger.info(f"Loaded {len(all_items)} total statements from {dir_path}")
        return all_items
