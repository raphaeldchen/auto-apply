# Workday Auto-Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-detect Workday ATS boards so `add-company --name "Stripe"` finds Workday companies without requiring `--ats-type workday --slug`.

**Architecture:** A new async `probe_workday(client, slug)` function in `workday.py` concurrently POSTs to all combinations of Workday version numbers and common board names for a given slug, returning the first match. `detect_ats` in `detector.py` calls it after the existing Greenhouse/Lever/Ashby probes fail, reusing the same `httpx.AsyncClient` instance.

**Tech Stack:** Python 3.11, httpx (async), asyncio.gather, pytest-asyncio

---

### Task 1: `probe_workday` function and constants

**Files:**
- Modify: `pipeline/discovery/clients/workday.py`
- Modify: `tests/test_workday.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workday.py`:

```python
async def test_probe_workday_finds_board():
    async def mock_post(url, **kwargs):
        r = MagicMock()
        r.status_code = 200 if "stripe.wd5" in url and "ExternalCareerSite" in url else 404
        return r

    mock_client = AsyncMock()
    mock_client.post = mock_post

    from pipeline.discovery.clients.workday import probe_workday
    result = await probe_workday(mock_client, "stripe")

    assert result is not None
    assert result[0] == "workday"
    assert result[1] == "stripe.wd5/ExternalCareerSite"


async def test_probe_workday_returns_none_when_no_match():
    async def mock_post(url, **kwargs):
        r = MagicMock()
        r.status_code = 404
        return r

    mock_client = AsyncMock()
    mock_client.post = mock_post

    from pipeline.discovery.clients.workday import probe_workday
    result = await probe_workday(mock_client, "unknowncorp")

    assert result is None
```

Also add `AsyncMock` to the existing import at the top of `tests/test_workday.py`:

```python
from unittest.mock import patch, MagicMock, AsyncMock
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_workday.py::test_probe_workday_finds_board tests/test_workday.py::test_probe_workday_returns_none_when_no_match -v
```

Expected: `ImportError` — `probe_workday` not defined yet.

- [ ] **Step 3: Add constants and `probe_workday` to `workday.py`**

Full file after edit:

```python
import asyncio
import httpx
from models.job import RawJob

WORKDAY_URL = "https://{subdomain}.myworkdayjobs.com/wday/cxs/{subdomain}/{board}/jobs"
WORKDAY_VERSIONS = ["wd5", "wd3", "wd1", "wd2"]
WORKDAY_BOARD_NAMES = ["ExternalCareerSite", "External", "Careers", "externalsite"]
_LIMIT = 20


async def _probe_board(client: httpx.AsyncClient, subdomain: str, board: str) -> tuple[str, str] | None:
    url = WORKDAY_URL.format(subdomain=subdomain, board=board)
    try:
        response = await client.post(
            url,
            json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            timeout=10,
        )
        if response.status_code == 200:
            return ("workday", f"{subdomain}/{board}")
    except httpx.RequestError:
        pass
    return None


async def probe_workday(client: httpx.AsyncClient, slug: str) -> tuple[str, str] | None:
    tasks = [
        _probe_board(client, f"{slug}.{version}", board)
        for version in WORKDAY_VERSIONS
        for board in WORKDAY_BOARD_NAMES
    ]
    results = await asyncio.gather(*tasks)
    for result in results:
        if result is not None:
            return result
    return None


def fetch_jobs(board_token: str) -> list[RawJob]:
    subdomain, board = board_token.split("/", 1)
    url = WORKDAY_URL.format(subdomain=subdomain, board=board)
    base_url = f"https://{subdomain}.myworkdayjobs.com"
    jobs = []
    offset = 0
    while True:
        response = httpx.post(
            url,
            json={"appliedFacets": {}, "limit": _LIMIT, "offset": offset, "searchText": ""},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        total = data.get("total", 0)
        for posting in data.get("jobPostings", []):
            path = posting["externalPath"]
            jobs.append(
                RawJob(
                    id=path,
                    title=posting["title"],
                    url=base_url + path,
                    location=posting.get("locationsText"),
                    description=None,
                )
            )
        offset += _LIMIT
        if offset >= total:
            break
    return jobs
```

- [ ] **Step 4: Run the new tests**

```bash
pytest tests/test_workday.py::test_probe_workday_finds_board tests/test_workday.py::test_probe_workday_returns_none_when_no_match -v
```

Expected: both `PASSED`.

- [ ] **Step 5: Run the full workday test file to check for regressions**

```bash
pytest tests/test_workday.py -v
```

Expected: all 5 tests `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/discovery/clients/workday.py tests/test_workday.py
git commit -m "feat: add probe_workday for Workday auto-detection"
```

---

### Task 2: Wire `probe_workday` into `detect_ats`

**Files:**
- Modify: `pipeline/discovery/detector.py`
- Modify: `tests/test_detector.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_detector.py`:

```python
async def test_detect_ats_finds_workday():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 404
        return r

    async def mock_post(url, **kwargs):
        r = MagicMock()
        r.status_code = 200 if "stripe.wd5" in url and "ExternalCareerSite" in url else 404
        return r

    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        mock_client.post = mock_post
        MockClient.return_value = mock_client
        result = await detect_ats("Stripe")

    assert result is not None
    assert result[0] == "workday"
    assert result[1] == "stripe.wd5/ExternalCareerSite"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_detector.py::test_detect_ats_finds_workday -v
```

Expected: `AssertionError` — `detect_ats` returns `None` (Workday not probed yet).

- [ ] **Step 3: Update `detect_ats` in `detector.py`**

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
            result = await probe_workday(client, slug)
            if result is not None:
                return result
    return None
```

- [ ] **Step 4: Run the new test**

```bash
pytest tests/test_detector.py::test_detect_ats_finds_workday -v
```

Expected: `PASSED`.

- [ ] **Step 5: Run all detector tests**

```bash
pytest tests/test_detector.py -v
```

Expected: all tests `PASSED` (existing tests unaffected — `AsyncMock` auto-mocks `post` returning status != 200 by default).

- [ ] **Step 6: Run the full test suite**

```bash
pytest -v
```

Expected: all tests `PASSED`.

- [ ] **Step 7: Commit**

```bash
git add pipeline/discovery/detector.py tests/test_detector.py
git commit -m "feat: wire Workday auto-detection into detect_ats"
```
