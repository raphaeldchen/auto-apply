# Job Application Automation Agent — Discovery & Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a daily job discovery agent that monitors Greenhouse, Lever, and Ashby job boards, filters new postings by keyword and LLM score, and prints a terminal digest.

**Architecture:** Four-stage modular pipeline (Discover → Filter → [Tailor*] → [Apply*]) triggered daily by APScheduler. Each stage is an independent module communicating through typed dataclasses. SQLite persists company/ATS mappings and job state across runs.

**Tech Stack:** Python 3.11+, httpx (HTTP), anthropic SDK (LLM scoring), APScheduler (daily trigger), click (CLI), PyYAML (config), pytest + pytest-asyncio (tests)

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Dependencies and pytest config |
| `config.yaml` | User config template |
| `db/schema.sql` | SQLite DDL |
| `models/company.py` | `Company` dataclass |
| `models/job.py` | `Job`, `RawJob` dataclasses |
| `models/digest.py` | `DigestResult`, `CompanyDigest` dataclasses |
| `pipeline/config.py` | Parses `config.yaml` into typed dataclasses |
| `pipeline/db.py` | SQLite init + all CRUD |
| `pipeline/discovery/clients/greenhouse.py` | Greenhouse API → `list[RawJob]` |
| `pipeline/discovery/clients/lever.py` | Lever API → `list[RawJob]` |
| `pipeline/discovery/clients/ashby.py` | Ashby API → `list[RawJob]` |
| `pipeline/discovery/detector.py` | Slug variant generation + async ATS probing |
| `pipeline/discovery/poller.py` | Daily fetch + diff against job store |
| `pipeline/filter/keyword.py` | Pass 1: title pattern matching |
| `pipeline/filter/llm_scorer.py` | Pass 2: Anthropic relevance scoring |
| `pipeline/filter/__init__.py` | `filter_jobs`: calls keyword then LLM, updates DB |
| `pipeline/notifier.py` | Terminal digest formatter + printer |
| `pipeline/runner.py` | Wires poller + filter + notifier |
| `pipeline/scheduler.py` | APScheduler daily trigger |
| `main.py` | CLI: add-company, list-companies, run, show-matches |
| `tests/conftest.py` | Shared in-memory DB fixture |

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `config.yaml`
- Create: `db/`, `models/`, `pipeline/`, `pipeline/discovery/`, `pipeline/discovery/clients/`, `pipeline/filter/`, `tests/` directories with `__init__.py` files

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "auto-apply"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "anthropic>=0.40",
    "apscheduler>=3.10",
    "click>=8.1",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create `config.yaml`**

```yaml
user:
  desired_role: "Software Engineer"
  desired_level: "Senior"
  resume_path: "./resume.pdf"

filter:
  include_patterns: ["software engineer", "swe", "backend engineer"]
  exclude_patterns: ["intern", "manager", "director", "vp", "head of"]
  level_patterns: ["senior", "l4", "l5", "sr.", "ic4", "ic5"]
  llm_score_threshold: 7.0

notifications:
  type: "terminal"
```

- [ ] **Step 3: Create directory structure and empty `__init__.py` files**

```bash
mkdir -p db models pipeline/discovery/clients pipeline/filter tests
touch models/__init__.py
touch pipeline/__init__.py
touch pipeline/discovery/__init__.py
touch pipeline/discovery/clients/__init__.py
touch pipeline/filter/__init__.py
touch tests/__init__.py
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -e ".[dev]"
```

Expected: no errors, packages installed.

- [ ] **Step 5: Verify pytest runs**

```bash
pytest tests/ -v
```

Expected: `no tests ran` (0 collected).

- [ ] **Step 6: Commit**

```bash
git init
echo "auto_apply.db" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.pyc" >> .gitignore
git add pyproject.toml config.yaml .gitignore
git add db/ models/ pipeline/ tests/
git commit -m "feat: project scaffolding"
```

---

### Task 2: Data Models

**Files:**
- Create: `models/company.py`
- Create: `models/job.py`
- Create: `models/digest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models.py
from models.company import Company
from models.job import Job, RawJob
from models.digest import DigestResult, CompanyDigest

def test_company_defaults():
    c = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                board_token="stripe", status="active")
    assert c.id is None
    assert c.detected_at is None

def test_job_defaults():
    j = Job(id="123", company_id=1, title="Senior SWE",
            url=None, location=None, description=None)
    assert j.filter_status == "new"
    assert j.llm_score is None

def test_raw_job_construction():
    r = RawJob(id="abc", title="Engineer", url=None, location=None, description=None)
    assert r.id == "abc"

def test_digest_result_defaults():
    d = DigestResult(date="2026-05-30")
    assert d.companies == []
    assert d.unsupported_companies == []

def test_company_digest_defaults():
    c = Company(name="X", slug="x", ats_type=None, board_token=None, status="active")
    cd = CompanyDigest(company=c)
    assert cd.matched == []
    assert cd.kw_filtered == []
    assert cd.llm_filtered == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError` (modules don't exist yet).

- [ ] **Step 3: Create `models/company.py`**

```python
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
```

- [ ] **Step 4: Create `models/job.py`**

```python
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
```

- [ ] **Step 5: Create `models/digest.py`**

```python
from dataclasses import dataclass, field
from models.company import Company
from models.job import Job

@dataclass
class CompanyDigest:
    company: Company
    matched: list[Job] = field(default_factory=list)
    kw_filtered: list[Job] = field(default_factory=list)
    llm_filtered: list[Job] = field(default_factory=list)

@dataclass
class DigestResult:
    date: str
    companies: list[CompanyDigest] = field(default_factory=list)
    unsupported_companies: list[Company] = field(default_factory=list)
```

- [ ] **Step 6: Run tests to confirm they pass**

```bash
pytest tests/test_models.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add models/company.py models/job.py models/digest.py tests/test_models.py
git commit -m "feat: add Company, Job, RawJob, DigestResult dataclasses"
```

---

### Task 3: Database Layer

**Files:**
- Create: `db/schema.sql`
- Create: `pipeline/db.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Create `db/schema.sql`**

```sql
CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    slug        TEXT    NOT NULL,
    ats_type    TEXT,
    board_token TEXT,
    status      TEXT    NOT NULL DEFAULT 'active',
    detected_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id             TEXT    NOT NULL,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    title          TEXT    NOT NULL,
    url            TEXT,
    location       TEXT,
    description    TEXT,
    first_seen_at  TEXT    NOT NULL,
    filter_status  TEXT    NOT NULL DEFAULT 'new',
    llm_score      REAL,
    llm_reason     TEXT,
    PRIMARY KEY (id, company_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    NOT NULL,
    company_id  INTEGER NOT NULL,
    applied_at  TEXT,
    status      TEXT
);
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/conftest.py
import pytest
import sqlite3
from pathlib import Path

@pytest.fixture
def db_conn():
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    conn.commit()
    yield conn
    conn.close()
```

```python
# tests/test_db.py
from models.company import Company
from models.job import Job
from pipeline.db import (
    upsert_company, get_all_companies, get_active_companies,
    get_seen_job_ids, upsert_jobs, update_job_filter_status, get_matched_jobs,
)

def test_upsert_company_creates_and_returns_id(db_conn):
    c = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                board_token="stripe", status="active")
    saved = upsert_company(db_conn, c)
    assert saved.id is not None

