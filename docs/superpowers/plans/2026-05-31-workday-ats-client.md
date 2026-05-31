# Workday ATS Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Workday ATS client so companies on Workday can be registered manually and polled during pipeline runs.

**Architecture:** A new `workday.py` client follows the same `fetch_jobs(board_token) -> list[RawJob]` contract as the existing Greenhouse/Lever/Ashby clients. The composite `board_token` format (`subdomain/board`, e.g. `stripe.wd5/ExternalCareerSite`) encodes both Workday identifiers in the existing DB column. A new `--ats-type` CLI flag on `add-company` bypasses auto-detection so Workday companies can be registered directly.

**Tech Stack:** Python 3.11, httpx (sync POST), Click, pytest + unittest.mock

---

### Task 1: Workday client — single page

**Files:**
- Create: `pipeline/discovery/clients/workday.py`
- Create: `tests/test_workday.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workday.py
from unittest.mock import patch, MagicMock


def _mock_post(json_data):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data
    return response


def test_workday_parses_jobs():
    page = {
        "total": 1,
        "jobPostings": [
            {
                "externalPath": "/en-US/ExternalCareerSite/job/Remote/Senior-ML-Engineer_JR-001",
                "title": "Senior ML Engineer",
                "locationsText": "Remote",
            }
        ],
    }
    with patch("pipeline.discovery.clients.workday.httpx.post", return_value=_mock_post(page)):
        from pipeline.discovery.clients.workday import fetch_jobs
        jobs = fetch_jobs("stripe.wd5/ExternalCareerSite")

    assert len(jobs) == 1
    assert jobs[0].id == "/en-US/ExternalCareerSite/job/Remote/Senior-ML-Engineer_JR-001"
    assert jobs[0].title == "Senior ML Engineer"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "https://stripe.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/Remote/Senior-ML-Engineer_JR-001"
    assert jobs[0].description is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_workday.py::test_workday_parses_jobs -v
```

Expected: `ModuleNotFoundError` or `ImportError` — file doesn't exist yet.

- [ ] **Step 3: Create the client**

```python
# pipeline/discovery/clients/workday.py
import httpx
from models.job import RawJob

WORKDAY_URL = "https://{subdomain}.myworkdayjobs.com/wday/cxs/{subdomain}/{board}/jobs"
_LIMIT = 20


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

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_workday.py::test_workday_parses_jobs -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/clients/workday.py tests/test_workday.py
git commit -m "feat: add Workday ATS client (single page)"
```

---

### Task 2: Workday client — pagination

**Files:**
- Modify: `tests/test_workday.py`

- [ ] **Step 1: Add the failing pagination test**

Append to `tests/test_workday.py`:

```python
def test_workday_paginates():
    def _posting(n):
        return {
            "externalPath": f"/en-US/Board/job/Remote/Job-{n}_JR-{n:03d}",
            "title": f"Job {n}",
            "locationsText": "Remote",
        }

    page1 = {"total": 22, "jobPostings": [_posting(i) for i in range(20)]}
    page2 = {"total": 22, "jobPostings": [_posting(i) for i in range(20, 22)]}

    with patch(
        "pipeline.discovery.clients.workday.httpx.post",
        side_effect=[_mock_post(page1), _mock_post(page2)],
    ):
        from pipeline.discovery.clients.workday import fetch_jobs
        jobs = fetch_jobs("company.wd5/Board")

    assert len(jobs) == 22
    assert jobs[0].id == "/en-US/Board/job/Remote/Job-0_JR-000"
    assert jobs[21].id == "/en-US/Board/job/Remote/Job-21_JR-021"
```

- [ ] **Step 2: Run test to verify it passes (pagination is already implemented)**

```bash
pytest tests/test_workday.py::test_workday_paginates -v
```

Expected: `PASSED` — the `while True / offset >= total` loop already handles this.

- [ ] **Step 3: Run full test file**

```bash
pytest tests/test_workday.py -v
```

Expected: both tests `PASSED`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_workday.py
git commit -m "test: add Workday pagination test"
```

---

### Task 3: Register Workday in the poller

**Files:**
- Modify: `pipeline/discovery/poller.py` (lines 1–12)
- Modify: `tests/test_workday.py`

- [ ] **Step 1: Add the failing registration test**

Append to `tests/test_workday.py`:

```python
def test_workday_registered_in_client_map():
    from pipeline.discovery.poller import _CLIENT_MAP
    assert "workday" in _CLIENT_MAP
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_workday.py::test_workday_registered_in_client_map -v
```

Expected: `AssertionError` — key not present yet.

- [ ] **Step 3: Register the client in the poller**

In `pipeline/discovery/poller.py`, add the import and map entry:

```python
# pipeline/discovery/poller.py  (full file after edit)
import sqlite3
import httpx
from models.company import Company
from models.job import Job, RawJob
from pipeline.db import get_seen_job_ids, upsert_jobs
from pipeline.discovery.clients import greenhouse, lever, ashby, workday   # add workday

