"""
Health and Stats API Routes.
"""

from fastapi import APIRouter, Depends

from api.schemas import HealthResponse, StatsResponse, SpeakersResponse
from core.deps import get_memory
from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Health & Stats"])


from fastapi import Response, status

@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Check if the API and backend services are running and healthy.",
)
async def health_check(response: Response) -> HealthResponse:
    """Detailed health check endpoint."""
    checks = {}
    errors = 0

    # PostgreSQL Check
    try:
        from database.session import get_engine
        from sqlalchemy import text
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = {"status": "ok", "detail": "connected"}
    except Exception as e:
        checks["postgres"] = {"status": "error", "detail": str(e)[:200]}
        errors += 1

    # Neo4j Check
    try:
        from database.neo4j_client import get_driver
        driver = await get_driver()
        await driver.verify_connectivity()
        checks["neo4j"] = {"status": "ok", "detail": "connected"}
    except Exception as e:
        checks["neo4j"] = {"status": "error", "detail": str(e)[:200]}
        errors += 1

    # ChromaDB Check
    try:
        from memory.vector_store import PoliticalMemory
        mem = PoliticalMemory()
        count = mem.count()
        checks["chromadb"] = {"status": "ok", "detail": f"{count} documents"}
    except Exception as e:
        checks["chromadb"] = {"status": "error", "detail": str(e)[:200]}
        errors += 1

    # Status aggregation
    if errors == 0:
        overall_status = "healthy"
        response.status_code = status.HTTP_200_OK
    elif errors < 3:
        overall_status = "degraded"
        response.status_code = status.HTTP_200_OK
    else:
        overall_status = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(status=overall_status, checks=checks)

@router.get("/health/ready", include_in_schema=False)
async def readiness_probe(response: Response):
    """Readiness probe for Kubernetes or Docker Healthcheck."""
    health_res = await health_check(response)
    if health_res.status != "healthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return None
    return {"status": "ready"}


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