def test_upsert_company_updates_on_duplicate_name(db_conn):
    c = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                board_token="stripe", status="active")
    upsert_company(db_conn, c)
    c2 = Company(name="Stripe", slug="stripe", ats_type="lever",
                 board_token="stripe-new", status="active")
    saved = upsert_company(db_conn, c2)
    companies = get_all_companies(db_conn)
    assert len(companies) == 1
    assert companies[0].ats_type == "lever"

def test_get_active_companies_excludes_unsupported(db_conn):
    upsert_company(db_conn, Company(name="A", slug="a", ats_type="greenhouse",
                                    board_token="a", status="active"))
    upsert_company(db_conn, Company(name="B", slug="b", ats_type=None,
                                    board_token=None, status="unsupported"))
    assert len(get_active_companies(db_conn)) == 1

def test_get_seen_job_ids_returns_existing(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe",
                                         ats_type="greenhouse", board_token="stripe",
                                         status="active"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="SWE",
                               url=None, location=None, description=None)])
    seen = get_seen_job_ids(db_conn, c.id)
    assert "j1" in seen

def test_upsert_jobs_ignores_duplicate(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe",
                                         ats_type="greenhouse", board_token="stripe",
                                         status="active"))
    job = Job(id="j1", company_id=c.id, title="SWE", url=None, location=None, description=None)
    upsert_jobs(db_conn, [job])
    upsert_jobs(db_conn, [job])
    seen = get_seen_job_ids(db_conn, c.id)
    assert len(seen) == 1

def test_update_job_filter_status(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe",
                                         ats_type="greenhouse", board_token="stripe",
                                         status="active"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="SWE",
                               url=None, location=None, description=None)])
    update_job_filter_status(db_conn, "j1", c.id, "matched", 8.5, "strong match")
    matched = get_matched_jobs(db_conn)
    assert len(matched) == 1
    job, company = matched[0]
    assert job.llm_score == 8.5
    assert job.llm_reason == "strong match"
```

- [ ] **Step 3: Run tests to confirm they fail**

```bash
pytest tests/test_db.py -v
```

Expected: `ImportError` (pipeline.db not defined yet).

- [ ] **Step 4: Create `pipeline/db.py`**

```python
import sqlite3
from pathlib import Path
from datetime import datetime
from models.company import Company
from models.job import Job

def init_db(db_path: str = "auto_apply.db") -> sqlite3.Connection:
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(schema)
    conn.commit()
    return conn

def upsert_company(conn: sqlite3.Connection, company: Company) -> Company:
    conn.execute(
        """INSERT INTO companies (name, slug, ats_type, board_token, status, detected_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
             slug=excluded.slug,
             ats_type=excluded.ats_type,
             board_token=excluded.board_token,
             status=excluded.status,
             detected_at=excluded.detected_at""",
        (company.name, company.slug, company.ats_type, company.board_token,
         company.status, datetime.now().isoformat()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (company.name,)).fetchone()
    company.id = row["id"]
    return company

def get_all_companies(conn: sqlite3.Connection) -> list[Company]:
    rows = conn.execute("SELECT * FROM companies").fetchall()
    return [_row_to_company(row) for row in rows]

def get_active_companies(conn: sqlite3.Connection) -> list[Company]:
    rows = conn.execute("SELECT * FROM companies WHERE status = 'active'").fetchall()
    return [_row_to_company(row) for row in rows]

def get_seen_job_ids(conn: sqlite3.Connection, company_id: int) -> set[str]:
    rows = conn.execute("SELECT id FROM jobs WHERE company_id = ?", (company_id,)).fetchall()
    return {row["id"] for row in rows}

def upsert_jobs(conn: sqlite3.Connection, jobs: list[Job]) -> None:
    now = datetime.now().isoformat()
    conn.executemany(
        """INSERT INTO jobs (id, company_id, title, url, location, description, first_seen_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id, company_id) DO NOTHING""",
        [(j.id, j.company_id, j.title, j.url, j.location, j.description, now) for j in jobs],
    )
    conn.commit()

def update_job_filter_status(
    conn: sqlite3.Connection,
    job_id: str,
    company_id: int,
    status: str,
    llm_score: float | None = None,
    llm_reason: str | None = None,
) -> None:
    conn.execute(
        "UPDATE jobs SET filter_status=?, llm_score=?, llm_reason=? WHERE id=? AND company_id=?",
        (status, llm_score, llm_reason, job_id, company_id),
    )
    conn.commit()

def get_matched_jobs(conn: sqlite3.Connection, days: int = 7) -> list[tuple[Job, Company]]:
    rows = conn.execute(
        """SELECT j.id as job_id, j.company_id, j.title, j.url, j.location, j.description,
                  j.first_seen_at, j.filter_status, j.llm_score, j.llm_reason,
                  c.id as company_db_id, c.name as company_name, c.slug as company_slug,
                  c.ats_type, c.board_token, c.status as company_status
           FROM jobs j JOIN companies c ON j.company_id = c.id
           WHERE j.filter_status = 'matched'
             AND j.first_seen_at >= datetime('now', ?)
           ORDER BY j.first_seen_at DESC""",
        (f"-{days} days",),
    ).fetchall()
    return [(_row_to_job(row), _row_to_company_from_join(row)) for row in rows]

def _row_to_company(row: sqlite3.Row) -> Company:
    return Company(
        id=row["id"], name=row["name"], slug=row["slug"],
        ats_type=row["ats_type"], board_token=row["board_token"], status=row["status"],
    )

def _row_to_company_from_join(row: sqlite3.Row) -> Company:
    return Company(
        id=row["company_db_id"], name=row["company_name"], slug=row["company_slug"],
        ats_type=row["ats_type"], board_token=row["board_token"], status=row["company_status"],
    )

def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["job_id"], company_id=row["company_id"], title=row["title"],
        url=row["url"], location=row["location"], description=row["description"],
        first_seen_at=row["first_seen_at"], filter_status=row["filter_status"],
        llm_score=row["llm_score"], llm_reason=row["llm_reason"],
    )
