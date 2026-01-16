"""
ReguSense Extended Configuration.

Extends base settings with FastAPI, Redis, and Celery configuration.
"""

from functools import lru_cache
from pathlib import Path
from typing import Final, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="REGUSENSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================================================
    # API Configuration
    # ==========================================================================
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False
    api_title: str = "ReguSense API"
    api_version: str = "1.0.0"
    
    # CORS
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    
    # ==========================================================================
    # Redis Configuration
    # ==========================================================================
    redis_url: str = "redis://localhost:6379/0"
    
    # ==========================================================================
    # Celery Configuration
    # ==========================================================================
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"
    celery_task_track_started: bool = True
    celery_task_time_limit: int = 3600  # 1 hour
    
    # ==========================================================================
    # TBMM Configuration
    # ==========================================================================
    tbmm_base_url: str = "https://www.tbmm.gov.tr"
    
    # ==========================================================================
    # Scraper Configuration
    # ==========================================================================
    retry_attempts: int = 3
    retry_delay_seconds: float = 2.0
    page_timeout_ms: int = 30000
    navigation_timeout_ms: int = 60000
    
    # ==========================================================================
    # Browser Configuration
    # ==========================================================================
    headless: bool = True
    slow_mo: int = 0
    
    # ==========================================================================
    # Data Directories
    # ==========================================================================
    data_dir: Path = Path("data")
    raw_contracts_dir: Path = Path("data/raw/contracts")
    processed_dir: Path = Path("data/processed")
    logs_dir: Path = Path("data/logs")
    chromadb_dir: Path = Path("data/chromadb")
    
    # ==========================================================================
    # Gemini API
    # ==========================================================================
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    
    # ==========================================================================
    # Vector Store
    # ==========================================================================
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    collection_name: str = "political_statements"
    
    def ensure_directories(self) -> None:
        """Create all required data directories if they don't exist."""
        for directory in [
            self.data_dir,
            self.raw_contracts_dir,
            self.processed_dir,
            self.logs_dir,
            self.chromadb_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)
    
    @property
    def api_key(self) -> str:
        """Get Gemini API key with fallback to generic env var."""
        import os
        return self.gemini_api_key or os.environ.get("GEMINI_API_KEY", "")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Singleton for backward compatibility
settings: Final[Settings] = get_settings()
