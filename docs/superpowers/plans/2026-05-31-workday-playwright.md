# Workday Playwright Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the broken httpx-based Workday client with a Playwright-based implementation that bypasses Cloudflare bot detection.

**Architecture:** `fetch_jobs` uses `sync_playwright` (compatible with the existing sync contract); `probe_workday` uses `async_playwright`. Job data mapping is extracted into a pure `_parse_jobs` function so the transformation logic is unit-testable without a browser. Integration tests (real browser + network) are gated behind `@pytest.mark.integration` and skipped in the normal suite.

**Tech Stack:** Python 3.11, playwright>=1.40 (sync + async API), pytest marker for integration tests

---

### Task 1: Add playwright dependency and integration test marker

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add playwright to dependencies and configure the integration marker**

Full `pyproject.toml` after edit:

```toml
[build-system]
requires = ["setuptools>=61", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "auto-apply"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "apscheduler>=3.10",
    "click>=8.1",
    "pyyaml>=6.0",
    "playwright>=1.40",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.setuptools]
packages = ["db", "models", "pipeline", "pipeline.discovery", "pipeline.discovery.clients", "pipeline.filter"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "integration: requires a real browser and live network (run with: pytest -m integration)",
]
```

- [ ] **Step 2: Install playwright and Chromium**

```bash
pip install playwright
playwright install chromium
```

Expected: Chromium downloads and installs (~150MB). No errors.

- [ ] **Step 3: Verify playwright is importable**

```bash
python3 -c "from playwright.sync_api import sync_playwright; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add playwright dependency for Workday browser automation"
```

---

### Task 2: `_parse_jobs` pure function and updated constants

**Files:**
- Modify: `pipeline/discovery/clients/workday.py`
- Modify: `tests/test_workday.py`

- [ ] **Step 1: Write the failing unit tests**

Replace the entire content of `tests/test_workday.py` with:

```python
import pytest


def test_parse_jobs_maps_fields():
    from pipeline.discovery.clients.workday import _parse_jobs
    data = {
        "total": 1,
        "jobPostings": [{
            "externalPath": "/en-US/ExternalCareerSite/job/Remote/ML-Engineer_JR-001",
            "title": "ML Engineer",
            "locationsText": "Remote",
        }],
    }
    jobs = _parse_jobs(data, "https://stripe.wd5.myworkdayjobs.com")
    assert len(jobs) == 1
    assert jobs[0].id == "/en-US/ExternalCareerSite/job/Remote/ML-Engineer_JR-001"
    assert jobs[0].title == "ML Engineer"
    assert jobs[0].url == "https://stripe.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/Remote/ML-Engineer_JR-001"
    assert jobs[0].location == "Remote"
    assert jobs[0].description is None


def test_parse_jobs_handles_missing_location():
    from pipeline.discovery.clients.workday import _parse_jobs
    data = {"total": 1, "jobPostings": [{"externalPath": "/path/Job_JR-1", "title": "Engineer"}]}
    jobs = _parse_jobs(data, "https://co.wd5.myworkdayjobs.com")
    assert len(jobs) == 1
    assert jobs[0].location is None


def test_parse_jobs_returns_empty_for_no_postings():
    from pipeline.discovery.clients.workday import _parse_jobs
    jobs = _parse_jobs({"total": 0, "jobPostings": []}, "https://co.wd5.myworkdayjobs.com")
    assert jobs == []


def test_workday_registered_in_client_map():
    from pipeline.discovery.poller import _CLIENT_MAP
    assert "workday" in _CLIENT_MAP


@pytest.mark.integration
def test_fetch_jobs_returns_jobs_from_real_board():
    """Requires: playwright install chromium, live network."""
    from pipeline.discovery.clients.workday import fetch_jobs
    jobs = fetch_jobs("workday.wd5/Workday")
    assert isinstance(jobs, list)
    if jobs:
        assert jobs[0].title
        assert jobs[0].url
        assert jobs[0].id


@pytest.mark.integration
async def test_probe_workday_finds_workday_inc():
    """Requires: playwright install chromium, live network."""
    from pipeline.discovery.clients.workday import probe_workday
    result = await probe_workday("workday")
    assert result is not None
    assert result[0] == "workday"
    assert "workday.wd" in result[1]
```