```

- [ ] **Step 5: Run tests to confirm they pass**

```bash
pytest tests/test_db.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add db/schema.sql pipeline/db.py tests/conftest.py tests/test_db.py
git commit -m "feat: add SQLite schema and DB CRUD layer"
```

---

### Task 4: Config Loader

**Files:**
- Create: `pipeline/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

First, create a fixture config file for tests:

```python
# tests/test_config.py
import pytest
import yaml
from pathlib import Path
from pipeline.config import load_config, Config, UserConfig, FilterConfig

@pytest.fixture
def config_file(tmp_path):
    content = {
        "user": {
            "desired_role": "Software Engineer",
            "desired_level": "Senior",
            "resume_path": "./resume.pdf",
        },
        "filter": {
            "include_patterns": ["software engineer"],
            "exclude_patterns": ["intern"],
            "level_patterns": ["senior"],
            "llm_score_threshold": 7.0,
        },
        "notifications": {"type": "terminal"},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(content))
    return str(p)

def test_load_config_returns_typed_config(config_file):
    config = load_config(config_file)
    assert isinstance(config, Config)
    assert isinstance(config.user, UserConfig)
    assert isinstance(config.filter, FilterConfig)

def test_load_config_user_fields(config_file):
    config = load_config(config_file)
    assert config.user.desired_role == "Software Engineer"
    assert config.user.desired_level == "Senior"

def test_load_config_filter_fields(config_file):
    config = load_config(config_file)
    assert config.filter.llm_score_threshold == 7.0
    assert "intern" in config.filter.exclude_patterns
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/config.py`**

```python
from dataclasses import dataclass
import yaml

@dataclass
class UserConfig:
    desired_role: str
    desired_level: str
    resume_path: str

@dataclass
class FilterConfig:
    include_patterns: list[str]
    exclude_patterns: list[str]
    level_patterns: list[str]
    llm_score_threshold: float

@dataclass
class NotificationsConfig:
    type: str

@dataclass
class Config:
    user: UserConfig
    filter: FilterConfig
    notifications: NotificationsConfig

def load_config(path: str = "config.yaml") -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config(
        user=UserConfig(**data["user"]),
        filter=FilterConfig(**data["filter"]),
        notifications=NotificationsConfig(**data["notifications"]),
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/config.py tests/test_config.py
git commit -m "feat: add config loader"
```

---

### Task 5: Greenhouse ATS Client

**Files:**
- Create: `pipeline/discovery/clients/greenhouse.py`
- Create: `tests/test_clients.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_clients.py
from unittest.mock import patch, MagicMock
from models.job import RawJob

def _mock_get(status_code, json_data):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock(
        side_effect=None if status_code == 200 else Exception("HTTP Error")
    )
    return response

def test_greenhouse_parses_jobs():
    json_data = {
        "jobs": [
            {
                "id": 12345,
                "title": "Senior Software Engineer",
                "location": {"name": "San Francisco"},
                "absolute_url": "https://boards.greenhouse.io/stripe/jobs/12345",
                "content": "<p>Description here</p>",
            }
        ]
    }
    with patch("pipeline.discovery.clients.greenhouse.httpx.get",
               return_value=_mock_get(200, json_data)):
        from pipeline.discovery.clients.greenhouse import fetch_jobs
        jobs = fetch_jobs("stripe")

    assert len(jobs) == 1
    assert jobs[0].id == "12345"
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].location == "San Francisco"
    assert jobs[0].url == "https://boards.greenhouse.io/stripe/jobs/12345"
    assert "<p>" in jobs[0].description
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_clients.py::test_greenhouse_parses_jobs -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/discovery/clients/greenhouse.py`**

```python
import httpx
from models.job import RawJob

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

def fetch_jobs(board_token: str) -> list[RawJob]:
    url = GREENHOUSE_URL.format(token=board_token)
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    return [
        RawJob(
            id=str(job["id"]),
            title=job["title"],
            url=job.get("absolute_url"),
            location=job.get("location", {}).get("name"),
            description=job.get("content"),
        )
        for job in data.get("jobs", [])
    ]
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest tests/test_clients.py::test_greenhouse_parses_jobs -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/clients/greenhouse.py tests/test_clients.py
git commit -m "feat: add Greenhouse ATS client"
```

