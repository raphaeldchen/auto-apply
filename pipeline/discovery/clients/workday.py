from playwright.sync_api import sync_playwright
from playwright.async_api import async_playwright
from models.job import RawJob

WORKDAY_VERSIONS = ["wd5", "wd3", "wd1", "wd2"]
WORKDAY_BOARD_NAMES = ["ExternalCareerSite", "External", "Careers", "externalsite", "Workday"]


def _parse_jobs(data: dict, base_url: str) -> list[RawJob]:
    return [
        RawJob(
            id=posting["externalPath"],
            title=posting["title"],
            url=base_url + posting["externalPath"],
            location=posting.get("locationsText"),
            description=None,
        )
        for posting in data.get("jobPostings", [])
    ]


def fetch_jobs(board_token: str) -> list[RawJob]:
    raise NotImplementedError("Playwright fetch_jobs — implemented in Task 3")


async def probe_workday(slug: str) -> tuple[str, str] | None:
    raise NotImplementedError("Playwright probe_workday — implemented in Task 4")
