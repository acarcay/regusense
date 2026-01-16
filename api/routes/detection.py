"""
Contradiction Detection API Routes.
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional

from api.schemas import (
    DetectionRequest,
    DetectionResponse,
    BatchDetectionRequest,
    TaskResponse,
    TaskStatusResponse,
    TaskStatus,
    HistoricalMatch,
    ContradictionType,
)
from core.deps import get_memory, get_analyzer, get_detector
from core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Detection"])


@router.post(
    "/detect",
    response_model=DetectionResponse,
    summary="Detect Contradictions",
    description="Analyze a statement for contradictions against historical records.",
)
async def detect_contradiction(request: DetectionRequest) -> DetectionResponse:
    """
    Synchronous contradiction detection.
    
    Returns immediately with the analysis result.
    """
    try:
        logger.info(f"Detection request: speaker={request.speaker}, threshold={request.threshold}")
        
        detector = get_detector(threshold=request.threshold)
        result = detector.detect(
            new_statement=request.statement,
            speaker=request.speaker,
            filter_by_speaker=request.filter_by_speaker,
        )
        
        # Convert result to response
        historical_matches = [
            HistoricalMatch(
                text=m.get("text", ""),
                speaker=m.get("speaker", ""),
                date=m.get("date", ""),
                topic=m.get("topic", ""),
                source=m.get("source", ""),
                source_type=m.get("source_type", "UNKNOWN"),
                similarity=m.get("similarity", 0.0),
            )
            for m in result.historical_matches
        ]
        
        response = DetectionResponse(
            is_contradiction=result.is_contradiction,
            contradiction_score=result.contradiction_score,
            contradiction_type=ContradictionType(result.contradiction_type.value),
            new_statement=result.new_statement,
            speaker=result.speaker,
            explanation=result.explanation,
            key_conflict_points=result.key_conflict_points,
            historical_matches=historical_matches,
            analysis_timestamp=result.analysis_timestamp,
        )
        
        logger.info(
            f"Detection complete: is_contradiction={response.is_contradiction}, "
            f"score={response.contradiction_score}"
        )
        
        return response
        
    except ValueError as e:
        logger.error(f"Detection error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Detection failed")
        raise HTTPException(status_code=500, detail=f"Detection failed: {e}")


@router.post(
    "/detect/async",
    response_model=TaskResponse,
    summary="Async Contradiction Detection",
    description="Start an async contradiction detection task. Returns a task ID.",
)
async def detect_contradiction_async(
    request: DetectionRequest,
    background_tasks: BackgroundTasks,
) -> TaskResponse:
    """
    Asynchronous contradiction detection via Celery.
    
    Returns immediately with a task ID that can be polled for results.
    """
    try:
        from workers.tasks.analysis import detect_contradiction_task
        
        task = detect_contradiction_task.delay(
            statement=request.statement,
            speaker=request.speaker,
            threshold=request.threshold,
            filter_by_speaker=request.filter_by_speaker,
        )
        
        logger.info(f"Async detection task created: {task.id}")
        
        return TaskResponse(
            task_id=task.id,
            status=TaskStatus.PENDING,
            message="Detection task submitted",
        )
        
    except Exception as e:
        logger.exception("Failed to create async detection task")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {e}")


@router.get(
    "/detect/{task_id}",
    response_model=TaskStatusResponse,
    summary="Get Detection Task Status",
    description="Get the status and result of an async detection task.",
)
async def get_detection_status(task_id: str) -> TaskStatusResponse:
    """Get status of an async detection task."""
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
    "/detect/batch",
    response_model=TaskResponse,
    summary="Batch Detection",
    description="Start batch contradiction detection for multiple statements.",
)
async def detect_batch(request: BatchDetectionRequest) -> TaskResponse:
    """
    Batch contradiction detection via Celery.
    
    Processes multiple statements asynchronously.
    """
    try:
        from workers.tasks.analysis import detect_batch_task
        
        task = detect_batch_task.delay(
            statements=request.statements,
            threshold=request.threshold,
        )
        
        logger.info(f"Batch detection task created: {task.id} ({len(request.statements)} statements)")
        
        return TaskResponse(
            task_id=task.id,
            status=TaskStatus.PENDING,
            message=f"Batch detection task submitted for {len(request.statements)} statements",
        )
        
    except Exception as e:
        logger.exception("Failed to create batch detection task")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {e}")