---

### Task 6: Lever ATS Client

**Files:**
- Modify: `pipeline/discovery/clients/lever.py` (create)
- Modify: `tests/test_clients.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_clients.py`:

```python
def test_lever_parses_jobs():
    json_data = [
        {
            "id": "abc123-def456",
            "text": "Senior Software Engineer",
            "categories": {"location": "Remote"},
            "hostedUrl": "https://jobs.lever.co/stripe/abc123-def456",
            "descriptionPlain": "We are looking for a senior engineer...",
        }
    ]
    with patch("pipeline.discovery.clients.lever.httpx.get",
               return_value=_mock_get(200, json_data)):
        from pipeline.discovery.clients.lever import fetch_jobs
        jobs = fetch_jobs("stripe")

    assert len(jobs) == 1
    assert jobs[0].id == "abc123-def456"
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "https://jobs.lever.co/stripe/abc123-def456"
    assert "senior engineer" in jobs[0].description
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_clients.py::test_lever_parses_jobs -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/discovery/clients/lever.py`**

```python
import httpx
from models.job import RawJob

LEVER_URL = "https://api.lever.co/v0/postings/{token}"

def fetch_jobs(board_token: str) -> list[RawJob]:
    url = LEVER_URL.format(token=board_token)
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    return [
        RawJob(
            id=job["id"],
            title=job["text"],
            url=job.get("hostedUrl"),
            location=job.get("categories", {}).get("location"),
            description=job.get("descriptionPlain"),
        )
        for job in data
    ]
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest tests/test_clients.py::test_lever_parses_jobs -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/clients/lever.py tests/test_clients.py
git commit -m "feat: add Lever ATS client"
```

---

### Task 7: Ashby ATS Client

**Files:**
- Create: `pipeline/discovery/clients/ashby.py`
- Modify: `tests/test_clients.py` (add test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_clients.py`:

```python
def test_ashby_parses_jobs():
    json_data = {
        "jobs": [
            {
                "id": "xyz-789",
                "title": "Senior Software Engineer",
                "locationName": "New York",
                "jobUrl": "https://jobs.ashbyhq.com/stripe/xyz-789",
                "descriptionHtml": "<p>We are looking for talent.</p>",
            }
        ]
    }
    with patch("pipeline.discovery.clients.ashby.httpx.get",
               return_value=_mock_get(200, json_data)):
        from pipeline.discovery.clients.ashby import fetch_jobs
        jobs = fetch_jobs("stripe")

    assert len(jobs) == 1
    assert jobs[0].id == "xyz-789"
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].location == "New York"
    assert jobs[0].url == "https://jobs.ashbyhq.com/stripe/xyz-789"
    assert "<p>" in jobs[0].description
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
pytest tests/test_clients.py::test_ashby_parses_jobs -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/discovery/clients/ashby.py`**

```python
import httpx
from models.job import RawJob

ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"

def fetch_jobs(board_token: str) -> list[RawJob]:
    url = ASHBY_URL.format(token=board_token)
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    return [
        RawJob(
            id=job["id"],
            title=job["title"],
            url=job.get("jobUrl"),
            location=job.get("locationName"),
            description=job.get("descriptionHtml"),
        )
        for job in data.get("jobs", [])
    ]
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
pytest tests/test_clients.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/clients/ashby.py tests/test_clients.py
git commit -m "feat: add Ashby ATS client"
```

---

### Task 8: ATS Auto-Detector

**Files:**
- Create: `pipeline/discovery/detector.py`
- Create: `tests/test_detector.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_detector.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pipeline.discovery.detector import generate_slug_variants, detect_ats

def test_slug_variants_simple():
    variants = generate_slug_variants("Stripe")
    assert "stripe" in variants

def test_slug_variants_with_space():
    variants = generate_slug_variants("Open AI")
    assert "open-ai" in variants
    assert "openai" in variants
    assert "open_ai" in variants

def test_slug_variants_strips_legal_suffix():
    variants = generate_slug_variants("Acme Corp")
    assert "acme" in variants

def test_slug_variants_strips_punctuation():
    variants = generate_slug_variants("Stripe, Inc.")
    assert "stripe" in variants

async def test_detect_ats_finds_greenhouse():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200 if "boards-api.greenhouse.io" in url and "/stripe" in url else 404
        return r

    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client

        result = await detect_ats("Stripe")

    assert result is not None
    ats_type, board_token = result
    assert ats_type == "greenhouse"
    assert board_token == "stripe"

async def test_detect_ats_returns_none_when_not_found():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 404
        return r

    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client

        result = await detect_ats("UnknownCorp XYZ")

    assert result is None

async def test_detect_ats_uses_slug_override():
    async def mock_get(url, **kwargs):
        r = MagicMock()
        r.status_code = 200 if "api.lever.co" in url and "/lever-slug" in url else 404
        return r

    with patch("pipeline.discovery.detector.httpx.AsyncClient") as MockClient:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get
        MockClient.return_value = mock_client

        result = await detect_ats("Some Company", slug_override="lever-slug")

    assert result is not None
    assert result[0] == "lever"
    assert result[1] == "lever-slug"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_detector.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/discovery/detector.py`**

```python
import re
import asyncio
import httpx
from pipeline.discovery.clients.greenhouse import GREENHOUSE_URL
from pipeline.discovery.clients.lever import LEVER_URL
from pipeline.discovery.clients.ashby import ASHBY_URL

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
    return None
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_detector.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/detector.py tests/test_detector.py
git commit -m "feat: add ATS auto-detector with slug variant generation"
```

---

### Task 9: Job Poller

**Files:**
- Create: `pipeline/discovery/poller.py`
- Create: `tests/test_poller.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_poller.py
from unittest.mock import patch
from models.company import Company
from models.job import Job, RawJob
from pipeline.db import upsert_company, upsert_jobs, get_seen_job_ids
from pipeline.discovery.poller import poll_company

