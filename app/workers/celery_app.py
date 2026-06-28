"""Celery application instance and configuration."""

from celery import Celery

from app.core.config import settings
from app.core.logging import configure_logging

# Set up structured logging when the worker process starts
configure_logging()

celery_app = Celery(
    "transaction_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],  # module that defines the tasks
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task execution
    task_acks_late=True,           
    task_reject_on_worker_lost=True,  
    worker_prefetch_multiplier=1,  

    # Result TTL — keep results in Redis for 1 day
    result_expires=86400,

    # Queue
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.process_job": {"queue": "default"},
    },
)
