"""
Data Ingestion API Routes.
"""

from fastapi import APIRouter, HTTPException, UploadFile, File
from pathlib import Path
import json
import tempfile

from api.schemas import (
    IngestRequest,
    IngestResponse,
    ScrapeRequest,
    TaskResponse,
    TaskStatusResponse,
    TaskStatus,
)
from core.deps import get_memory
from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Ingestion"])


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Ingest Statements",
    description="Ingest political statements into the vector store.",
)
async def ingest_statements(request: IngestRequest) -> IngestResponse:
    """
    Ingest statements from JSON payload.
    
    Each statement should have at least a 'text' field.
    Optional fields: speaker, date, topic, source.
    """
    try:
        memory = get_memory()
        
        # Validate statements have 'text' field
        for i, stmt in enumerate(request.statements):
            if "text" not in stmt or not stmt["text"].strip():
                raise ValueError(f"Statement {i} is missing 'text' field")
        
        ids = memory.ingest_batch(request.statements)
        
        logger.info(f"Ingested {len(ids)} statements")
        
        return IngestResponse(
            success=True,
            count=len(ids),
            document_ids=ids,
            message=f"Successfully ingested {len(ids)} statements",
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Ingestion failed")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@router.post(
    "/ingest/file",
    response_model=IngestResponse,
    summary="Ingest from File",
    description="Upload and ingest statements from a JSON file.",
)
async def ingest_file(file: UploadFile = File(...)) -> IngestResponse:
    """
    Ingest statements from an uploaded JSON file.
    
    The file should contain an array of statement objects.
    """
    if not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=400,
            detail="Only JSON files are supported",
        )
    
    try:
        content = await file.read()
        statements = json.loads(content.decode("utf-8"))
        
        if not isinstance(statements, list):
            raise ValueError("File must contain a JSON array")
        
        memory = get_memory()
        ids = memory.ingest_batch(statements)
        
        logger.info(f"Ingested {len(ids)} statements from file: {file.filename}")
        
        return IngestResponse(
            success=True,
            count=len(ids),
            document_ids=ids,
            message=f"Successfully ingested {len(ids)} statements from {file.filename}",
        )
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("File ingestion failed")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {e}")


@router.post(
    "/scrape",
    response_model=TaskResponse,
    summary="Start Scraping Task",
    description="Start an async scraping task for TBMM commission transcripts.",
)
async def start_scraping(request: ScrapeRequest) -> TaskResponse:
    """
    Start a scraping task via Celery.
    
    Returns a task ID that can be polled for status.
    """
    try:
        from workers.tasks.scraping import scrape_commission_task
        
        task = scrape_commission_task.delay(
            commission_key=request.commission,
            limit=request.limit,
        )
        
        logger.info(f"Scraping task created: {task.id} (commission={request.commission})")
        
        return TaskResponse(
            task_id=task.id,
            status=TaskStatus.PENDING,
            message=f"Scraping task submitted for {request.commission}",
        )
        
    except Exception as e:
        logger.exception("Failed to create scraping task")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {e}")


@router.get(
    "/scrape/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get Scraping Task Status",
    description="Get the status and result of a scraping task.",
)
async def get_scraping_status(task_id: str) -> TaskStatusResponse:
    """Get status of a scraping task."""
    try:
        from workers.celery_app import celery_app
        
        result = celery_app.AsyncResult(task_id)
        
        response = TaskStatusResponse(
            task_id=task_id,
            status=TaskStatus(result.status),
        )
        
        if result.ready():
            if result.successful():
                response.result = result.result
            else:
                response.error = str(result.result)
        
        return response
        
    except Exception as e:
        logger.exception(f"Failed to get task status: {task_id}")
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {e}")


@router.post(
    "/scrape/all",
    response_model=TaskResponse,
    summary="Scrape All Commissions",
    description="Start scraping all configured TBMM commissions.",
)
async def scrape_all_commissions() -> TaskResponse:
    """Start scraping all commissions."""
    try:
        from workers.tasks.scraping import scrape_all_commissions_task
        
        task = scrape_all_commissions_task.delay()
        
        logger.info(f"Scrape all commissions task created: {task.id}")
        
        return TaskResponse(
            task_id=task.id,
            status=TaskStatus.PENDING,
            message="Scraping task submitted for all commissions",
        )
        
    except Exception as e:
        logger.exception("Failed to create scraping task")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {e}")