def test_poll_returns_only_new_jobs(db_conn):
    company = upsert_company(db_conn, Company(
        name="Stripe", slug="stripe", ats_type="greenhouse",
        board_token="stripe", status="active"
    ))
    upsert_jobs(db_conn, [Job(id="old-1", company_id=company.id, title="Old Job",
                               url=None, location=None, description=None)])

    raw = [
        RawJob(id="old-1", title="Old Job", url=None, location=None, description=None),
        RawJob(id="new-2", title="New Job", url=None, location=None, description=None),
    ]
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", return_value=raw):
        new_jobs = poll_company(company, db_conn)

    assert len(new_jobs) == 1
    assert new_jobs[0].id == "new-2"
    assert new_jobs[0].company_id == company.id

def test_poll_persists_all_jobs_not_just_new(db_conn):
    company = upsert_company(db_conn, Company(
        name="Stripe", slug="stripe", ats_type="greenhouse",
        board_token="stripe", status="active"
    ))
    raw = [RawJob(id="j1", title="Job 1", url=None, location=None, description=None)]
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", return_value=raw):
        poll_company(company, db_conn)

    seen = get_seen_job_ids(db_conn, company.id)
    assert "j1" in seen

def test_poll_returns_empty_on_http_error(db_conn):
    import httpx
    company = upsert_company(db_conn, Company(
        name="Stripe", slug="stripe", ats_type="greenhouse",
        board_token="stripe", status="active"
    ))
    with patch("pipeline.discovery.poller.fetch_jobs_for_company",
               side_effect=httpx.HTTPError("connection refused")):
        new_jobs = poll_company(company, db_conn)

    assert new_jobs == []
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_poller.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/discovery/poller.py`**

```python
import sqlite3
import httpx
from models.company import Company
from models.job import Job, RawJob
from pipeline.db import get_seen_job_ids, upsert_jobs
from pipeline.discovery.clients import greenhouse, lever, ashby

_CLIENT_MAP = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
}

def fetch_jobs_for_company(company: Company) -> list[RawJob]:
    return _CLIENT_MAP[company.ats_type](company.board_token)

def poll_company(company: Company, conn: sqlite3.Connection) -> list[Job]:
    try:
        raw_jobs = fetch_jobs_for_company(company)
    except httpx.HTTPError as e:
        print(f"⚠ Failed to fetch jobs for {company.name}: {e}")
        return []

    seen_ids = get_seen_job_ids(conn, company.id)
    all_jobs = [
        Job(id=r.id, company_id=company.id, title=r.title,
            url=r.url, location=r.location, description=r.description)
        for r in raw_jobs
    ]
    upsert_jobs(conn, all_jobs)
    return [j for j in all_jobs if j.id not in seen_ids]
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_poller.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/poller.py tests/test_poller.py
git commit -m "feat: add job poller with new-job diffing"
```

---

### Task 10: Keyword Filter

**Files:**
- Create: `pipeline/filter/keyword.py`
- Create: `tests/test_keyword.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_keyword.py
from models.job import Job
from pipeline.config import FilterConfig
from pipeline.filter.keyword import keyword_filter

def _job(title: str) -> Job:
    return Job(id="1", company_id=1, title=title, url=None, location=None, description=None)

def _config(**overrides) -> FilterConfig:
    defaults = {
        "include_patterns": ["software engineer"],
        "exclude_patterns": ["intern", "manager"],
        "level_patterns": ["senior"],
        "llm_score_threshold": 7.0,
    }
    defaults.update(overrides)
    return FilterConfig(**defaults)

def test_matching_include_pattern_passes():
    assert keyword_filter(_job("Senior Software Engineer"), _config()) is True

def test_no_include_match_fails():
    assert keyword_filter(_job("Product Manager"), _config()) is False

def test_exclude_pattern_rejects():
    assert keyword_filter(_job("Software Engineer Intern"), _config()) is False

def test_no_level_match_fails_when_level_patterns_set():
    assert keyword_filter(_job("Software Engineer"), _config()) is False

def test_empty_level_patterns_allows_any_level():
    assert keyword_filter(_job("Software Engineer"), _config(level_patterns=[])) is True

def test_case_insensitive_matching():
    assert keyword_filter(_job("SENIOR SOFTWARE ENGINEER"), _config()) is True
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_keyword.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/filter/keyword.py`**

```python
from models.job import Job
from pipeline.config import FilterConfig

def keyword_filter(job: Job, config: FilterConfig) -> bool:
    title = job.title.lower()
    if not any(p.lower() in title for p in config.include_patterns):
        return False
    if any(p.lower() in title for p in config.exclude_patterns):
        return False
    if config.level_patterns and not any(p.lower() in title for p in config.level_patterns):
        return False
    return True
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_keyword.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/filter/keyword.py tests/test_keyword.py
git commit -m "feat: add keyword pre-filter"
```

---

### Task 11: LLM Scorer

**Files:**
- Create: `pipeline/filter/llm_scorer.py`
- Create: `tests/test_llm_scorer.py`

**Prerequisite:** Set `ANTHROPIC_API_KEY` environment variable before running the pipeline (not needed for tests, which mock the client).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_scorer.py
from unittest.mock import MagicMock, patch
from models.job import Job
from pipeline.config import UserConfig
from pipeline.filter.llm_scorer import score_job

def _user_config():
    return UserConfig(desired_role="Software Engineer", desired_level="Senior",
                      resume_path="./resume.pdf")

def _job():
    return Job(id="1", company_id=1, title="Senior SWE",
               url=None, location=None, description="We need a senior engineer.")

def _mock_anthropic(response_text: str):
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client

def test_score_job_returns_score_and_reason():
    mock_client = _mock_anthropic('{"score": 8.5, "reason": "strong match"}')
    with patch("pipeline.filter.llm_scorer.anthropic.Anthropic", return_value=mock_client):
        score, reason = score_job(_job(), _user_config())
    assert score == 8.5
    assert reason == "strong match"

def test_score_job_sends_desired_role_in_system_prompt():
    mock_client = _mock_anthropic('{"score": 6.0, "reason": "ok match"}')
    with patch("pipeline.filter.llm_scorer.anthropic.Anthropic", return_value=mock_client):
        score_job(_job(), _user_config())
    call_kwargs = mock_client.messages.create.call_args
    system_prompt = call_kwargs.kwargs["system"]
    assert "Software Engineer" in system_prompt
    assert "Senior" in system_prompt

def test_score_job_returns_zero_on_invalid_json():
    mock_client = _mock_anthropic("not valid json")
    with patch("pipeline.filter.llm_scorer.anthropic.Anthropic", return_value=mock_client):
        score, reason = score_job(_job(), _user_config())
    assert score == 0.0
    assert "parse" in reason.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_llm_scorer.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/filter/llm_scorer.py`**

