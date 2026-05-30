from dataclasses import dataclass
from datetime import datetime


@dataclass
class RawJob:
    id: str
    title: str
    url: str | None
    location: str | None
    description: str | None


@dataclass
class Job:
    id: str
    company_id: int
    title: str
    url: str | None
    location: str | None
    description: str | None
    first_seen_at: datetime | None = None
    filter_status: str = "new"
    llm_score: float | None = None
    llm_reason: str | None = None
    kw_reason: str | None = None
