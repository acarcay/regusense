"""
ReguSense Scrapers Module.

Provides async Playwright-based scrapers for political data:
- Twitter/X posts
- TBMM Commission transcripts
- TBMM General Assembly transcripts
- Resmi Gazete (Official Gazette)
- News RSS feeds

All scrapers feature:
- Rate limiting
- User-agent rotation
- Proxy support
- Pydantic validation
- Async vector store ingestion
"""

from scrapers.base import (
    BaseScraper,
    RateLimiter,
    UserAgentRotator,
    ProxyManager,
    ProxyConfig,
)
from scrapers.models import (
    SourceType,
    ScrapedStatement,
    ScrapedTweet,
    ScrapedTranscript,
    ScrapeResult,
)
from scrapers.commission_scraper import CommissionScraper
from scrapers.twitter_scraper import TwitterScraper
from scrapers.genel_kurul_scraper import GenelKurulScraper
from scrapers.resmi_gazete_scraper import ResmiGazeteScraper
from scrapers.political_scraper import NewsScraper, ManualDataIngest

__all__ = [
    # Base
    "BaseScraper",
    "RateLimiter",
    "UserAgentRotator",
    "ProxyManager",
    "ProxyConfig",
    # Models
    "SourceType",
    "ScrapedStatement",
    "ScrapedTweet",
    "ScrapedTranscript",
    "ScrapeResult",
    # Scrapers
    "CommissionScraper",
    "TwitterScraper",
    "GenelKurulScraper",
    "ResmiGazeteScraper",
    "NewsScraper",
    "ManualDataIngest",
]
