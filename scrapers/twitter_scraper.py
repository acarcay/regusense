"""
Modern Async Twitter/X Scraper.

Features:
- Playwright async for dynamic content
- Rate limiting (30 req/min)
- User-agent rotation
- Proxy support
- Pydantic validation
- Async vector store ingestion
- Protocol tweet filtering

Author: ReguSense Team
"""

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from scrapers.base import BaseScraper, RateLimiter, UserAgentRotator, ProxyManager
from scrapers.models import ScrapedTweet, ScrapedStatement, ScrapeResult, SourceType
from core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Protocol Tweet Filter
# =============================================================================

class ProtocolTweetFilter:
    """
    Filters out ceremonial/protocol tweets.
    
    Filters:
    - Holiday greetings
    - Commemoration days
    - Condolences
    - General greetings
    """
    
    PROTOCOL_PATTERNS = [
        # Holidays
        r"bayram[ıi]n[ıi]z?\s*(kutlu|mübarek)",
        r"(ramazan|kurban)\s*bayram",
        r"yeni\s*y[ıi]l[ıi]n[ıi]z",
        r"(mutlu|nice)\s*y[ıi]llar",
        
        # Commemoration
        r"10\s*kas[ıi]m",
        r"atatürk['ü]?\s*(anma|saygı|özlem)",
        r"19\s*may[ıi]s",
        r"23\s*nisan",
        r"29\s*ekim",
        r"30\s*a[ğg]ustos",
        r"15\s*temmuz",
        
        # Religious
        r"hay[ıi]rl[ıi]\s*cumalar",
        r"hay[ıi]rl[ıi]\s*kandil",
        r"kadir\s*gecesi",
        
        # Condolences
        r"ba[şs]sa[ğg]l[ıi][ğg][ıi]",
        r"taziye",
        r"allah\s*rahmet",
        
        # Greetings
        r"^günayd[ıi]n\s*$",
        r"^iyi\s*geceler\s*$",
    ]
    
    POLITICAL_KEYWORDS = [
        r"ekonomi", r"enflasyon", r"faiz", r"vergi", r"b[üu]tçe",
        r"kanun", r"yasa", r"meclis", r"komisyon", r"hükümet",
        r"seçim", r"reform", r"maa[şs]", r"asgari\s*[üu]cret",
    ]
    
    def __init__(self):
        self.protocol_patterns = [
            re.compile(p, re.IGNORECASE | re.UNICODE)
            for p in self.PROTOCOL_PATTERNS
        ]
        self.political_patterns = [
            re.compile(p, re.IGNORECASE | re.UNICODE)
            for p in self.POLITICAL_KEYWORDS
        ]
    
    def is_protocol(self, text: str) -> bool:
        """Check if tweet is protocol/ceremonial."""
        if not text or len(text.strip()) < 20:
            return True
        
        # Keep if has political keywords
        for pattern in self.political_patterns:
            if pattern.search(text):
                return False
        
        # Filter if matches protocol patterns
        for pattern in self.protocol_patterns:
            if pattern.search(text):
                return True
        
        return False


# =============================================================================
# Twitter Scraper
# =============================================================================

