from dataclasses import dataclass
from datetime import datetime

# Desirability tiers, most → least. Drives generation model choice and care budget.
TIERS = ("reach", "target", "standard")


@dataclass
class Company:
    name: str
    slug: str
    ats_type: str | None
    board_token: str | None
    status: str
    id: int | None = None
    detected_at: datetime | None = None
    tier: str = "standard"
