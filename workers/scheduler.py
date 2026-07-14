"""
Autonomous Data Collector and Pipeline Scheduler.

Runs daily tasks via APScheduler to collect data from:
- EKAP (Tenders) at 01:00 AM
- Resmi Gazete (Appointments & Tenders) at 02:00 AM
And then runs the LangGraph Intelligence Pipeline at 03:00 AM to process all pending data.
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scrapers.ekap_scraper import EkapScraper
from scrapers.resmi_gazete_scraper import ResmiGazeteScraper
from pipeline.intelligence import run_intelligence_pipeline

from core.logging import setup_logging
from config.settings import settings

# Configure logging
setup_logging(level="INFO", log_file=settings.logs_dir / "scheduler.log")
logger = logging.getLogger("ReguSenseScheduler")


async def task_ekap_scraper():
    """Run EKAP scraper for the last 1 day."""
    logger.info("=== Starting EKAP Scraper Task ===")
    try:
        async with EkapScraper(headless=True) as scraper:
            result = await scraper.scrape_latest(days=1)
            logger.info(f"EKAP Scrape Completed: Found={result.items_found}, Saved={result.items_saved}")
    except Exception as e:
        logger.error(f"EKAP Scraper Task Failed: {e}", exc_info=True)


async def task_resmi_gazete_scraper():
    """Run Resmi Gazete scraper for the last 1 day."""
    logger.info("=== Starting Resmi Gazete Scraper Task ===")
    try:
        async with ResmiGazeteScraper(headless=True) as scraper:
            result = await scraper.scrape_latest(days=1, ingest_to_memory=False)
            logger.info(f"Resmi Gazete Scrape Completed: Found={result.items_found}, Saved={result.items_saved}")
    except Exception as e:
        logger.error(f"Resmi Gazete Scraper Task Failed: {e}", exc_info=True)


async def task_intelligence_pipeline():
    """Run the intelligence pipeline (Hunter + Temporal Analysis) on newly ingested data."""
    logger.info("=== Starting Intelligence Pipeline Task ===")
    try:
        # EKAP/Resmi Gazete scrapers already ran at 01:00/02:00, so look back 1 day
        summary = await run_intelligence_pipeline(ekap_days=1)
        logger.info(f"Pipeline Completed: {summary}")
    except Exception as e:
        logger.error(f"Intelligence Pipeline Task Failed: {e}", exc_info=True)


async def main():
    """Initialize and start the scheduler."""
    logger.info("Starting ReguSense Autonomous Scheduler...")
    
    scheduler = AsyncIOScheduler()

    # 1. EKAP Scraper at 01:00 AM
    scheduler.add_job(
        task_ekap_scraper,
        trigger=CronTrigger(hour=1, minute=0),
        id="ekap_scraper_job",
        name="EKAP Nightly Scrape",
        replace_existing=True,
    )
    
    # 2. Resmi Gazete at 02:00 AM
    scheduler.add_job(
        task_resmi_gazete_scraper,
        trigger=CronTrigger(hour=2, minute=0),
        id="resmi_gazete_scraper_job",
        name="Resmi Gazete Nightly Scrape",
        replace_existing=True,
    )
    
    # 3. Agent Pipeline at 03:00 AM
    scheduler.add_job(
        task_intelligence_pipeline,
        trigger=CronTrigger(hour=3, minute=0),
        id="intelligence_pipeline_job",
        name="Nightly Agent Pipeline",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started. Waiting for jobs...")
    
    # Print schedule
    scheduler.print_jobs()

    # Keep the event loop running
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping scheduler...")
        scheduler.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Scheduler stopped by user.")
