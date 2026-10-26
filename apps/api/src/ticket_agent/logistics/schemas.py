from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class LogisticsQueryRequest(BaseModel):
    order_id: str | None = Field(default=None, max_length=128)
    tracking_number: str | None = Field(default=None, max_length=128)
    carrier_code: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_identifier(self) -> "LogisticsQueryRequest":
        if not self.order_id and not self.tracking_number:
            raise ValueError("order_id or tracking_number is required")
        return self


class LogisticsEventView(BaseModel):
    occurred_at: datetime | None
    location: str | None
    description: str


class LogisticsStatusView(BaseModel):
    order_id: str | None
    tracking_number: str | None
    carrier_code: str | None
    status: str
    status_label: str
    latest_event_at: datetime | None
    events: list[LogisticsEventView]
