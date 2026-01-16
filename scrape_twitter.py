"""
Smart Twitter/X Scraper for Political Statements.

Features:
- Scrapes tweets from specific politicians
- Filters out protocol/ceremonial tweets (holidays, commemorations, etc.)
- Extracts substantive political statements only
- Outputs JSON format compatible with ingest_archives.py

Note: Due to Twitter API restrictions, this uses alternative methods:
1. Nitter (Twitter alternative frontend)
2. Archived Twitter data (if available)
3. Manual JSON import

Author: ReguSense Team
"""

import json
import logging
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Protocol/Ceremonial Tweet Filter
# ============================================================================

class ProtocolTweetFilter:
    """
    Filters out ceremonial/protocol tweets that don't contain 
    substantive political statements.
    
    Filters:
    - Holiday greetings (Bayram, Yılbaşı, Ramazan)
    - Commemoration days (19 Mayıs, 29 Ekim, 10 Kasım)
    - Condolences (Taziye, Başsağlığı)
    - General greetings (Hayırlı Cumalar, Günaydın)
    - Event announcements without policy content
    """
    
    # Patterns indicating protocol/ceremonial content
    PROTOCOL_PATTERNS = [
        # Holidays
        r"bayram[ıi]n[ıi]z?\s*(kutlu|mübarek)",
        r"(ramazan|kurban)\s*bayram",
        r"yeni\s*y[ıi]l[ıi]n[ıi]z",
        r"y[ıi]lba[şs][ıi]",
        r"(mutlu|nice)\s*y[ıi]llar",
        
        # Commemoration days
        r"10\s*kas[ıi]m",
        r"atatürk['ü]?\s*(anma|saygı|özlem)",
        r"19\s*may[ıi]s",
        r"23\s*nisan",
        r"29\s*ekim",
        r"30\s*a[ğg]ustos",
        r"15\s*temmuz",
        r"gazi\s*mustafa\s*kemal",
        r"ebediyete\s*intikal",
        r"ruhlar[ıi]\s*şad\s*olsun",
        r"şehit(ler)?imiz",
        r"gazilerimiz",
        
        # Religious greetings
        r"hay[ıi]rl[ıi]\s*cumalar",
        r"hay[ıi]rl[ıi]\s*kandil",
        r"mevlid\s*kandili",
        r"regaip\s*kandili",
        r"kadir\s*gecesi",
        r"cuma\s*m[üu]barek",
        
        # Condolences
        r"ba[şs]sa[ğg]l[ıi][ğg][ıi]",
        r"taziye(ler)?",
        r"hay[ıi]r\s*duas[ıi]",
        r"allah\s*rahmet\s*eylesin",
        r"mekan[ıi]\s*cennet\s*olsun",
        
        # General greetings
        r"günayd[ıi]n",
        r"iyi\s*geceler",
        r"iyi\s*hafta\s*sonlar[ıi]",
        r"iyi\s*ak[şs]amlar",
        r"iyi\s*haftalar",
        
        # Celebration/Congratulation
        r"tebrik(ler)?[ie]m",
        r"kutluyorum",
        r"kutlu\s*olsun",
        r"hay[ıi]rl[ıi]\s*olsun",
        r"başar[ıi]lar\s*diliyorum",
        
        # Sports/Entertainment
        r"maç(ı|ta)\s*(kazand|kazan|başarı)",
        r"şampiyon(luk)?",
        r"milli\s*tak[ıi]m",
        r"gol\s*att[ıi]",
        
        # Birthday/Anniversary
        r"do[ğg]um\s*gün[üu]",
        r"y[ıi]l\s*dön[üu]m[üu]",
        r"nice\s*y[ıi]llara",
        
        # Thank you / Appreciation (without substance)
        r"^te[şs]ekk[üu]r(ler)?\s*$",
        r"^sa[ğg]ol(un)?\s*$",
        
        # Event attendance without policy
        r"ziyaret\s*ett[ik]",
        r"bir\s*arada\s*olduk",
        r"toplant[ıi]s[ıi]na\s*kat[ıi]ld[ıi]",
    ]
    
    # Keywords that indicate substantive political content (keep these tweets)
    POLITICAL_KEYWORDS = [
        r"ekonomi",
        r"enflasyon",
        r"faiz",
        r"vergi",
        r"b[üu]tçe",
        r"kanun",
        r"yasa",
        r"meclis",
        r"komisyon",
        r"hükümet",
        r"muhalefet",
        r"seçim",
        r"oy",
        r"siyaset",
        r"politika",
        r"reform",
        r"değişiklik",
        r"tasarı",
        r"teklif",
        r"önerge",
        r"maa[şs]",
        r"asgari\s*[üu]cret",
        r"emekli",
        r"sosyal\s*güvenlik",
        r"sağlık",
        r"eğitim",
        r"tarım",
        r"sanayi",
        r"ihracat",
        r"ithalat",
        r"dolar",
        r"euro",
        r"kur",
        r"merkez\s*bankas[ıi]",
        r"tcmb",
        r"imf",
        r"dünya\s*bankas[ıi]",
        r"avrupa\s*birli[ğg]i",
        r"nato",
        r"suriye",
        r"irak",
        r"yunanistan",
        r"abd",
        r"rusya",
        r"çin",
        r"ukray[i]?na",
        r"güvenlik",
        r"terör",
        r"pkk",
        r"fetö",
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
    
    def is_protocol_tweet(self, text: str) -> bool:
        """
        Check if a tweet is a protocol/ceremonial tweet.
        
        Args:
            text: Tweet text
            
        Returns:
            True if tweet is protocol/ceremonial (should be filtered)
        """
        if not text:
            return True
        
        text = text.strip()
        
        # Very short tweets are usually greetings
        if len(text) < 20:
            return True
        
        # Check for political keywords - if present, keep the tweet
        for pattern in self.political_patterns:
            if pattern.search(text):
                return False  # Has political content, keep it
        
        # Check for protocol patterns
        for pattern in self.protocol_patterns:
            if pattern.search(text):
                return True  # Is protocol, filter it
        
        return False  # Default: keep the tweet
    
    def filter_tweets(self, tweets: list[dict]) -> list[dict]:
        """
        Filter a list of tweets, removing protocol/ceremonial ones.
        
        Args:
            tweets: List of tweet dictionaries with 'text' field
            
        Returns:
            Filtered list of tweets
        """
        filtered = []
        for tweet in tweets:
            text = tweet.get("text", "") or tweet.get("full_text", "")
            if not self.is_protocol_tweet(text):
                filtered.append(tweet)
        
        logger.info(f"Filtered {len(tweets)} -> {len(filtered)} tweets")
        return filtered


# ============================================================================
# Twitter Data Classes
# ============================================================================

@dataclass
class Tweet:
    """A single tweet."""
    id: str
    text: str
    created_at: str
    username: str
    display_name: str
    retweets: int = 0
    likes: int = 0
    is_retweet: bool = False
    url: str = ""


# ============================================================================
# Nitter Scraper (Alternative Twitter Frontend)
# ============================================================================

class NitterScraper:
    """
    Scraper using Nitter instances (alternative Twitter frontend).
    
    Nitter is an open-source Twitter frontend that can be used for scraping
    without Twitter API access.
    
    Example:
        >>> scraper = NitterScraper()
        >>> tweets = scraper.get_user_tweets("yaborali", max_tweets=100)
    """
    
    # Public Nitter instances - may change over time
    NITTER_INSTANCES = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.1d4.us",
        "https://nitter.kavin.rocks",
    ]
    
    def __init__(self, rate_limit: float = 2.0):
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36",
        })
        self._working_instance = None
    
    def _find_working_instance(self) -> Optional[str]:
        """Find a working Nitter instance."""
        for instance in self.NITTER_INSTANCES:
            try:
                response = self.session.get(f"{instance}/", timeout=10)
                if response.status_code == 200:
                    logger.info(f"Using Nitter instance: {instance}")
                    return instance
            except:
                continue
        return None
    
    @property
    def base_url(self) -> str:
        """Get working Nitter instance URL."""
        if not self._working_instance:
            self._working_instance = self._find_working_instance()
        return self._working_instance or self.NITTER_INSTANCES[0]
    
    def get_user_tweets(
        self,
        username: str,
        max_tweets: int = 100,
    ) -> list[Tweet]:
        """
        Get tweets from a user's timeline.
        
        Args:
            username: Twitter username (without @)
            max_tweets: Maximum tweets to retrieve
            
        Returns:
            List of Tweet objects
        """
        tweets = []
        cursor = ""
        
        while len(tweets) < max_tweets:
            url = f"{self.base_url}/{username}"
            if cursor:
                url += f"?cursor={cursor}"
            
            try:
                response = self.session.get(url, timeout=30)
                if response.status_code != 200:
                    logger.warning(f"Failed to fetch: {url}")
                    break
            except requests.RequestException as e:
                logger.error(f"Request failed: {e}")
                break
            
            soup = BeautifulSoup(response.text, "lxml")
            
            # Parse tweets
            for tweet_elem in soup.select(".timeline-item"):
                if len(tweets) >= max_tweets:
                    break
                
                # Get tweet text
                text_elem = tweet_elem.select_one(".tweet-content")
                if not text_elem:
                    continue
                
                text = text_elem.get_text(strip=True)
                
                # Get tweet ID from link
                tweet_link = tweet_elem.select_one(".tweet-link")
                tweet_id = ""
                tweet_url = ""
                if tweet_link:
                    href = tweet_link.get("href", "")
                    tweet_id = href.split("/")[-1].split("#")[0]
                    tweet_url = f"https://twitter.com{href}"
                
                # Get timestamp
                time_elem = tweet_elem.select_one(".tweet-date a")
                created_at = time_elem.get("title", "") if time_elem else ""
                
                # Get stats
                stats = tweet_elem.select(".tweet-stat")
                retweets = 0
                likes = 0
                for stat in stats:
                    stat_text = stat.get_text(strip=True)
                    if "retweet" in stat.get("class", []):
                        retweets = self._parse_stat(stat_text)
                    elif "heart" in str(stat):
                        likes = self._parse_stat(stat_text)
                
                # Check if retweet
                is_retweet = bool(tweet_elem.select_one(".retweet-header"))
                
                tweets.append(Tweet(
                    id=tweet_id,
                    text=text,
                    created_at=created_at,
                    username=username,
                    display_name=username,
                    retweets=retweets,
                    likes=likes,
                    is_retweet=is_retweet,
                    url=tweet_url,
                ))
            
            # Find next page cursor
            show_more = soup.select_one(".show-more a")
            if show_more:
                cursor = show_more.get("href", "").split("cursor=")[-1]
            else:
                break
            
            time.sleep(self.rate_limit)
        
        return tweets
    
    def _parse_stat(self, text: str) -> int:
        """Parse tweet stat (e.g., '1.2K' -> 1200)."""
        text = text.strip().replace(",", "")
        if "K" in text:
            return int(float(text.replace("K", "")) * 1000)
        elif "M" in text:
            return int(float(text.replace("M", "")) * 1000000)
        try:
            return int(text)
        except:
            return 0


