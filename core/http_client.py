"""
Async HTTP Client for ReguSense.

Provides a configured httpx client with retries, timeouts, and logging.
"""

import asyncio
from typing import Any, Optional
from contextlib import asynccontextmanager

import httpx

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


class HTTPClientError(Exception):
    """Custom exception for HTTP client errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AsyncHTTPClient:
    """
    Async HTTP client with retries and connection pooling.
    
    Example:
        async with AsyncHTTPClient() as client:
            response = await client.get("https://example.com")
    """
    
    def __init__(
        self,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        headers: Optional[dict[str, str]] = None,
    ):
        """
        Initialize the HTTP client.
        
        Args:
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            retry_delay: Delay between retries in seconds
            headers: Default headers to include in all requests
        """
        self.timeout = httpx.Timeout(timeout)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.default_headers = headers or {
            "User-Agent": "ReguSense/1.0",
            "Accept": "application/json, text/html, */*",
        }
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self) -> "AsyncHTTPClient":
        """Start the client session."""
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            headers=self.default_headers,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
            ),
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Close the client session."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """
        Make a request with automatic retries.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL
            **kwargs: Additional arguments to pass to httpx
            
        Returns:
            httpx.Response object
            
        Raises:
            HTTPClientError: If all retries fail
        """
        if self._client is None:
            raise HTTPClientError("Client not initialized. Use 'async with' context manager.")
        
        last_exception: Optional[Exception] = None
        
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"HTTP {method} {url} (attempt {attempt + 1}/{self.max_retries})")
                
                response = await self._client.request(method, url, **kwargs)
                
                # Log response info
                logger.debug(f"HTTP {response.status_code} {url}")
                
                # Raise for 4xx/5xx status codes
                response.raise_for_status()
                
                return response
                
            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    raise HTTPClientError(
                        f"Client error: {e.response.status_code}",
                        status_code=e.response.status_code,
                    )
                last_exception = e
                
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_exception = e
                logger.warning(f"Request failed (attempt {attempt + 1}): {e}")
            
            # Wait before retrying
            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_delay * (attempt + 1))
        
        raise HTTPClientError(
            f"Request failed after {self.max_retries} attempts: {last_exception}"
        )
    
    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Make a GET request."""
        return await self._request_with_retry("GET", url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Make a POST request."""
        return await self._request_with_retry("POST", url, **kwargs)
    
    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Make a PUT request."""
        return await self._request_with_retry("PUT", url, **kwargs)
    
    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """Make a DELETE request."""
        return await self._request_with_retry("DELETE", url, **kwargs)
    
    async def download_file(
        self,
        url: str,
        output_path: str,
        chunk_size: int = 8192,
    ) -> str:
        """
        Download a file to disk.
        
        Args:
            url: URL of the file to download
            output_path: Path to save the file
            chunk_size: Size of chunks to download
            
        Returns:
            Path to the downloaded file
        """
        if self._client is None:
            raise HTTPClientError("Client not initialized. Use 'async with' context manager.")
        
        async with self._client.stream("GET", url) as response:
            response.raise_for_status()
            
            with open(output_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                    f.write(chunk)
        
        logger.info(f"Downloaded file: {output_path}")
        return output_path


@asynccontextmanager
async def get_http_client(**kwargs):
    """
    Context manager for getting an HTTP client.
    
    Example:
        async with get_http_client() as client:
            response = await client.get(url)
    """
    client = AsyncHTTPClient(**kwargs)
    async with client:
        yield client
