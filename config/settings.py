"""
ReguSense Settings Module.

Centralized configuration using Pydantic Settings for environment variable management.
"""

from pathlib import Path
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="REGUSENSE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # TBMM Configuration
    tbmm_base_url: str = "https://www.tbmm.gov.tr"
    
    # Scraper Configuration
    retry_attempts: int = 3
    retry_delay_seconds: float = 2.0
    page_timeout_ms: int = 30000
    navigation_timeout_ms: int = 60000
    
    # Browser Configuration
    headless: bool = True
    slow_mo: int = 0  # Milliseconds between actions (useful for debugging)
    
    # Data Directories
    data_dir: Path = Path("data")
    raw_contracts_dir: Path = Path("data/raw/contracts")
    processed_dir: Path = Path("data/processed")
    logs_dir: Path = Path("data/logs")
    
    # Gemini API
    gemini_api_key: str = ""
    gemini_model: str = "gemini-pro"
    
    def ensure_directories(self) -> None:
        """Create all required data directories if they don't exist."""
        for directory in [
            self.data_dir,
            self.raw_contracts_dir,
            self.processed_dir,
            self.logs_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)


# Singleton settings instance
settings: Final[Settings] = Settings()


# =============================================================================
# Commission Sources Dictionary
# =============================================================================
# Maps internal Commission Keys to specific TBMM Commission Transcript Page URLs.
# Each commission monitors different sectors and risk types.

COMMISSION_SOURCES: Final[dict[str, dict[str, str]]] = {
    # Main source for Taxes & Fines (Crucial for All Sectors)
    "PLAN_BUTCE": {
        "name": "Plan ve Bütçe Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "plan-ve-butce-komisyonu/f72877d1-b469-037b-e050-007f01005610"
        ),
        "sectors": ["CRYPTO", "FINTECH", "ENERGY", "AUTOMOTIVE", "ECOMMERCE"],
        "focus": "Vergi düzenlemeleri, bütçe tahsisatları, mali yaptırımlar",
    },
    
    # Source for Energy & E-Commerce Regulations
    "SANAYI_ENERJI": {
        "name": "Sanayi, Ticaret, Enerji Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/Icerik/"
            "ihtisas-komisyonlari-sanayi-ticaret-enerji-tabii-kaynaklar-bilgi-ve-teknoloji-komisyonu-hakkinda/"
            "sanayi-ticaret-enerji-tabii-kaynaklar-bilgi-ve-teknoloji-komisyonu/"
            "f72877d1-b474-037b-e050-007f01005610"
        ),
        "sectors": ["ENERGY", "ECOMMERCE", "FINTECH"],
        "focus": "Enerji düzenlemeleri, e-ticaret mevzuatı, teknoloji politikaları",
    },
    
    # Source for Automotive & Logistics
    "BAYINDIRLIK": {
        "name": "Bayındırlık, İmar, Ulaştırma ve Turizm Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "bayindirlik-imar-ulastirma-ve-turizm-komisyonu/"
            "f72877d1-b46a-037b-e050-007f01005610"
        ),
        "sectors": ["AUTOMOTIVE", "CONSTRUCTION", "LOGISTICS"],
        "focus": "Ulaştırma düzenlemeleri, otomotiv standartları, lojistik mevzuatı",
    },
    
    # Source for Digital Assets & Social Media Law
    "DIJITAL_MECRALAR": {
        "name": "Dijital Mecralar Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "dijital-mecralar-komisyonu/f72877d1-b4c7-037b-e050-007f01005610"
        ),
        "sectors": ["CRYPTO", "FINTECH", "ECOMMERCE"],
        "focus": "Dijital varlık düzenlemeleri, sosyal medya yasaları, veri koruma",
    },
    
    # Source for Penal Codes (Crypto Assets)
    "ADALET": {
        "name": "Adalet Komisyonu",
        "url": (
            "https://www.tbmm.gov.tr/ihtisas-komisyonlari/KomisyonTutanaklari/"
            "adalet-komisyonu/f72877d1-b46b-037b-e050-007f01005610"
        ),
        "sectors": ["CRYPTO", "FINTECH"],
        "focus": "Ceza hukuku, kripto varlık suçları, dolandırıcılık mevzuatı",
    },
}


# Default commission for backward compatibility
DEFAULT_COMMISSION: Final[str] = "ADALET"


# Helper function to get commission URL by key
def get_commission_url(key: str) -> str:
    """Get commission URL by key, with fallback to default."""
    commission = COMMISSION_SOURCES.get(key.upper(), COMMISSION_SOURCES[DEFAULT_COMMISSION])
    return commission["url"]


# Helper function to get all commission keys
def get_all_commissions() -> list[str]:
    """Get list of all available commission keys."""
    return list(COMMISSION_SOURCES.keys())


# Legacy compatibility alias
COMMISSION_URLS: Final[dict[str, str]] = {
    key.lower(): info["url"] for key, info in COMMISSION_SOURCES.items()
}