# ============================================================================
# Twitter Archive Importer
# ============================================================================

class TwitterArchiveImporter:
    """
    Import tweets from Twitter archive export (Download Your Data).
    
    Twitter allows users to download their data as a ZIP file containing
    tweets.js with all their tweets.
    
    Example:
        >>> importer = TwitterArchiveImporter()
        >>> tweets = importer.import_archive("twitter_archive/data/tweets.js")
    """
    
    def import_archive(self, archive_path: str) -> list[Tweet]:
        """
        Import tweets from Twitter archive file.
        
        Args:
            archive_path: Path to tweets.js file from Twitter archive
            
        Returns:
            List of Tweet objects
        """
        path = Path(archive_path)
        if not path.exists():
            logger.error(f"Archive file not found: {archive_path}")
            return []
        
        # Read file
        content = path.read_text(encoding="utf-8")
        
        # Remove JavaScript wrapper
        # tweets.js starts with "window.YTD.tweets.part0 = ["
        content = re.sub(r"^window\.YTD\.tweets\.part\d+\s*=\s*", "", content)
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            return []
        
        tweets = []
        for item in data:
            tweet_data = item.get("tweet", item)
            
            tweets.append(Tweet(
                id=tweet_data.get("id_str", ""),
                text=tweet_data.get("full_text", tweet_data.get("text", "")),
                created_at=tweet_data.get("created_at", ""),
                username=tweet_data.get("user", {}).get("screen_name", ""),
                display_name=tweet_data.get("user", {}).get("name", ""),
                retweets=int(tweet_data.get("retweet_count", 0)),
                likes=int(tweet_data.get("favorite_count", 0)),
                is_retweet="retweeted_status" in tweet_data,
            ))
        
        logger.info(f"Imported {len(tweets)} tweets from archive")
        return tweets


