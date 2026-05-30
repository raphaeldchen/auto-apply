from dataclasses import dataclass
from datetime import datetime


@dataclass
class Company:
    name: str
    slug: str
    ats_type: str | None
    board_token: str | None
    status: str
    id: int | None = None
    detected_at: datetime | None = None
