import asyncio
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
    page_url = f"{base_url}/{board}"
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


async def _probe_version_playwright(browser, subdomain: str) -> tuple[str, str] | None:
    page = await browser.new_page()
    try:
        try:
            async with page.expect_response(
                lambda r: "/wday/cxs/" in r.url and r.url.endswith("/jobs") and r.status == 200,
                timeout=5000,
            ) as response_info:
                await page.goto(
                    f"https://{subdomain}.myworkdayjobs.com/",
                    wait_until="domcontentloaded",
                    timeout=5000,
                )
            resp = await response_info.value
            # Extract board token from URL:
            # https://{subdomain}.myworkdayjobs.com/wday/cxs/{subdomain}/{board}/jobs
            token = resp.url.split("/wday/cxs/")[-1].removesuffix("/jobs")
            return ("workday", token)
        except Exception:
            return None
    finally:
        await page.close()


async def probe_workday(slug: str) -> tuple[str, str] | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            results = await asyncio.gather(*[
                _probe_version_playwright(browser, f"{slug}.{version}")
                for version in WORKDAY_VERSIONS
            ])
            for result in results:
                if result is not None:
                    return result
        finally:
            await browser.close()
    return None
