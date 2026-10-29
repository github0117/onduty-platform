from celery import Celery

from ticket_agent.shared.settings import get_settings

settings = get_settings()

celery_app = Celery(
    "ticket_agent",
    broker=settings.redis_url,
    include=["ticket_agent.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=3,
    task_default_queue="ticket_agent",
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "dispatch-outbox-every-2-seconds": {
            "task": "ticket_agent.outbox.dispatch_pending",
            "schedule": 2.0,
        },
        "reclaim-offline-customer-agents-every-30-seconds": {
            "task": "ticket_agent.customer_service.reclaim_offline",
            "schedule": 30.0,
        },
        "escalate-customer-service-sla-every-60-seconds": {
            "task": "ticket_agent.customer_service.escalate_sla",
            "schedule": 60.0,
        },
        "notify-supervisors-every-60-seconds": {
            "task": "ticket_agent.customer_service.notify_supervisors",
            "schedule": 60.0,
        },
        "reclaim-conversation-turns-every-30-seconds": {
            "task": "ticket_agent.customer_service.reclaim_turns",
            "schedule": 30.0,
        },
        "auto-assign-customer-conversations-every-10-seconds": {
            "task": "ticket_agent.customer_service.auto_assign",
            "schedule": 10.0,
        },
        "reconcile-mcp-incidents-every-120-seconds": {
            "task": "ticket_agent.mcp.reconcile_incidents",
            "schedule": 120.0,
        },
        "poll-email-connectors-every-60-seconds": {
            "task": "ticket_agent.connectors.poll_email",
            "schedule": 60.0,
        },
    },
)

