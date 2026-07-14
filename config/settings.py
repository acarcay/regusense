"""
ReguSense Settings Module.

Single source of truth for configuration. All settings are loaded from
environment variables with the REGUSENSE_ prefix (see .env.example).

Note: core.config re-exports this module for backward compatibility —
do not add settings anywhere else.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Final

from pydantic import Field, model_validator
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

    # API authentication — clients must send this value in the X-API-Key header.
    # Empty value disables auth (development only; a warning is logged).
    api_auth_key: str = ""

    # CORS — explicit origins; never use ["*"] together with credentials.
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:8501",  # Streamlit dashboard
        ]
    )

    # ==========================================================================
    # Redis / Celery
    # ==========================================================================
    redis_url: str = "redis://localhost:6379/0"
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
    slow_mo: int = 0  # Milliseconds between actions (useful for debugging)

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
    # Tavily API (web search)
    # ==========================================================================
    tavily_api_key: str = ""

    # ==========================================================================
    # Vector Store
    # ==========================================================================
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    collection_name: str = "political_statements"

    # ==========================================================================
    # Neo4j (Graph Database)
    # ==========================================================================
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""  # Required — set REGUSENSE_NEO4J_PASSWORD in .env

    # ==========================================================================
    # PostgreSQL
    # ==========================================================================
    database_url: str = ""  # Required — set REGUSENSE_DATABASE_URL in .env

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
        """Gemini API key with fallback to the generic GEMINI_API_KEY env var."""
        return self.gemini_api_key or os.environ.get("GEMINI_API_KEY", "")

    @model_validator(mode="after")
    def warn_if_missing_secrets(self) -> "Settings":
        """Warn at startup when required secrets are not configured.

        Import stays non-fatal so tests and tooling can load the package;
        components that actually need a secret raise a clear error at use time
        (see database.session.get_engine and GeminiAnalyst).
        """
        missing = []
        if not self.neo4j_password:
            missing.append("REGUSENSE_NEO4J_PASSWORD")
        if not self.database_url:
            missing.append("REGUSENSE_DATABASE_URL")
        if not self.gemini_api_key:
            missing.append("REGUSENSE_GEMINI_API_KEY")
        if missing:
            import warnings
            warnings.warn(
                f"ReguSense: Missing required config: {missing}. "
                "Copy .env.example to .env and fill in the values.",
                stacklevel=2,
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Singleton settings instance
settings: Final[Settings] = get_settings()


# =============================================================================
# Commission Sources Dictionary - ALL 18 TBMM Specialty Commissions
# =============================================================================
# Maps internal Commission Keys to specific TBMM Commission Transcript Page URLs.

COMMISSION_SOURCES: Final[dict[str, dict[str, list[str] | str]]] = {
    # =========================================================================
    # PRIMARY COMMISSIONS (Most Relevant for Political Analysis)
    # =========================================================================

    "PLAN_BUTCE": {
        "name": "Plan ve Bütçe Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "plan-ve-butce-komisyonu/f72877d1-b469-037b-e050-007f01005610"
        ),
        "sectors": ["ECONOMY", "FINANCE", "BUDGET", "TAX"],
        "focus": "Vergi düzenlemeleri, bütçe tahsisatları, mali yaptırımlar",
    },

    "ADALET": {
        "name": "Adalet Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "adalet-komisyonu/f72877d1-b46b-037b-e050-007f01005610"
        ),
        "sectors": ["LAW", "JUSTICE", "CRIMINAL"],
        "focus": "Ceza hukuku, yargı düzenlemeleri, hukuk reformları",
    },

    "ANAYASA": {
        "name": "Anayasa Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "anayasa-komisyonu/f72877d1-b46c-037b-e050-007f01005610"
        ),
        "sectors": ["CONSTITUTION", "RIGHTS", "GOVERNANCE"],
        "focus": "Anayasa değişiklikleri, temel haklar, yönetim yapısı",
    },

    "SANAYI_ENERJI": {
        "name": "Sanayi, Ticaret, Enerji, Tabii Kaynaklar, Bilgi ve Teknoloji Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "sanayi-ticaret-enerji-tabii-kaynaklar-bilgi-ve-teknoloji-komisyonu/"
            "f72877d1-b474-037b-e050-007f01005610"
        ),
        "sectors": ["ENERGY", "TECH", "INDUSTRY", "COMMERCE"],
        "focus": "Enerji politikaları, sanayi düzenlemeleri, teknoloji",
    },

    "SAGLIK": {
        "name": "Sağlık, Aile, Çalışma ve Sosyal İşler Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "saglik-aile-calisma-ve-sosyal-isler-komisyonu/"
            "f72877d1-b475-037b-e050-007f01005610"
        ),
        "sectors": ["HEALTH", "SOCIAL", "LABOR", "FAMILY"],
        "focus": "Sağlık politikaları, iş hukuku, sosyal güvenlik",
    },

    "EGITIM": {
        "name": "Milli Eğitim, Kültür, Gençlik ve Spor Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "milli-egitim-kultur-genclik-ve-spor-komisyonu/"
            "f72877d1-b472-037b-e050-007f01005610"
        ),
        "sectors": ["EDUCATION", "CULTURE", "YOUTH", "SPORTS"],
        "focus": "Eğitim politikaları, kültür, gençlik",
    },

    # =========================================================================
    # SECONDARY COMMISSIONS
    # =========================================================================

    "BAYINDIRLIK": {
        "name": "Bayındırlık, İmar, Ulaştırma ve Turizm Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "bayindirlik-imar-ulastirma-ve-turizm-komisyonu/"
            "f72877d1-b46a-037b-e050-007f01005610"
        ),
        "sectors": ["TRANSPORT", "CONSTRUCTION", "TOURISM"],
        "focus": "Ulaştırma, imar, turizm düzenlemeleri",
    },

    "DIJITAL_MECRALAR": {
        "name": "Dijital Mecralar Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "dijital-mecralar-komisyonu/f72877d1-b4c7-037b-e050-007f01005610"
        ),
        "sectors": ["DIGITAL", "SOCIAL_MEDIA", "INTERNET"],
        "focus": "Dijital platformlar, sosyal medya, internet düzenlemeleri",
    },

    "ICISLERI": {
        "name": "İçişleri Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "icisleri-komisyonu/f72877d1-b46f-037b-e050-007f01005610"
        ),
        "sectors": ["SECURITY", "LOCAL_GOV", "CITIZENSHIP"],
        "focus": "İç güvenlik, yerel yönetimler, vatandaşlık",
    },

    "DISISLERI": {
        "name": "Dışişleri Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "disisleri-komisyonu/f72877d1-b468-037b-e050-007f01005610"
        ),
        "sectors": ["FOREIGN_POLICY", "DIPLOMACY", "TREATIES"],
        "focus": "Dış politika, uluslararası anlaşmalar",
    },

    "CEVRE": {
        "name": "Çevre Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "cevre-komisyonu/f72877d1-b46d-037b-e050-007f01005610"
        ),
        "sectors": ["ENVIRONMENT", "CLIMATE", "SUSTAINABILITY"],
        "focus": "Çevre politikaları, iklim, sürdürülebilirlik",
    },

    "TARIM": {
        "name": "Tarım, Orman ve Köyişleri Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "tarim-orman-ve-koyisleri-komisyonu/f72877d1-b476-037b-e050-007f01005610"
        ),
        "sectors": ["AGRICULTURE", "FORESTRY", "RURAL"],
        "focus": "Tarım politikaları, orman, köy kalkınması",
    },

    "SAVUNMA": {
        "name": "Milli Savunma Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "milli-savunma-komisyonu/f72877d1-b477-037b-e050-007f01005610"
        ),
        "sectors": ["DEFENSE", "MILITARY", "SECURITY"],
        "focus": "Savunma politikaları, askeri düzenlemeler",
    },

    "AB_UYUM": {
        "name": "Avrupa Birliği Uyum Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "avrupa-birligi-uyum-komisyonu/f72877d1-b47a-037b-e050-007f01005610"
        ),
        "sectors": ["EU", "HARMONIZATION", "INTERNATIONAL"],
        "focus": "AB mevzuatı uyumu, uluslararası standartlar",
    },

    "INSAN_HAKLARI": {
        "name": "İnsan Haklarını İnceleme Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "insan-haklarini-inceleme-komisyonu/f72877d1-b470-037b-e050-007f01005610"
        ),
        "sectors": ["HUMAN_RIGHTS", "CIVIL_LIBERTIES"],
        "focus": "İnsan hakları, sivil özgürlükler",
    },

    "KADIN_ERKEK": {
        "name": "Kadın Erkek Fırsat Eşitliği Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "kadin-erkek-firsat-esitligi-komisyonu/f72877d1-b499-037b-e050-007f01005610"
        ),
        "sectors": ["GENDER", "EQUALITY", "WOMEN"],
        "focus": "Cinsiyet eşitliği, kadın hakları",
    },

    "KIT": {
        "name": "Kamu İktisadi Teşebbüsleri Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "kamu-iktisadi-tesebbusleri-komisyonu/f72877d1-b471-037b-e050-007f01005610"
        ),
        "sectors": ["STATE_ENTERPRISES", "PUBLIC_SECTOR"],
        "focus": "Kamu işletmeleri, devlet teşebbüsleri",
    },

    "DILEKCE": {
        "name": "Dilekçe Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "dilekce-komisyonu/f72877d1-b46e-037b-e050-007f01005610"
        ),
        "sectors": ["PETITIONS", "CITIZENS"],
        "focus": "Vatandaş dilekçeleri, şikayetler",
    },

    "GUVENLIK": {
        "name": "Güvenlik ve İstihbarat Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "guvenlik-ve-istihbarat-komisyonu/f72877d1-b460-037b-e050-007f01005610"
        ),
        "sectors": ["INTELLIGENCE", "NATIONAL_SECURITY"],
        "focus": "İstihbarat, ulusal güvenlik",
    },
}


# Default commission for backward compatibility
DEFAULT_COMMISSION: Final[str] = "ADALET"


# Helper function to get commission URL by key
def get_commission_url(key: str) -> str:
    """Get commission URL by key, with fallback to default."""
    commission = COMMISSION_SOURCES.get(key.upper(), COMMISSION_SOURCES[DEFAULT_COMMISSION])
    return str(commission["url"])


# Helper function to get all commission keys
def get_all_commissions() -> list[str]:
    """Get list of all available commission keys."""
    return list(COMMISSION_SOURCES.keys())


# Legacy compatibility alias
COMMISSION_URLS: Final[dict[str, str]] = {
    key.lower(): str(info["url"]) for key, info in COMMISSION_SOURCES.items()
}