- [ ] **Step 2: Run the unit tests to verify they fail**

```bash
pytest tests/test_workday.py::test_parse_jobs_maps_fields tests/test_workday.py::test_parse_jobs_handles_missing_location tests/test_workday.py::test_parse_jobs_returns_empty_for_no_postings -v
```

Expected: `ImportError` — `_parse_jobs` not defined yet.

- [ ] **Step 3: Rewrite `workday.py` with the constants update and `_parse_jobs`**

Replace the entire file with this intermediate state (keeps `fetch_jobs` as a stub, adds `_parse_jobs`):

```python
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
```

- [ ] **Step 4: Run the unit tests to verify they pass**

```bash
pytest tests/test_workday.py::test_parse_jobs_maps_fields tests/test_workday.py::test_parse_jobs_handles_missing_location tests/test_workday.py::test_parse_jobs_returns_empty_for_no_postings -v
```

Expected: all 3 `PASSED`.

- [ ] **Step 5: Confirm integration tests are skipped in normal run**

```bash
pytest tests/test_workday.py -v
```

Expected: 4 tests run (`test_parse_jobs_*` × 3 + `test_workday_registered_in_client_map`), 2 integration tests skipped/deselected.

- [ ] **Step 6: Commit**

```bash
git add pipeline/discovery/clients/workday.py tests/test_workday.py
git commit -m "feat: add _parse_jobs pure function, update WORKDAY_BOARD_NAMES"
```

---

### Task 3: `fetch_jobs` with Playwright

**Files:**
- Modify: `pipeline/discovery/clients/workday.py`

- [ ] **Step 1: Replace the `fetch_jobs` stub with the Playwright implementation**

Replace only the `fetch_jobs` function in `pipeline/discovery/clients/workday.py`:

```python
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
```

- [ ] **Step 2: Run the unit tests to confirm they still pass**

```bash
pytest tests/test_workday.py -v -m "not integration"
```

Expected: 4 tests `PASSED` (the `_parse_jobs` and registration tests).

- [ ] **Step 3: Run the integration test manually to confirm `fetch_jobs` works**

```bash
pytest tests/test_workday.py::test_fetch_jobs_returns_jobs_from_real_board -v -m integration
```

Expected: `PASSED` — returns a list of `RawJob` objects from Workday Inc's board. (Requires live network.)

- [ ] **Step 4: Commit**

```bash
git add pipeline/discovery/clients/workday.py
git commit -m "feat: replace fetch_jobs httpx with Playwright browser automation"
```

---

### Task 4: `probe_workday` with Playwright + update `detector.py`

**Files:**
- Modify: `pipeline/discovery/clients/workday.py`
- Modify: `pipeline/discovery/detector.py`
- Modify: `tests/test_detector.py`

- [ ] **Step 1: Replace `probe_workday` stub with Playwright implementation**

Replace the `probe_workday` function (and add the `_probe_board_playwright` helper) in `pipeline/discovery/clients/workday.py`. The complete file after this step:

```python
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


async def _probe_board_playwright(browser, subdomain: str, board: str) -> tuple[str, str] | None:
    page = await browser.new_page()
    try:
        url = f"https://{subdomain}.myworkdayjobs.com/en-US/{board}"
        try:
            async with page.expect_response(
                lambda r: "/wday/cxs/" in r.url and r.url.endswith("/jobs"),
                timeout=10000,
            ) as response_info:
                await page.goto(url, wait_until="domcontentloaded", timeout=10000)
            resp = await response_info.value
            if resp.status == 200:
                return ("workday", f"{subdomain}/{board}")
        except Exception:
            pass
        return None
    finally:
        await page.close()


async def probe_workday(slug: str) -> tuple[str, str] | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            for version in WORKDAY_VERSIONS:
                subdomain = f"{slug}.{version}"
                for board in WORKDAY_BOARD_NAMES:
                    result = await _probe_board_playwright(browser, subdomain, board)
                    if result is not None:
                        return result
        finally:
            await browser.close()
    return None
```