```python
import json
import anthropic
from models.job import Job
from pipeline.config import UserConfig

def score_job(job: Job, user_config: UserConfig) -> tuple[float, str]:
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=(
                f"You are evaluating job postings for a candidate. "
                f"Desired role: {user_config.desired_role}. "
                f"Desired level: {user_config.desired_level}."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Title: {job.title}\n"
                    f"Description: {job.description or '(no description)'}\n\n"
                    "Rate relevance 0-10. Criteria:\n"
                    "- Is this the right role type?\n"
                    "- Is this the right seniority level?\n"
                    "- Is this full-time (not contract/intern)?\n\n"
                    'Reply ONLY as JSON: {"score": 8.0, "reason": "one sentence"}'
                ),
            }],
        )
        data = json.loads(response.content[0].text)
        return float(data["score"]), str(data["reason"])
    except (json.JSONDecodeError, KeyError):
        return 0.0, "failed to parse LLM response"
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_llm_scorer.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/filter/llm_scorer.py tests/test_llm_scorer.py
git commit -m "feat: add LLM relevance scorer using Claude Haiku"
```

---

### Task 12: Filter Coordinator

**Files:**
- Modify: `pipeline/filter/__init__.py`
- Create: `tests/test_filter.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_filter.py
from unittest.mock import patch
from models.company import Company
from models.job import Job
from pipeline.config import Config, UserConfig, FilterConfig, NotificationsConfig
from pipeline.db import upsert_company, upsert_jobs
from pipeline.filter import filter_jobs

def _config(threshold: float = 7.0) -> Config:
    return Config(
        user=UserConfig(desired_role="Software Engineer", desired_level="Senior",
                        resume_path="./resume.pdf"),
        filter=FilterConfig(
            include_patterns=["software engineer"],
            exclude_patterns=["intern"],
            level_patterns=["senior"],
            llm_score_threshold=threshold,
        ),
        notifications=NotificationsConfig(type="terminal"),
    )

def _seed_jobs(db_conn) -> tuple[Company, list[Job]]:
    company = upsert_company(db_conn, Company(
        name="Stripe", slug="stripe", ats_type="greenhouse",
        board_token="stripe", status="active"
    ))
    jobs = [
        Job(id="j1", company_id=company.id, title="Senior Software Engineer",
            url=None, location=None, description="Great role"),
        Job(id="j2", company_id=company.id, title="Software Engineer Intern",
            url=None, location=None, description="Internship"),
        Job(id="j3", company_id=company.id, title="Senior Software Engineer II",
            url=None, location=None, description="Another good role"),
    ]
    upsert_jobs(db_conn, jobs)
    return company, jobs

def test_filter_jobs_routes_to_correct_buckets(db_conn):
    _, jobs = _seed_jobs(db_conn)
    with patch("pipeline.filter.score_job", return_value=(8.0, "strong match")):
        matched, kw_filtered, llm_filtered = filter_jobs(jobs, _config(), db_conn)
    assert len(kw_filtered) == 1
    assert kw_filtered[0].id == "j2"
    assert len(matched) == 2

def test_filter_jobs_routes_to_llm_filtered_below_threshold(db_conn):
    _, jobs = _seed_jobs(db_conn)
    with patch("pipeline.filter.score_job", return_value=(5.0, "weak match")):
        matched, kw_filtered, llm_filtered = filter_jobs(jobs, _config(), db_conn)
    assert len(llm_filtered) == 2
    assert len(matched) == 0

def test_filter_jobs_sets_llm_score_on_job(db_conn):
    _, jobs = _seed_jobs(db_conn)
    with patch("pipeline.filter.score_job", return_value=(9.1, "exact match")):
        matched, _, _ = filter_jobs(jobs, _config(), db_conn)
    assert matched[0].llm_score == 9.1
    assert matched[0].llm_reason == "exact match"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_filter.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Write `pipeline/filter/__init__.py`**

```python
import sqlite3
from models.job import Job
from pipeline.config import Config
from pipeline.db import update_job_filter_status
from pipeline.filter.keyword import keyword_filter
from pipeline.filter.llm_scorer import score_job

def filter_jobs(
    jobs: list[Job], config: Config, conn: sqlite3.Connection
) -> tuple[list[Job], list[Job], list[Job]]:
    matched, kw_filtered, llm_filtered = [], [], []
    for job in jobs:
        if not keyword_filter(job, config.filter):
            update_job_filter_status(conn, job.id, job.company_id, "kw_filtered")
            job.filter_status = "kw_filtered"
            kw_filtered.append(job)
            continue
        score, reason = score_job(job, config.user)
        job.llm_score = score
        job.llm_reason = reason
        if score >= config.filter.llm_score_threshold:
            update_job_filter_status(conn, job.id, job.company_id, "matched", score, reason)
            job.filter_status = "matched"
            matched.append(job)
        else:
            update_job_filter_status(conn, job.id, job.company_id, "llm_filtered", score, reason)
            job.filter_status = "llm_filtered"
            llm_filtered.append(job)
    return matched, kw_filtered, llm_filtered
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_filter.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/filter/__init__.py tests/test_filter.py
git commit -m "feat: add filter coordinator wiring keyword and LLM stages"
```

---

### Task 13: Notifier

**Files:**
- Create: `pipeline/notifier.py`
- Create: `tests/test_notifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_notifier.py
from models.company import Company
from models.job import Job
from models.digest import DigestResult, CompanyDigest
from pipeline.notifier import format_digest