_CLIENT_MAP = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
    "workday": workday.fetch_jobs,                                          # add this line
}


def fetch_jobs_for_company(company: Company) -> list[RawJob]:
    return _CLIENT_MAP[company.ats_type](company.board_token)


def poll_company(company: Company, conn: sqlite3.Connection) -> list[Job]:
    try:
        raw_jobs = fetch_jobs_for_company(company)
    except (httpx.HTTPError, KeyError) as e:
        print(f"Failed to fetch jobs for {company.name}: {e}")
        return []
    seen_ids = get_seen_job_ids(conn, company.id)
    all_jobs = [
        Job(id=r.id, company_id=company.id, title=r.title, url=r.url, location=r.location, description=r.description)
        for r in raw_jobs
    ]
    upsert_jobs(conn, all_jobs)
    return [j for j in all_jobs if j.id not in seen_ids]
```

- [ ] **Step 4: Run all Workday tests**

```bash
pytest tests/test_workday.py -v
```

Expected: all 3 tests `PASSED`.

- [ ] **Step 5: Confirm existing poller tests still pass**

```bash
pytest tests/test_poller.py -v
```

Expected: all `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add pipeline/discovery/poller.py tests/test_workday.py
git commit -m "feat: register Workday client in poller"
```

---

### Task 4: Add `--ats-type` to the CLI

**Files:**
- Modify: `main.py` (lines 18–41, the `add_company` command)
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from unittest.mock import patch
from click.testing import CliRunner
from main import cli


def test_add_company_with_ats_type_skips_detection(db_conn):
    with patch("main.init_db", return_value=db_conn):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add-company", "--name", "Stripe", "--ats-type", "workday", "--slug", "stripe.wd5/ExternalCareerSite"],
        )
    assert result.exit_code == 0
    assert "workday" in result.output
    assert "stripe.wd5/ExternalCareerSite" in result.output


def test_add_company_without_ats_type_calls_detection(db_conn):
    with patch("main.init_db", return_value=db_conn), \
         patch("main.detect_ats", return_value=("greenhouse", "stripe")) as mock_detect:
        runner = CliRunner()
        result = runner.invoke(cli, ["add-company", "--name", "Stripe"])
    mock_detect.assert_called_once()
    assert result.exit_code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -v
```

Expected: both fail — `--ats-type` option does not exist yet.

- [ ] **Step 3: Update `add_company` in `main.py`**

Replace the existing `add_company` function (lines 17–40) with:

```python
@cli.command()
@click.option("--name", required=True, help="Company name")
@click.option("--slug", default=None, help="ATS board token (required when --ats-type is set)")
@click.option("--ats-type", "ats_type", default=None, help="Skip detection and use this ATS type (e.g. workday)")
def add_company(name, slug, ats_type):
    """Detect and register a company's ATS."""
    conn = init_db(DB_PATH)
    try:
        if ats_type and slug:
            click.echo(f"✓ {name} → {ats_type} (token: {slug})")
            company = Company(
                name=name,
                slug=slug,
                ats_type=ats_type,
                board_token=slug,
                status="active",
            )
            upsert_company(conn, company)
        else:
            detected = asyncio.run(detect_ats(name, slug))
            if detected is None:
                click.echo(f"Could not detect ATS for '{name}'. Try --slug <slug> to specify.")
                return
            detected_ats, board_token = detected
            click.echo(f"✓ {name} → {detected_ats} (token: {board_token})")
            company = Company(
                name=name,
                slug=board_token,
                ats_type=detected_ats,
                board_token=board_token,
                status="active",
            )
            upsert_company(conn, company)
    finally:
        conn.close()
```

- [ ] **Step 4: Run the CLI tests**

```bash
pytest tests/test_cli.py -v
```

Expected: both `PASSED`.

- [ ] **Step 5: Run the full test suite**

```bash
pytest -v
```

Expected: all tests `PASSED`.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: add --ats-type flag to add-company for manual ATS registration"
```
