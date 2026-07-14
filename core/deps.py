"""
FastAPI Dependency Injection for ReguSense.

Provides singleton instances of core services as FastAPI dependencies.
"""

from functools import lru_cache
from typing import Generator, Optional
import logging
import os
import secrets

from fastapi import Header, HTTPException, status

from config.settings import settings


@lru_cache
def get_memory():
    """
    Get PoliticalMemory singleton instance.
    
    Returns:
        PoliticalMemory instance for vector operations
    """
    from memory.vector_store import PoliticalMemory
    
    return PoliticalMemory(
        collection_name=settings.collection_name,
        persist_dir=settings.chromadb_dir,
        model_name=settings.embedding_model,
    )


@lru_cache
def get_analyzer():
    """
    Get GeminiAnalyst singleton instance.
    
    Returns:
        GeminiAnalyst instance for AI analysis
    
    Raises:
        ValueError: If GEMINI_API_KEY is not set
    """
    from intelligence.gemini_analyzer import GeminiAnalyst
    
    api_key = settings.api_key
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY environment variable is required. "
            "Set it in your .env file or environment."
        )
    
    return GeminiAnalyst(
        api_key=api_key,
        model=settings.gemini_model,
    )


def get_detector(
    memory=None,
    analyzer=None,
    top_k: int = 5,
    threshold: int = 70,
):
    """
    Get ContradictionDetector instance.
    
    This is not cached because it depends on configurable parameters.
    
    Args:
        memory: PoliticalMemory instance (uses singleton if None)
        analyzer: GeminiAnalyst instance (uses singleton if None)
        top_k: Number of historical matches to retrieve
        threshold: Contradiction score threshold
        
    Returns:
        ContradictionDetector instance
    """
    from intelligence.contradiction_engine import ContradictionDetector
    
    if memory is None:
        memory = get_memory()
    if analyzer is None:
        analyzer = get_analyzer()
    
    return ContradictionDetector(
        memory=memory,
        analyzer=analyzer,
        top_k=top_k,
        contradiction_threshold=threshold,
    )


def get_report_generator():
    """
    Get PDFGenerator instance.
    
    Returns:
        ReportGenerator instance for PDF generation
    """
    from reporting.pdf_generator import ReportGenerator
    
    return ReportGenerator()


# FastAPI dependency functions
async def verify_api_key(
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    """
    FastAPI dependency enforcing X-API-Key authentication.

    Clients must send the value of REGUSENSE_API_AUTH_KEY in the X-API-Key
    header. If no key is configured, requests are allowed but a warning is
    logged (development mode only — always configure a key in production).
    """
    if not settings.api_auth_key:
        logging.getLogger(__name__).warning(
            "REGUSENSE_API_AUTH_KEY is not set — API authentication is DISABLED. "
            "Configure it before exposing this service."
        )
        return

    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_auth_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Send it in the X-API-Key header.",
        )


async def memory_dependency():
    """FastAPI dependency for PoliticalMemory."""
    return get_memory()


async def analyzer_dependency():
    """FastAPI dependency for GeminiAnalyst."""
    return get_analyzer()


async def detector_dependency():
    """FastAPI dependency for ContradictionDetector."""
    return get_detector()
