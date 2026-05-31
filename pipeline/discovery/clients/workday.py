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
    subdomain, board = board_token.split("/", 1)
    base_url = f"https://{subdomain}.myworkdayjobs.com"
    page_url = f"{base_url}/en-US/{board}"
    all_data: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(response):
            if "/wday/cxs/" in response.url and response.url.endswith("/jobs"):
                try:
                    all_data.append(response.json())
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(page_url, wait_until="networkidle")

        while True:
            btn = page.query_selector("[data-automation-id='loadMoreButton']")
            if btn is None or not btn.is_visible():
                break
            btn.click()
            page.wait_for_load_state("networkidle")

        browser.close()

    jobs: list[RawJob] = []
    for data in all_data:
        jobs.extend(_parse_jobs(data, base_url))
    return jobs


async def probe_workday(slug: str) -> tuple[str, str] | None:
    raise NotImplementedError("Playwright probe_workday — implemented in Task 4")
