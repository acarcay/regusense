"""
Celery Application Configuration for ReguSense.

Configures Celery with Redis as broker and result backend.
"""

from celery import Celery

from core.config import settings

# Create Celery app
celery_app = Celery(
    "regusense",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "workers.tasks.analysis",
        "workers.tasks.scraping",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_track_started=settings.celery_task_track_started,
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_time_limit - 60,
    
    # Result settings
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,
    
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    
    # Timezone
    timezone="Europe/Istanbul",
    enable_utc=True,
    
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
    
    # Task routing
    task_routes={
        "workers.tasks.scraping.*": {"queue": "scraping"},
        "workers.tasks.analysis.*": {"queue": "analysis"},
    },
    
    # Default queue
    task_default_queue="default",
)


# Optional: Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    # Example: Daily scraping at 6 AM Istanbul time
    # "daily-scrape": {
    #     "task": "workers.tasks.scraping.scrape_all_commissions_task",
    #     "schedule": crontab(hour=6, minute=0),
    # },
}
