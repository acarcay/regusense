"""
FastAPI Dependency Injection for ReguSense.

Provides singleton instances of core services as FastAPI dependencies.
"""

from functools import lru_cache
from typing import Generator, Optional
import os

from core.config import settings


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
async def memory_dependency():
    """FastAPI dependency for PoliticalMemory."""
    return get_memory()


async def analyzer_dependency():
    """FastAPI dependency for GeminiAnalyst."""
    return get_analyzer()


async def detector_dependency():
    """FastAPI dependency for ContradictionDetector."""
    return get_detector()
