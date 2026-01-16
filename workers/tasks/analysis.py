"""
Analysis Celery Tasks.

Background tasks for contradiction detection and report generation.
"""

from typing import Any

from workers.celery_app import celery_app
from core.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(
    name="workers.tasks.analysis.detect_contradiction",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def detect_contradiction_task(
    self,
    statement: str,
    speaker: str = "",
    threshold: int = 70,
    filter_by_speaker: bool = True,
) -> dict[str, Any]:
    """
    Celery task for contradiction detection.
    
    Args:
        statement: The statement to analyze
        speaker: Optional speaker name
        threshold: Contradiction score threshold
        filter_by_speaker: Whether to filter by speaker
        
    Returns:
        Detection result as dictionary
    """
    try:
        logger.info(f"Starting detection task: {self.request.id}")
        
        from core.deps import get_detector
        
        detector = get_detector(threshold=threshold)
        result = detector.detect(
            new_statement=statement,
            speaker=speaker,
            filter_by_speaker=filter_by_speaker,
        )
        
        logger.info(
            f"Detection task complete: {self.request.id}, "
            f"is_contradiction={result.is_contradiction}"
        )
        
        return result.to_dict()
        
    except Exception as e:
        logger.exception(f"Detection task failed: {self.request.id}")
        raise self.retry(exc=e)


@celery_app.task(
    name="workers.tasks.analysis.detect_batch",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def detect_batch_task(
    self,
    statements: list[dict[str, str]],
    threshold: int = 70,
) -> list[dict[str, Any]]:
    """
    Celery task for batch contradiction detection.
    
    Args:
        statements: List of statements with 'text' and optional 'speaker' keys
        threshold: Contradiction score threshold
        
    Returns:
        List of detection results
    """
    try:
        logger.info(f"Starting batch detection task: {self.request.id} ({len(statements)} statements)")
        
        from core.deps import get_detector
        
        detector = get_detector(threshold=threshold)
        results = detector.detect_batch(statements)
        
        logger.info(f"Batch detection complete: {self.request.id}")
        
        return [r.to_dict() for r in results]
        
    except Exception as e:
        logger.exception(f"Batch detection task failed: {self.request.id}")
        raise self.retry(exc=e)


@celery_app.task(
    name="workers.tasks.analysis.generate_report",
    bind=True,
)
def generate_report_task(self, result: dict[str, Any]) -> str:
    """
    Celery task for PDF report generation.
    
    Args:
        result: Detection result dictionary
        
    Returns:
        Path to generated PDF
    """
    try:
        logger.info(f"Starting report generation: {self.request.id}")
        
        from core.deps import get_report_generator
        
        generator = get_report_generator()
        pdf_path = generator.generate_insight_card(result)
        
        logger.info(f"Report generated: {pdf_path}")
        
        return str(pdf_path)
        
    except Exception as e:
        logger.exception(f"Report generation failed: {self.request.id}")
        raise
