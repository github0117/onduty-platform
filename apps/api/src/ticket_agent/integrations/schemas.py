from pydantic import BaseModel


class SyncMetricsResponse(BaseModel):
    attempted: int
    pending: int
    syncing: int
    retrying: int
    succeeded: int
    failed: int
    terminal_count: int
    success_rate: float
    failure_rate: float
    average_attempts: float
    alerts: list[str]

