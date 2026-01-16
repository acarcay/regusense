"""
Scraping Celery Tasks.

Background tasks for TBMM commission transcript scraping.
"""

import asyncio
from typing import Any

from workers.celery_app import celery_app
from core.logging import get_logger

logger = get_logger(__name__)


def run_async(coro):
    """Helper to run async code in Celery tasks."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(
    name="workers.tasks.scraping.scrape_commission",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def scrape_commission_task(
    self,
    commission_key: str,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Celery task for scraping a single commission.
    
    Args:
        commission_key: Key of the commission to scrape
        limit: Maximum transcripts to scrape
        
    Returns:
        Scraping result summary
    """
    try:
        logger.info(f"Starting scrape task: {self.request.id} (commission={commission_key})")
        
        from scrapers.commission_scraper import CommissionScraper
        from config.settings import COMMISSION_SOURCES
        
        if commission_key not in COMMISSION_SOURCES:
            raise ValueError(f"Unknown commission: {commission_key}")
        
        commission = COMMISSION_SOURCES[commission_key]
        
        async def _scrape():
            async with CommissionScraper() as scraper:
                result = await scraper.scrape(
                    url=commission["url"],
                    limit=limit,
                )
                return result
        
        result = run_async(_scrape())
        
        logger.info(
            f"Scrape task complete: {self.request.id}, "
            f"success={result.success}, transcripts={len(result.transcripts)}"
        )
        
        return {
            "success": result.success,
            "commission": commission_key,
            "transcripts_found": len(result.transcripts),
            "saved_path": str(result.saved_path) if result.saved_path else None,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
        }
        
    except Exception as e:
        logger.exception(f"Scrape task failed: {self.request.id}")
        raise self.retry(exc=e)


@celery_app.task(
    name="workers.tasks.scraping.scrape_all_commissions",
    bind=True,
    max_retries=1,
    default_retry_delay=600,
)
def scrape_all_commissions_task(self, limit_per_commission: int = 5) -> dict[str, Any]:
    """
    Celery task for scraping all commissions.
    
    Args:
        limit_per_commission: Maximum transcripts per commission
        
    Returns:
        Summary of all scraping results
    """
    try:
        logger.info(f"Starting scrape all task: {self.request.id}")
        
        from config.settings import COMMISSION_SOURCES
        
        results = {}
        total_transcripts = 0
        successful = 0
        failed = 0
        
        for key in COMMISSION_SOURCES:
            try:
                result = scrape_commission_task(
                    commission_key=key,
                    limit=limit_per_commission,
                )
                results[key] = result
                
                if result["success"]:
                    successful += 1
                    total_transcripts += result["transcripts_found"]
                else:
                    failed += 1
                    
            except Exception as e:
                logger.error(f"Failed to scrape {key}: {e}")
                results[key] = {"success": False, "error": str(e)}
                failed += 1
        
        logger.info(
            f"Scrape all complete: {self.request.id}, "
            f"successful={successful}, failed={failed}, total_transcripts={total_transcripts}"
        )
        
        return {
            "total_commissions": len(COMMISSION_SOURCES),
            "successful": successful,
            "failed": failed,
            "total_transcripts": total_transcripts,
            "results": results,
        }
        
    except Exception as e:
        logger.exception(f"Scrape all task failed: {self.request.id}")
        raise


@celery_app.task(
    name="workers.tasks.scraping.ingest_transcript",
    bind=True,
)
def ingest_transcript_task(
    self,
    pdf_path: str,
    commission_key: str,
) -> dict[str, Any]:
    """
    Celery task for ingesting a scraped transcript.
    
    Args:
        pdf_path: Path to the PDF file
        commission_key: Commission that the transcript belongs to
        
    Returns:
        Ingestion result
    """
    try:
        logger.info(f"Starting ingest task: {self.request.id} (file={pdf_path})")
        
        from processors.pdf_processor import PDFProcessor
        from core.deps import get_memory
        
        processor = PDFProcessor()
        memory = get_memory()
        
        # Extract text from PDF
        text_content = processor.extract_text(pdf_path)
        
        if not text_content:
            return {
                "success": False,
                "error": "No text content extracted from PDF",
            }
        
        # Parse into statements (simplified - you may want more sophisticated parsing)
        statements = [{
            "text": text_content,
            "source": f"TBMM {commission_key}",
            "source_type": "TBMM_COMMISSION",
        }]
        
        ids = memory.ingest_batch(statements)
        
        logger.info(f"Ingest task complete: {self.request.id}, ingested={len(ids)}")
        
        return {
            "success": True,
            "pdf_path": pdf_path,
            "documents_ingested": len(ids),
            "document_ids": ids,
        }
        
    except Exception as e:
        logger.exception(f"Ingest task failed: {self.request.id}")
        raise