- [ ] **Step 2: Update `detector.py` — remove `client` from `probe_workday` call and move outside httpx block**

Full file after edit:

```python
import re
import asyncio
import httpx
from pipeline.discovery.clients.greenhouse import GREENHOUSE_URL
from pipeline.discovery.clients.lever import LEVER_URL
from pipeline.discovery.clients.ashby import ASHBY_URL
from pipeline.discovery.clients.workday import probe_workday

_ATS_PROBE_URLS = {
    "greenhouse": GREENHOUSE_URL,
    "lever": LEVER_URL,
    "ashby": ASHBY_URL,
}

def generate_slug_variants(name: str) -> list[str]:
    base = name.lower()
    base = re.sub(r"[,\.&]+", "", base)
    base = re.sub(r"\b(inc|corp|llc|ltd|co)\b", "", base).strip()
    base = re.sub(r"\s+", " ", base).strip()
    variants = {
        base.replace(" ", "-"),
        base.replace(" ", ""),
        base.replace(" ", "_"),
    }
    return list(variants)

async def _probe(client: httpx.AsyncClient, ats_type: str, slug: str) -> tuple[str, str] | None:
    url = _ATS_PROBE_URLS[ats_type].format(token=slug)
    try:
        response = await client.get(url, timeout=10)
        if response.status_code == 200:
            return (ats_type, slug)
    except httpx.RequestError:
        pass
    return None

async def detect_ats(name: str, slug_override: str | None = None) -> tuple[str, str] | None:
    slugs = [slug_override] if slug_override else generate_slug_variants(name)
    async with httpx.AsyncClient() as client:
        tasks = [
            _probe(client, ats_type, slug)
            for slug in slugs
            for ats_type in _ATS_PROBE_URLS
        ]
        results = await asyncio.gather(*tasks)
        for result in results:
            if result is not None:
                return result
    for slug in slugs:
        result = await probe_workday(slug)
        if result is not None:
            return result
    return None
```

- [ ] **Step 3: Update `test_detect_ats_finds_workday` in `tests/test_detector.py`**

Replace the `test_detect_ats_finds_workday` test (append at end of file, replacing the existing version):

```python
async def test_detect_ats_finds_workday():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 404
        return r

    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient, \
         patch("pipeline.discovery.detector.probe_workday",
               return_value=("workday", "stripe.wd5/ExternalCareerSite")) as mock_probe:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client
        result = await detect_ats("Stripe")

    assert mock_probe.called
    assert result == ("workday", "stripe.wd5/ExternalCareerSite")
```

- [ ] **Step 4: Run the full test suite**

```bash
pytest -v -m "not integration"
```

Expected: all non-integration tests `PASSED`. Count should be similar to before (the 4 workday unit tests + all other tests).

- [ ] **Step 5: Run the integration probe test manually**

```bash
pytest tests/test_workday.py::test_probe_workday_finds_workday_inc -v -m integration
```

Expected: `PASSED` — finds Workday Inc's board automatically.

- [ ] **Step 6: Smoke test the CLI end-to-end**

```bash
python3 main.py add-company --name "Workday"
```

Expected: `✓ Workday → workday (token: workday.wd5/Workday)` or similar.

- [ ] **Step 7: Commit**

```bash
git add pipeline/discovery/clients/workday.py pipeline/discovery/detector.py tests/test_detector.py
git commit -m "feat: replace probe_workday httpx with Playwright, update detector"
```