class TwitterScraper(BaseScraper):
    """
    Async Playwright-based Twitter/X scraper.
    
    Uses Nitter instances as alternative frontend for scraping
    without Twitter API access.
    
    Example:
        async with TwitterScraper() as scraper:
            result = await scraper.scrape_user("yaborali", max_tweets=100)
    """
    
    NITTER_INSTANCES = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.1d4.us",
    ]
    
    def __init__(
        self,
        output_dir: str = "data/raw/twitter",
        filter_protocol: bool = True,
        rate_limit: Optional[RateLimiter] = None,
        proxy_manager: Optional[ProxyManager] = None,
        headless: bool = True,
    ):
        """
        Initialize Twitter scraper.
        
        Args:
            output_dir: Directory to save scraped data
            filter_protocol: Filter out protocol tweets
            rate_limit: Custom rate limiter (default: 30 req/min)
            proxy_manager: Optional proxy manager
            headless: Run browser headless
        """
        super().__init__(
            headless=headless,
            rate_limit=rate_limit or RateLimiter(max_requests=30, time_window=60),
            proxy_manager=proxy_manager,
            max_retries=3,
            page_timeout_ms=30000,
        )
        
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.filter_protocol = filter_protocol
        self.tweet_filter = ProtocolTweetFilter()
        self._working_instance: Optional[str] = None
    
    async def _find_working_instance(self) -> Optional[str]:
        """Find a working Nitter instance."""
        async with self._create_page() as page:
            for instance in self.NITTER_INSTANCES:
                try:
                    await self.rate_limiter.acquire()
                    response = await page.goto(f"{instance}/", wait_until="domcontentloaded")
                    if response and response.ok:
                        logger.info(f"Using Nitter instance: {instance}")
                        return instance
                except Exception as e:
                    logger.debug(f"Instance {instance} failed: {e}")
                    continue
        return None
    
    async def scrape_user(
        self,
        username: str,
        max_tweets: int = 100,
        ingest_to_memory: bool = True,
    ) -> ScrapeResult:
        """
        Scrape tweets from a user.
        
        Args:
            username: Twitter username (without @)
            max_tweets: Maximum tweets to fetch
            ingest_to_memory: Send to vector store after scraping
            
        Returns:
            ScrapeResult with statistics
        """
        start_time = datetime.now()
        tweets: list[ScrapedTweet] = []
        
        if not self._working_instance:
            self._working_instance = await self._find_working_instance()
            if not self._working_instance:
                return ScrapeResult(
                    success=False,
                    error="No working Nitter instance found",
                )
        
        try:
            async with self._create_page() as page:
                cursor = ""
                
                while len(tweets) < max_tweets:
                    url = f"{self._working_instance}/{username}"
                    if cursor:
                        url += f"?cursor={cursor}"
                    
                    async def fetch_page():
                        await page.goto(url, wait_until="domcontentloaded")
                        return await page.content()
                    
                    html = await self._retry_with_backoff(fetch_page, "fetch timeline")
                    
                    # Parse tweets
                    page_tweets = await self._parse_tweets(page, username)
                    
                    if not page_tweets:
                        break
                    
                    tweets.extend(page_tweets)
                    
                    # Get next cursor
                    cursor = await self._get_next_cursor(page)
                    if not cursor:
                        break
                    
                    # Small delay between pages
                    await asyncio.sleep(1)
            
            # Filter and validate
            valid_tweets = []
            for tweet in tweets[:max_tweets]:
                if tweet.is_retweet:
                    continue
                if self.filter_protocol and self.tweet_filter.is_protocol(tweet.text):
                    continue
                valid_tweets.append(tweet)
            
            # Save to JSON
            output_file = self.output_dir / f"{username}_tweets.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(
                    [t.model_dump() for t in valid_tweets],
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            
            # Ingest to vector store
            ingested = 0
            if ingest_to_memory and valid_tweets:
                ingested = await self._ingest_tweets(valid_tweets)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            logger.info(
                f"Scraped @{username}: {len(tweets)} found, "
                f"{len(valid_tweets)} valid, {ingested} ingested"
            )
            
            return ScrapeResult(
                success=True,
                items_found=len(tweets),
                items_saved=len(valid_tweets),
                items_ingested=ingested,
                duration_seconds=duration,
                saved_path=str(output_file),
            )
            
        except Exception as e:
            logger.exception(f"Failed to scrape @{username}")
            return ScrapeResult(
                success=False,
                error=str(e),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
            )
    
    async def _parse_tweets(self, page, username: str) -> list[ScrapedTweet]:
        """Parse tweets from page content."""
        tweets = []
        
        # Get all tweet containers
        tweet_elements = await page.query_selector_all(".timeline-item")
        
        for elem in tweet_elements:
            try:
                # Get text
                text_elem = await elem.query_selector(".tweet-content")
                if not text_elem:
                    continue
                text = await text_elem.inner_text()
                
                # Get ID from link
                link_elem = await elem.query_selector(".tweet-link")
                tweet_id = ""
                tweet_url = ""
                if link_elem:
                    href = await link_elem.get_attribute("href") or ""
                    tweet_id = href.split("/")[-1].split("#")[0]
                    tweet_url = f"https://twitter.com{href}"
                
                # Get timestamp
                time_elem = await elem.query_selector(".tweet-date a")
                created_at = ""
                if time_elem:
                    created_at = await time_elem.get_attribute("title") or ""
                
                # Check if retweet
                retweet_header = await elem.query_selector(".retweet-header")
                is_retweet = retweet_header is not None
                
                tweets.append(ScrapedTweet(
                    id=tweet_id,
                    text=text.strip(),
                    username=username,
                    display_name=username,
                    created_at=created_at,
                    is_retweet=is_retweet,
                    url=tweet_url,
                ))
                
            except Exception as e:
                logger.debug(f"Failed to parse tweet: {e}")
                continue
        
        return tweets
    
    async def _get_next_cursor(self, page) -> Optional[str]:
        """Get next page cursor."""
        show_more = await page.query_selector(".show-more a")
        if show_more:
            href = await show_more.get_attribute("href") or ""
            if "cursor=" in href:
                return href.split("cursor=")[-1]
        return None
    
    async def _ingest_tweets(self, tweets: list[ScrapedTweet]) -> int:
        """Ingest tweets to vector store."""
        try:
            from core.deps import get_memory
            
            memory = get_memory()
            statements = [t.to_statement().to_ingest_dict() for t in tweets]
            
            ids = memory.ingest_batch(statements)
            return len(ids)
            
        except Exception as e:
            logger.error(f"Failed to ingest tweets: {e}")
            return 0
    
    async def scrape(
        self,
        usernames: list[str],
        max_tweets_per_user: int = 100,
    ) -> list[ScrapeResult]:
        """
        Scrape multiple users.
        
        Args:
            usernames: List of usernames
            max_tweets_per_user: Max tweets per user
            
        Returns:
            List of ScrapeResults
        """
        results = []
        
        for username in usernames:
            result = await self.scrape_user(username, max_tweets_per_user)
            results.append(result)
            await asyncio.sleep(2)  # Rate limit between users
        
        return results


# =============================================================================
# CLI
# =============================================================================

async def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Modern Twitter Scraper")
    parser.add_argument("usernames", nargs="+", help="Twitter usernames")
    parser.add_argument("--max-tweets", "-m", type=int, default=100)
    parser.add_argument("--output", "-o", default="data/raw/twitter")
    parser.add_argument("--no-filter", action="store_true")
    parser.add_argument("--no-ingest", action="store_true")
    
    args = parser.parse_args()
    
    async with TwitterScraper(
        output_dir=args.output,
        filter_protocol=not args.no_filter,
    ) as scraper:
        for username in args.usernames:
            result = await scraper.scrape_user(
                username,
                max_tweets=args.max_tweets,
                ingest_to_memory=not args.no_ingest,
            )
            
            if result.success:
                print(f"✅ @{username}: {result.items_saved} tweets saved")
            else:
                print(f"❌ @{username}: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