def _company(name="Stripe", ats="greenhouse"):
    return Company(name=name, slug=name.lower(), ats_type=ats,
                   board_token=name.lower(), status="active")

def _job(title="Senior SWE", score=8.5, reason="good match", status="matched"):
    j = Job(id="1", company_id=1, title=title, url=None, location=None, description=None)
    j.filter_status = status
    j.llm_score = score
    j.llm_reason = reason
    return j

def test_format_digest_includes_matched_job():
    digest = DigestResult(
        date="2026-05-30",
        companies=[CompanyDigest(company=_company(), matched=[_job()])],
    )
    output = format_digest(digest)
    assert "Senior SWE" in output
    assert "8.5" in output
    assert "good match" in output
    assert "✓" in output

def test_format_digest_includes_kw_filtered_job():
    kw_job = _job(title="Staff Engineer", status="kw_filtered", score=None, reason=None)
    kw_job.llm_score = None
    digest = DigestResult(
        date="2026-05-30",
        companies=[CompanyDigest(company=_company(), kw_filtered=[kw_job])],
    )
    output = format_digest(digest)
    assert "kw_filtered" in output
    assert "Staff Engineer" in output

def test_format_digest_includes_unsupported_company():
    unsupported = Company(name="Acme", slug="acme", ats_type=None,
                          board_token=None, status="unsupported")
    digest = DigestResult(date="2026-05-30", unsupported_companies=[unsupported])
    output = format_digest(digest)
    assert "Acme" in output
    assert "Unsupported" in output

def test_format_digest_shows_total_matched_count():
    digest = DigestResult(
        date="2026-05-30",
        companies=[CompanyDigest(company=_company(), matched=[_job(), _job(title="SWE II")])],
    )
    output = format_digest(digest)
    assert "2 new matched" in output
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_notifier.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/notifier.py`**

```python
from models.digest import DigestResult

def format_digest(result: DigestResult) -> str:
    lines = [f"=== Auto-Apply Daily Digest — {result.date} ===\n"]
    for cd in result.companies:
        ats = cd.company.ats_type.capitalize() if cd.company.ats_type else "Unknown"
        lines.append(f"{cd.company.name} ({ats})")
        for job in cd.matched:
            score = f"{job.llm_score:.1f}" if job.llm_score is not None else "N/A"
            lines.append(f'  ✓ {job.title} — score {score} — "{job.llm_reason}"')
        for job in cd.kw_filtered:
            lines.append(f"  ✗ [kw_filtered] {job.title}")
        for job in cd.llm_filtered:
            score = f"{job.llm_score:.1f}" if job.llm_score is not None else "N/A"
            lines.append(f"  ✗ [llm_filtered] {job.title} — score {score}")
        if not (cd.matched or cd.kw_filtered or cd.llm_filtered):
            lines.append("  (no new postings)")
        lines.append("")
    for company in result.unsupported_companies:
        lines.append(f"{company.name}")
        lines.append(
            f'  ⚠ Unsupported ATS — run: python main.py add-company --name "{company.name}" --slug <slug>'
        )
        lines.append("")
    total = sum(len(cd.matched) for cd in result.companies)
    lines.append(f"{total} new matched job(s). Run `python main.py show-matches` to review.")
    return "\n".join(lines)

def print_digest(result: DigestResult) -> None:
    print(format_digest(result))
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_notifier.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pipeline/notifier.py tests/test_notifier.py
git commit -m "feat: add terminal digest formatter"
```

---

### Task 14: Pipeline Runner

**Files:**
- Create: `pipeline/runner.py`
- Create: `tests/test_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
from unittest.mock import patch
from models.company import Company
from models.job import Job
from models.digest import DigestResult
from pipeline.config import Config, UserConfig, FilterConfig, NotificationsConfig
from pipeline.db import upsert_company
from pipeline.runner import run_pipeline

def _config():
    return Config(
        user=UserConfig(desired_role="Software Engineer", desired_level="Senior",
                        resume_path="./resume.pdf"),
        filter=FilterConfig(include_patterns=["software engineer"], exclude_patterns=[],
                            level_patterns=[], llm_score_threshold=7.0),
        notifications=NotificationsConfig(type="terminal"),
    )

def test_run_pipeline_returns_digest(db_conn):
    upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                                    board_token="stripe", status="active"))
    new_job = Job(id="j1", company_id=1, title="Senior Software Engineer",
                  url=None, location=None, description="Great role")
    with patch("pipeline.runner.poll_company", return_value=[new_job]), \
         patch("pipeline.runner.filter_jobs", return_value=([new_job], [], [])):
        result = run_pipeline(_config(), db_conn)
    assert isinstance(result, DigestResult)
    assert len(result.companies) == 1
    assert result.companies[0].matched == [new_job]

def test_run_pipeline_includes_unsupported_companies(db_conn):
    upsert_company(db_conn, Company(name="Acme", slug="acme", ats_type=None,
                                    board_token=None, status="unsupported"))
    with patch("pipeline.runner.poll_company", return_value=[]), \
         patch("pipeline.runner.filter_jobs", return_value=([], [], [])):
        result = run_pipeline(_config(), db_conn)
    assert len(result.unsupported_companies) == 1
    assert result.unsupported_companies[0].name == "Acme"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_runner.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Create `pipeline/runner.py`**

