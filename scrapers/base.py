"""
Scraper Base Infrastructure.

Provides shared utilities for all scrapers:
- BaseScraper with async context management
- RateLimiter for request throttling
- UserAgentRotator for random user-agents
- ProxyManager for proxy rotation
"""

import asyncio
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Any
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# User-Agent Rotation
# =============================================================================

class UserAgentRotator:
    """
    Rotates through a pool of realistic user-agents.
    
    Example:
        rotator = UserAgentRotator()
        ua = rotator.get_random()
    """
    
    # Modern browser user-agents (updated for 2024)
    USER_AGENTS = [
        # Chrome on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        # Chrome on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        # Firefox on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
        # Firefox on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        # Safari on macOS
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        # Edge on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    ]
    
    def __init__(self, custom_agents: Optional[list[str]] = None):
        """
        Initialize with optional custom user-agents.
        
        Args:
            custom_agents: Optional list of custom user-agents to use
        """
        self.agents = custom_agents or self.USER_AGENTS
        self._last_used: Optional[str] = None
    
    def get_random(self) -> str:
        """Get a random user-agent different from the last one."""
        available = [ua for ua in self.agents if ua != self._last_used]
        self._last_used = random.choice(available)
        return self._last_used
    
    def get_all(self) -> list[str]:
        """Get all available user-agents."""
        return self.agents.copy()


# =============================================================================
# Rate Limiter
# =============================================================================

class RateLimiter:
    """
    Token bucket rate limiter for controlling request frequency.
    
    Example:
        limiter = RateLimiter(max_requests=30, time_window=60)  # 30 req/min
        await limiter.acquire()  # Waits if limit reached
    """
    
    def __init__(
        self,
        max_requests: int = 30,
        time_window: float = 60.0,
        burst_size: Optional[int] = None,
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in time window
            time_window: Time window in seconds
            burst_size: Optional burst size (defaults to max_requests)
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.burst_size = burst_size or max_requests
        
        self._tokens = float(self.burst_size)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens, waiting if necessary.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            Time waited in seconds
        """
        async with self._lock:
            waited = 0.0
            
            while self._tokens < tokens:
                # Refill tokens based on elapsed time
                now = time.monotonic()
                elapsed = now - self._last_refill
                refill = (elapsed / self.time_window) * self.max_requests
                self._tokens = min(self.burst_size, self._tokens + refill)
                self._last_refill = now
                
                if self._tokens < tokens:
                    # Calculate wait time
                    needed = tokens - self._tokens
                    wait_time = (needed / self.max_requests) * self.time_window
                    wait_time = min(wait_time, self.time_window)
                    
                    logger.debug(f"Rate limit reached, waiting {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    waited += wait_time
            
            self._tokens -= tokens
            return waited
    
    @property
    def available_tokens(self) -> float:
        """Get current available tokens."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        refill = (elapsed / self.time_window) * self.max_requests
        return min(self.burst_size, self._tokens + refill)


# =============================================================================
# Proxy Manager
# =============================================================================

@dataclass
class ProxyConfig:
    """Proxy configuration."""
    server: str  # e.g., "http://proxy.example.com:8080"
    username: Optional[str] = None
    password: Optional[str] = None
    
    def to_playwright(self) -> dict:
        """Convert to Playwright proxy format."""
        config = {"server": self.server}
        if self.username:
            config["username"] = self.username
        if self.password:
            config["password"] = self.password
        return config


class ProxyManager:
    """
    Manages a pool of proxies with rotation and health checking.
    
    Example:
        manager = ProxyManager([
            ProxyConfig("http://proxy1:8080"),
            ProxyConfig("http://proxy2:8080"),
        ])
        proxy = manager.get_next()
    """
    
    def __init__(self, proxies: Optional[list[ProxyConfig]] = None):
        """
        Initialize with optional proxy list.
        
        Args:
            proxies: List of proxy configurations
        """
        self.proxies = proxies or []
        self._index = 0
        self._failed: set[str] = set()
    
    def add_proxy(self, proxy: ProxyConfig) -> None:
        """Add a proxy to the pool."""
        self.proxies.append(proxy)
    
    def get_next(self) -> Optional[ProxyConfig]:
        """Get next healthy proxy in rotation."""
        if not self.proxies:
            return None
        
        # Try to find a non-failed proxy
        for _ in range(len(self.proxies)):
            proxy = self.proxies[self._index]
            self._index = (self._index + 1) % len(self.proxies)
            
            if proxy.server not in self._failed:
                return proxy
        
        # All proxies failed, reset and try again
        logger.warning("All proxies failed, resetting failed list")
        self._failed.clear()
        return self.proxies[0] if self.proxies else None
    
    def mark_failed(self, proxy: ProxyConfig) -> None:
        """Mark a proxy as failed."""
        self._failed.add(proxy.server)
        logger.warning(f"Proxy marked as failed: {proxy.server}")
    
    def mark_healthy(self, proxy: ProxyConfig) -> None:
        """Mark a proxy as healthy."""
        self._failed.discard(proxy.server)
    
    @property
    def healthy_count(self) -> int:
        """Get count of healthy proxies."""
        return len(self.proxies) - len(self._failed)


# =============================================================================
# Base Scraper
# =============================================================================

class BaseScraper(ABC):
    """
    Abstract base class for all async Playwright scrapers.
    
    Provides:
    - Async context management for browser lifecycle
    - Rate limiting
    - User-agent rotation
    - Proxy support
    - Retry with exponential backoff
    
    Example:
        class MyScraper(BaseScraper):
            async def scrape(self):
                async with self._create_page() as page:
                    await page.goto("https://example.com")
                    return await page.content()
        
        async with MyScraper() as scraper:
            result = await scraper.scrape()
    """
    
    def __init__(
        self,
        headless: bool = True,
        rate_limit: Optional[RateLimiter] = None,
        proxy_manager: Optional[ProxyManager] = None,
        user_agent_rotator: Optional[UserAgentRotator] = None,
        max_retries: int = 3,
        page_timeout_ms: int = 30000,
    ):
        """
        Initialize base scraper.
        
        Args:
            headless: Run browser in headless mode
            rate_limit: Optional rate limiter
            proxy_manager: Optional proxy manager
            user_agent_rotator: Optional user-agent rotator
            max_retries: Maximum retry attempts
            page_timeout_ms: Page load timeout
        """
        self.headless = headless
        self.rate_limiter = rate_limit or RateLimiter()
        self.proxy_manager = proxy_manager
        self.ua_rotator = user_agent_rotator or UserAgentRotator()
        self.max_retries = max_retries
        self.page_timeout_ms = page_timeout_ms
        
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
    
    async def __aenter__(self):
        """Start browser on context enter."""
        await self._start_browser()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Close browser on context exit."""
        await self._close_browser()
    
    async def _start_browser(self) -> None:
        """Initialize Playwright and browser."""
        self._playwright = await async_playwright().start()
        
        # Get proxy config if available
        proxy = None
        if self.proxy_manager:
            proxy_config = self.proxy_manager.get_next()
            if proxy_config:
                proxy = proxy_config.to_playwright()
        
        # Launch browser
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        
        # Create context with user-agent
        self._context = await self._browser.new_context(
            user_agent=self.ua_rotator.get_random(),
            viewport={"width": 1920, "height": 1080},
            proxy=proxy,
        )
        
        logger.info("Browser started")
    
    async def _close_browser(self) -> None:
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        
        logger.info("Browser closed")
    
    @asynccontextmanager
    async def _create_page(self):
        """
        Create a new page with configured timeouts.
        
        Yields:
            Playwright Page object
        """
        if not self._context:
            raise RuntimeError("Browser not started. Use 'async with' context manager.")
        
        page = await self._context.new_page()
        page.set_default_timeout(self.page_timeout_ms)
        
        try:
            yield page
        finally:
            await page.close()
    
    async def _retry_with_backoff(
        self,
        coro_factory,
        operation_name: str = "operation",
    ) -> Any:
        """
        Retry an async operation with exponential backoff.
        
        Args:
            coro_factory: Callable that returns a coroutine
            operation_name: Name for logging
            
        Returns:
            Result of the coroutine
        """
        last_error = None
        
        for attempt in range(self.max_retries):
            try:
                # Apply rate limiting
                await self.rate_limiter.acquire()
                
                return await coro_factory()
                
            except Exception as e:
                last_error = e
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                
                logger.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{self.max_retries}): {e}. "
                    f"Retrying in {wait_time:.2f}s"
                )
                
                await asyncio.sleep(wait_time)
        
        raise last_error
    
    @abstractmethod
    async def scrape(self, *args, **kwargs) -> Any:
        """
        Main scraping method. Must be implemented by subclasses.
        """
        pass