# ============================================================================
# Main Scraper Class
# ============================================================================

class SmartTwitterScraper:
    """
    Smart Twitter scraper that filters out protocol tweets.
    
    Example:
        >>> scraper = SmartTwitterScraper(output_dir="data/raw/twitter")
        >>> scraper.scrape_user("yaborali", max_tweets=500)
    """
    
    def __init__(
        self,
        output_dir: str = "data/raw/twitter",
        filter_protocol: bool = True,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.filter_protocol = filter_protocol
        self.tweet_filter = ProtocolTweetFilter()
        self.nitter_scraper = NitterScraper()
        self.archive_importer = TwitterArchiveImporter()
    
    def scrape_user(
        self,
        username: str,
        max_tweets: int = 500,
        source: str = "nitter",
    ) -> dict:
        """
        Scrape tweets from a user.
        
        Args:
            username: Twitter username
            max_tweets: Maximum tweets to fetch
            source: "nitter" or path to archive file
            
        Returns:
            Stats dictionary
        """
        logger.info(f"Scraping @{username}")
        
        # Get tweets
        if source == "nitter":
            tweets = self.nitter_scraper.get_user_tweets(username, max_tweets)
        else:
            tweets = self.archive_importer.import_archive(source)
        
        logger.info(f"Retrieved {len(tweets)} tweets")
        
        # Convert to dicts for filtering
        tweet_dicts = [asdict(t) for t in tweets]
        
        # Filter retweets
        original_tweets = [t for t in tweet_dicts if not t.get("is_retweet")]
        logger.info(f"After removing retweets: {len(original_tweets)}")
        
        # Filter protocol tweets if enabled
        if self.filter_protocol:
            filtered_tweets = self.tweet_filter.filter_tweets(original_tweets)
        else:
            filtered_tweets = original_tweets
        
        logger.info(f"After protocol filter: {len(filtered_tweets)}")
        
        # Save to JSON
        output_file = self.output_dir / f"{username}_tweets.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(filtered_tweets, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved to {output_file}")
        
        return {
            "username": username,
            "total_fetched": len(tweets),
            "after_retweet_filter": len(original_tweets),
            "after_protocol_filter": len(filtered_tweets),
            "output_file": str(output_file),
        }
    
    def scrape_politicians(
        self,
        usernames: list[str],
        max_tweets_per_user: int = 500,
    ) -> list[dict]:
        """
        Scrape multiple politician accounts.
        
        Args:
            usernames: List of Twitter usernames
            max_tweets_per_user: Max tweets per user
            
        Returns:
            List of stats dicts
        """
        results = []
        for username in usernames:
            try:
                stats = self.scrape_user(username, max_tweets_per_user)
                results.append(stats)
            except Exception as e:
                logger.error(f"Failed to scrape @{username}: {e}")
                results.append({
                    "username": username,
                    "error": str(e),
                })
            time.sleep(3)  # Rate limit between users
        
        return results