```python
import sqlite3
from datetime import datetime
from models.digest import DigestResult, CompanyDigest
from pipeline.config import Config
from pipeline.db import get_active_companies, get_all_companies
from pipeline.discovery.poller import poll_company
from pipeline.filter import filter_jobs

def run_pipeline(config: Config, conn: sqlite3.Connection) -> DigestResult:
    active = get_active_companies(conn)
    all_companies = get_all_companies(conn)
    unsupported = [c for c in all_companies if c.status == "unsupported"]
    company_digests = []
    for company in active:
        new_jobs = poll_company(company, conn)
        matched, kw_filtered, llm_filtered = filter_jobs(new_jobs, config, conn)
        company_digests.append(CompanyDigest(
            company=company,
            matched=matched,
            kw_filtered=kw_filtered,
            llm_filtered=llm_filtered,
        ))
    return DigestResult(
        date=datetime.now().strftime("%Y-%m-%d"),
        companies=company_digests,
        unsupported_companies=unsupported,
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_runner.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pipeline/runner.py tests/test_runner.py
git commit -m "feat: add pipeline runner wiring discovery and filter"
```

---

### Task 15: Scheduler

**Files:**
- Create: `pipeline/scheduler.py`

No tests for the scheduler itself — APScheduler's trigger behavior is tested by the library. Integration is verified manually in Task 16.

- [ ] **Step 1: Create `pipeline/scheduler.py`**

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from pipeline.config import Config
from pipeline.db import init_db
from pipeline.runner import run_pipeline
from pipeline.notifier import print_digest

def start_scheduler(config: Config, db_path: str = "auto_apply.db") -> None:
    scheduler = BlockingScheduler()

    def daily_job():
        conn = init_db(db_path)
        try:
            result = run_pipeline(config, conn)
            print_digest(result)
        finally:
            conn.close()

    scheduler.add_job(daily_job, "cron", hour=8, minute=0)
    print("Scheduler started. Running daily at 08:00. Press Ctrl+C to stop.")
    scheduler.start()
```

- [ ] **Step 2: Commit**

```bash
git add pipeline/scheduler.py
git commit -m "feat: add APScheduler daily trigger"
```

---

### Task 16: CLI

**Files:**
- Create: `main.py`

- [ ] **Step 1: Create `main.py`**

```python
import asyncio
import click
from datetime import datetime
from pipeline.config import load_config
from pipeline.db import init_db, upsert_company, get_all_companies, get_matched_jobs
from pipeline.discovery.detector import detect_ats
from pipeline.runner import run_pipeline
from pipeline.notifier import print_digest
from pipeline.scheduler import start_scheduler
from models.company import Company

DB_PATH = "auto_apply.db"
CONFIG_PATH = "config.yaml"

@click.group()
def cli():
    pass

@cli.command()
@click.option("--name", required=True, help="Company name")
@click.option("--slug", default=None, help="ATS board slug (optional override)")
def add_company(name, slug):
    """Detect and register a company's ATS."""
    conn = init_db(DB_PATH)
    try:
        result = asyncio.run(detect_ats(name, slug))
        if result is None:
            ats_type, board_token, status = None, None, "unsupported"
            click.echo(f"⚠ Could not detect ATS for '{name}'. Try --slug <slug> to specify.")
        else:
            ats_type, board_token = result
            status = "active"
            click.echo(f"✓ {name} → {ats_type} (token: {board_token})")
        company = Company(
            name=name,
            slug=board_token or name.lower().replace(" ", "-"),
            ats_type=ats_type,
            board_token=board_token,
            status=status,
        )
        upsert_company(conn, company)
    finally:
        conn.close()

@cli.command()
def list_companies():
    """List all registered companies."""
    conn = init_db(DB_PATH)
    try:
        companies = get_all_companies(conn)
        if not companies:
            click.echo("No companies registered. Use `add-company` to add one.")
            return
        for c in companies:
            ats = c.ats_type or "unsupported"
            token = c.board_token or "-"
            click.echo(f"  {c.name:<30} {ats:<12} {token}")
    finally:
        conn.close()

@cli.command()
@click.option("--schedule", is_flag=True, default=False,
              help="Run on daily schedule instead of once")
def run(schedule):
    """Run the discovery + filter pipeline."""
    config = load_config(CONFIG_PATH)
    if schedule:
        start_scheduler(config, DB_PATH)
    else:
        conn = init_db(DB_PATH)
        try:
            result = run_pipeline(config, conn)
            print_digest(result)
        finally:
            conn.close()

@cli.command()
@click.option("--days", default=7, show_default=True, help="Look back N days")
def show_matches(days):
    """Show matched jobs from the last N days."""
    conn = init_db(DB_PATH)
    try:
        results = get_matched_jobs(conn, days)
        if not results:
            click.echo(f"No matched jobs in the last {days} days.")
            return
        for job, company in results:
            score = f"{job.llm_score:.1f}" if job.llm_score is not None else "N/A"
            click.echo(f"  [{company.name}] {job.title} — score {score}")
            if job.llm_reason:
                click.echo(f"    {job.llm_reason}")
            if job.url:
                click.echo(f"    {job.url}")
    finally:
        conn.close()

if __name__ == "__main__":
    cli()
```

- [ ] **Step 2: Smoke-test the CLI**

```bash
python main.py --help
```

Expected output:
```
Usage: main.py [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  add-company     Detect and register a company's ATS.
  list-companies  List all registered companies.
  run             Run the discovery + filter pipeline.
  show-matches    Show matched jobs from the last N days.
```

- [ ] **Step 3: Run full test suite one final time**

```bash
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat: add CLI (add-company, list-companies, run, show-matches)"
```

---

## End-to-End Smoke Test

After Task 16, verify the full pipeline manually:

```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Register a company (uses live ATS probing)
python main.py add-company --name "Stripe"

# Confirm it was registered
python main.py list-companies

# Run the pipeline once
python main.py run

# Review matched jobs
python main.py show-matches
```
