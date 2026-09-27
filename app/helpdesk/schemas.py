from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class TicketInput(BaseModel):
    ticket_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class Classification(BaseModel):
    ticket_id: str
    category: str
    priority: str


class OrderData(BaseModel):
    ticket_id: str
    order_number: str | None
    product: str | None


class PeriodInput(BaseModel):
    start: date
    end: date


class Topic(BaseModel):
    topic: str
    count: int
    examples: list[str]


class TopicsReport(BaseModel):
    start: date
    end: date
    total_tickets: int
    topics: list[Topic]


class JobState(str, Enum):
    pending = "pending"
    running = "running"
    failed = "failed"
    done = "done"


class ReportJob(BaseModel):
    id: str
    state: JobState = JobState.pending
    progress: str | None = None
    reason: str | None = None
    result: TopicsReport | None = None
