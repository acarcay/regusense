"""
Health and Stats API Routes.
"""

from fastapi import APIRouter, Depends

from api.schemas import HealthResponse, StatsResponse, SpeakersResponse
from core.deps import get_memory
from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Health & Stats"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Check if the API is running and healthy.",
)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse()


@router.get(
    "/api/v1/stats",
    response_model=StatsResponse,
    summary="Memory Statistics",
    description="Get statistics about the vector store.",
)
async def get_stats() -> StatsResponse:
    """Get memory statistics."""
    memory = get_memory()
    stats = memory.get_stats()
    
    return StatsResponse(
        collection_name=stats["collection_name"],
        document_count=stats["document_count"],
        persist_dir=str(stats["persist_dir"]),
        model_name=stats["model_name"],
    )


@router.get(
    "/api/v1/speakers",
    response_model=SpeakersResponse,
    summary="List Speakers",
    description="Get all unique speaker names in the database.",
)
async def list_speakers() -> SpeakersResponse:
    """List all speakers."""
    memory = get_memory()
    speakers = sorted(list(memory.get_unique_speakers()))
    
    return SpeakersResponse(
        speakers=speakers,
        count=len(speakers),
    )