# ============================================================================
# CLI
# ============================================================================

def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Smart Twitter scraper for political statements"
    )
    parser.add_argument(
        "usernames",
        nargs="+",
        help="Twitter usernames to scrape (without @)",
    )
    parser.add_argument(
        "--max-tweets", "-m",
        type=int,
        default=500,
        help="Maximum tweets per user (default: 500)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="data/raw/twitter",
        help="Output directory",
    )
    parser.add_argument(
        "--no-filter",
        action="store_true",
        help="Don't filter protocol tweets",
    )
    parser.add_argument(
        "--archive",
        type=str,
        help="Path to Twitter archive file (tweets.js)",
    )
    
    args = parser.parse_args()
    
    scraper = SmartTwitterScraper(
        output_dir=args.output,
        filter_protocol=not args.no_filter,
    )
    
    if args.archive:
        # Import from archive
        for username in args.usernames:
            scraper.scrape_user(
                username,
                max_tweets=args.max_tweets,
                source=args.archive,
            )
    else:
        # Scrape from Nitter
        results = scraper.scrape_politicians(
            args.usernames,
            max_tweets_per_user=args.max_tweets,
        )
        
        print("\n=== SONUÇ ===")
        for r in results:
            if "error" in r:
                print(f"❌ @{r['username']}: {r['error']}")
            else:
                print(f"✅ @{r['username']}: {r['after_protocol_filter']} tweet")


if __name__ == "__main__":
    main()
