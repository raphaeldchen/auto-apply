# Job Lifecycle Tracker & Higher-Frequency Polling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the auto-apply tool into a scraper *and* tracker — detect when captured jobs close (disappearance from the board), poll on a configurable interval, and track the user's own application status.

**Architecture:** Because the poller already fetches a company's entire ATS board each run, disappearance from that board is a near-free, authoritative closure signal. `poll_company` returns a richer `PollResult(success, current_ids, new_jobs)` so reconciliation only runs on a successful fetch (guarding against a blocked poll falsely closing everything). The posting's lifecycle (`open`/`closed`) lives on `jobs`; the user's application status lives in the separate `applications` table.

**Tech Stack:** Python 3.14, Click, APScheduler, PyYAML, SQLite, pytest (+ pytest-asyncio, `asyncio_mode = auto`).

## Global Constraints

- Run tests with `python3 -m pytest` (no bare `python` on this machine).
- Tests default to `-m 'not integration'` (see `pyproject.toml`).
- Reconciliation runs **only** when a poll succeeded (no client exception). A failed poll must touch no rows.
- Closure is factual: a job that leaves the board is `closed` regardless of application status. Application rows are preserved independently.
- Job states are exactly `open` | `closed`. No time-based expiry, no hard-delete GC.
- Application statuses are exactly `applied` | `interviewing` | `offer` | `rejected`.
- New schema columns are additive with safe defaults; existing local DBs must upgrade in place via idempotent `ALTER TABLE` guards (the schema is applied with `CREATE TABLE IF NOT EXISTS`, which will not add columns to an existing DB).
- The `db_conn` test fixture (`tests/conftest.py`) loads `db/schema.sql` directly (not via `init_db`), so all lifecycle columns and the applications uniqueness constraint must be present in `db/schema.sql` itself, not only in the migration path.

---

### Task 1: Schema + in-place migration

**Files:**
- Modify: `db/schema.sql`
- Modify: `pipeline/db.py` (add `_column_names`, `_migrate`; call `_migrate` from `init_db`)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: existing `init_db(db_path) -> sqlite3.Connection`.
- Produces: `jobs` has columns `job_state` (default `'open'`), `last_seen_at`, `closed_at`; `applications` has `updated_at` and a unique `(job_id, company_id)`. `init_db` upgrades pre-existing DBs in place.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_init_db_has_lifecycle_columns(tmp_path):
    from pipeline.db import init_db
    conn = init_db(str(tmp_path / "fresh.db"))
    job_cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"job_state", "last_seen_at", "closed_at"} <= job_cols
    app_cols = {r["name"] for r in conn.execute("PRAGMA table_info(applications)")}
    assert "updated_at" in app_cols
    conn.close()


def test_applications_reject_duplicate_pair(tmp_path):
    import sqlite3
    import pytest
    from pipeline.db import init_db
    conn = init_db(str(tmp_path / "fresh.db"))
    conn.execute("INSERT INTO applications (job_id, company_id, status) VALUES ('j1', 1, 'applied')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO applications (job_id, company_id, status) VALUES ('j1', 1, 'applied')")
        conn.commit()
    conn.close()


def test_init_db_migrates_legacy_db(tmp_path):
    import sqlite3
    from pipeline.db import init_db
    path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE jobs (
            id TEXT NOT NULL, company_id INTEGER NOT NULL, title TEXT NOT NULL,
            url TEXT, location TEXT, description TEXT, first_seen_at TEXT NOT NULL,
            filter_status TEXT NOT NULL DEFAULT 'new', llm_score REAL, llm_reason TEXT,
            kw_reason TEXT, PRIMARY KEY (id, company_id)
        );
        CREATE TABLE applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            company_id INTEGER NOT NULL, applied_at TEXT, status TEXT
        );
        """
    )
    legacy.commit()
    legacy.close()

    conn = init_db(path)
    job_cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"job_state", "last_seen_at", "closed_at"} <= job_cols
    app_cols = {r["name"] for r in conn.execute("PRAGMA table_info(applications)")}
    assert "updated_at" in app_cols
    conn.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db.py::test_init_db_has_lifecycle_columns tests/test_db.py::test_applications_reject_duplicate_pair tests/test_db.py::test_init_db_migrates_legacy_db -v`
Expected: FAIL — columns/constraint do not exist yet.

- [ ] **Step 3: Update `db/schema.sql`**

Replace the `jobs` and `applications` `CREATE TABLE` statements so they read exactly:

```sql
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
    kw_reason      TEXT,
    job_state      TEXT    NOT NULL DEFAULT 'open',
    last_seen_at   TEXT,
    closed_at      TEXT,
    PRIMARY KEY (id, company_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    NOT NULL,
    company_id  INTEGER NOT NULL,
    applied_at  TEXT,
    status      TEXT,
    updated_at  TEXT,
    UNIQUE (job_id, company_id)
);
```

Leave the `companies` table unchanged.

- [ ] **Step 4: Add migration to `pipeline/db.py`**

Add these helpers (place them just after the imports, before `init_db`):

```python
def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate(conn: sqlite3.Connection) -> None:
    job_cols = _column_names(conn, "jobs")
    if "job_state" not in job_cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN job_state TEXT NOT NULL DEFAULT 'open'")
    if "last_seen_at" not in job_cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN last_seen_at TEXT")
    if "closed_at" not in job_cols:
        conn.execute("ALTER TABLE jobs ADD COLUMN closed_at TEXT")
    app_cols = _column_names(conn, "applications")
    if "updated_at" not in app_cols:
        conn.execute("ALTER TABLE applications ADD COLUMN updated_at TEXT")
    # A legacy applications table lacks the inline UNIQUE constraint; a unique
    # index gives the same guarantee and can be added by migration.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_job_company "
        "ON applications (job_id, company_id)"
    )
    conn.commit()
```

Then change `init_db` so the migration runs after the schema is applied. The body becomes:

```python
def init_db(db_path: str = "auto_apply.db") -> sqlite3.Connection:
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema)
    conn.commit()
    _migrate(conn)
    return conn
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db.py -v`
Expected: PASS (all db tests, including the three new ones).

- [ ] **Step 6: Commit**

```bash
git add db/schema.sql pipeline/db.py tests/test_db.py
git commit -m "feat: add job lifecycle + application columns with in-place migration"
```

---

### Task 2: Reconciliation DB layer

**Files:**
- Modify: `pipeline/db.py` (add `get_open_job_ids`, `reconcile_job_states`)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: the `jobs` columns from Task 1; existing `upsert_jobs(conn, jobs)`.
- Produces:
  - `get_open_job_ids(conn, company_id: int) -> set[str]`
  - `reconcile_job_states(conn, company_id: int, current_ids: set[str]) -> None` — marks present jobs `open` (refresh `last_seen_at`, clear `closed_at`), and previously-`open` jobs absent from `current_ids` as `closed` (set `closed_at`). Assumes present jobs already exist in `jobs` (caller upserts first).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def _insert_job(conn, job_id, company_id, state="open"):
    conn.execute(
        "INSERT INTO jobs (id, company_id, title, first_seen_at, job_state) "
        "VALUES (?, ?, 'T', '2026-01-01', ?)",
        (job_id, company_id, state),
    )
    conn.commit()


def test_reconcile_closes_absent_job(db_conn):
    from pipeline.db import reconcile_job_states
    _insert_job(db_conn, "gone", 1)
    _insert_job(db_conn, "here", 1)
    reconcile_job_states(db_conn, 1, {"here"})
    rows = {r["id"]: r for r in db_conn.execute(
        "SELECT id, job_state, closed_at, last_seen_at FROM jobs WHERE company_id = 1")}
    assert rows["gone"]["job_state"] == "closed"
    assert rows["gone"]["closed_at"] is not None
    assert rows["here"]["job_state"] == "open"
    assert rows["here"]["last_seen_at"] is not None


def test_reconcile_reopens_returning_job(db_conn):
    from pipeline.db import reconcile_job_states
    _insert_job(db_conn, "back", 1, state="closed")
    db_conn.execute("UPDATE jobs SET closed_at='2026-01-02' WHERE id='back'")
    db_conn.commit()
    reconcile_job_states(db_conn, 1, {"back"})
    row = db_conn.execute("SELECT job_state, closed_at FROM jobs WHERE id='back'").fetchone()
    assert row["job_state"] == "open"
    assert row["closed_at"] is None


def test_reconcile_empty_current_closes_all_open(db_conn):
    from pipeline.db import reconcile_job_states
    _insert_job(db_conn, "a", 1)
    _insert_job(db_conn, "b", 1)
    reconcile_job_states(db_conn, 1, set())
    states = {r["id"]: r["job_state"] for r in db_conn.execute(
        "SELECT id, job_state FROM jobs WHERE company_id = 1")}
    assert states == {"a": "closed", "b": "closed"}


def test_reconcile_scoped_to_company(db_conn):
    from pipeline.db import reconcile_job_states
    _insert_job(db_conn, "x", 1)
    _insert_job(db_conn, "x", 2)
    reconcile_job_states(db_conn, 1, set())
    c1 = db_conn.execute("SELECT job_state FROM jobs WHERE id='x' AND company_id=1").fetchone()
    c2 = db_conn.execute("SELECT job_state FROM jobs WHERE id='x' AND company_id=2").fetchone()
    assert c1["job_state"] == "closed"
    assert c2["job_state"] == "open"


def test_get_open_job_ids(db_conn):
    from pipeline.db import get_open_job_ids
    _insert_job(db_conn, "o", 1, state="open")
    _insert_job(db_conn, "c", 1, state="closed")
    assert get_open_job_ids(db_conn, 1) == {"o"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db.py -k "reconcile or get_open_job_ids" -v`
Expected: FAIL — `ImportError` / functions not defined.

- [ ] **Step 3: Implement the functions**

Add to `pipeline/db.py`:

```python
def get_open_job_ids(conn: sqlite3.Connection, company_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT id FROM jobs WHERE company_id = ? AND job_state = 'open'",
        (company_id,),
    ).fetchall()
    return {row["id"] for row in rows}


def reconcile_job_states(
    conn: sqlite3.Connection, company_id: int, current_ids: set[str]
) -> None:
    now = datetime.now().isoformat()
    if current_ids:
        conn.executemany(
            "UPDATE jobs SET job_state='open', last_seen_at=?, closed_at=NULL "
            "WHERE id=? AND company_id=?",
            [(now, jid, company_id) for jid in current_ids],
        )
    absent = get_open_job_ids(conn, company_id) - set(current_ids)
    if absent:
        conn.executemany(
            "UPDATE jobs SET job_state='closed', closed_at=? WHERE id=? AND company_id=?",
            [(now, jid, company_id) for jid in absent],
        )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/db.py tests/test_db.py
git commit -m "feat: add job-state reconciliation helpers"
```

---

### Task 3: `poll_company` returns `PollResult` + reconciliation wiring

**Files:**
- Modify: `pipeline/discovery/poller.py` (add `PollResult`, rewrite `poll_company`)
- Modify: `pipeline/runner.py` (consume `PollResult`)
- Test: `tests/test_poller.py` (update existing, add new), `tests/test_runner.py` (update existing)

**Interfaces:**
- Consumes: `reconcile_job_states` (Task 2); existing `get_seen_job_ids`, `upsert_jobs`.
- Produces: `PollResult(success: bool, current_ids: set[str], new_jobs: list[Job])` (dataclass in `pipeline/discovery/poller.py`); `poll_company(company, conn) -> PollResult`.

- [ ] **Step 1: Update existing poller tests + add new ones**

In `tests/test_poller.py`, update the imports line to:

```python
from pipeline.discovery.poller import poll_company, PollResult
```

Change the assertions in the existing tests to use the new return type:

- In `test_poll_returns_only_new_jobs`, replace the `with`-block result handling and assertions with:

```python
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", return_value=raw):
        result = poll_company(company, db_conn)
    assert result.success is True
    assert len(result.new_jobs) == 1
    assert result.new_jobs[0].id == "new-2"
    assert result.new_jobs[0].company_id == company.id
```

- In `test_poll_returns_empty_on_http_error`, replace the last two lines with:

```python
        result = poll_company(company, db_conn)
    assert result.success is False
    assert result.new_jobs == []
```

- In `test_poll_returns_empty_on_malformed_token`, replace the last two lines with:

```python
        result = poll_company(company, db_conn)
    assert result.success is False
    assert result.new_jobs == []
```

- In `test_poll_returns_empty_on_playwright_error`, replace the last two lines with:

```python
    result = poller.poll_company(company, db_conn)
    assert result.success is False
    assert result.new_jobs == []
```

(`test_poll_persists_all_jobs_not_just_new` does not use the return value and needs no change.)

Then add these new tests to `tests/test_poller.py`:

```python
def test_poll_marks_disappeared_job_closed(db_conn):
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(db_conn, [Job(id="gone-1", company_id=company.id, title="Gone", url=None, location=None, description=None)])
    raw = [RawJob(id="present-2", title="Present", url=None, location=None, description=None)]
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", return_value=raw):
        result = poll_company(company, db_conn)
    assert result.success is True
    gone = db_conn.execute("SELECT job_state FROM jobs WHERE id='gone-1' AND company_id=?", (company.id,)).fetchone()
    present = db_conn.execute("SELECT job_state FROM jobs WHERE id='present-2' AND company_id=?", (company.id,)).fetchone()
    assert gone["job_state"] == "closed"
    assert present["job_state"] == "open"


def test_poll_failure_does_not_close_jobs(db_conn):
    import httpx
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(db_conn, [Job(id="keep-1", company_id=company.id, title="Keep", url=None, location=None, description=None)])
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", side_effect=httpx.HTTPError("down")):
        result = poll_company(company, db_conn)
    assert result.success is False
    row = db_conn.execute("SELECT job_state FROM jobs WHERE id='keep-1' AND company_id=?", (company.id,)).fetchone()
    assert row["job_state"] == "open"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_poller.py -v`
Expected: FAIL — `ImportError: cannot import name 'PollResult'` (and the new assertions).

- [ ] **Step 3: Rewrite `poll_company` in `pipeline/discovery/poller.py`**

Update the imports at the top of the file to add `dataclass`/`field` and `reconcile_job_states`:

```python
import sqlite3
from dataclasses import dataclass, field
import httpx
from playwright.sync_api import Error as PlaywrightError
from models.company import Company
from models.job import Job, RawJob
from pipeline.db import get_seen_job_ids, upsert_jobs, reconcile_job_states
from pipeline.discovery.clients import greenhouse, lever, ashby, workday
```

Add the result type just below `_CLIENT_MAP`:

```python
@dataclass
class PollResult:
    success: bool
    current_ids: set[str] = field(default_factory=set)
    new_jobs: list[Job] = field(default_factory=list)
```

Replace `poll_company` with:

```python
def poll_company(company: Company, conn: sqlite3.Connection) -> PollResult:
    try:
        raw_jobs = fetch_jobs_for_company(company)
    except (httpx.HTTPError, KeyError, ValueError, PlaywrightError) as e:
        print(f"Failed to fetch jobs for {company.name}: {e}")
        return PollResult(success=False)
    seen_ids = get_seen_job_ids(conn, company.id)
    all_jobs = [
        Job(id=r.id, company_id=company.id, title=r.title, url=r.url, location=r.location, description=r.description)
        for r in raw_jobs
    ]
    upsert_jobs(conn, all_jobs)
    current_ids = {j.id for j in all_jobs}
    reconcile_job_states(conn, company.id, current_ids)
    new_jobs = [j for j in all_jobs if j.id not in seen_ids]
    return PollResult(success=True, current_ids=current_ids, new_jobs=new_jobs)
```

- [ ] **Step 4: Update `pipeline/runner.py` to consume `PollResult`**

In `run_pipeline`, change the loop body from:

```python
    for company in active:
        new_jobs = poll_company(company, conn)
        matched, kw_filtered, llm_filtered = filter_jobs(new_jobs, config, conn)
```

to:

```python
    for company in active:
        poll = poll_company(company, conn)
        matched, kw_filtered, llm_filtered = filter_jobs(poll.new_jobs, config, conn)
```

- [ ] **Step 5: Update `tests/test_runner.py` for the new return type**

Update the import line to add `PollResult`:

```python
from pipeline.discovery.poller import PollResult
```

In `test_run_pipeline_returns_digest`, change the `poll_company` patch to:

```python
    with patch("pipeline.runner.poll_company", return_value=PollResult(success=True, current_ids={"j1"}, new_jobs=[new_job])), \
         patch("pipeline.runner.filter_jobs", return_value=([new_job], [], [])):
```

In `test_run_pipeline_includes_unsupported_companies`, change the `poll_company` patch to:

```python
    with patch("pipeline.runner.poll_company", return_value=PollResult(success=True)), \
         patch("pipeline.runner.filter_jobs", return_value=([], [], [])):
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_poller.py tests/test_runner.py -v`
Expected: PASS (all poller and runner tests).

- [ ] **Step 7: Commit**

```bash
git add pipeline/discovery/poller.py pipeline/runner.py tests/test_poller.py tests/test_runner.py
git commit -m "feat: poll_company returns PollResult and reconciles job states on success"
```

---

### Task 4: Configurable poll interval + interval scheduler

**Files:**
- Modify: `pipeline/config.py` (add `ScheduleConfig`, add `schedule` to `Config`, parse it)
- Modify: `config.yaml` (add `schedule` block)
- Modify: `pipeline/scheduler.py` (interval trigger)
- Test: `tests/test_config.py`, `tests/test_scheduler.py` (new)

**Interfaces:**
- Consumes: existing `Config`, `load_config`, `start_scheduler(config, db_path)`.
- Produces: `ScheduleConfig(poll_interval_minutes: int = 60)`; `Config.schedule: ScheduleConfig` (defaulted); scheduler runs on an `interval` trigger of `config.schedule.poll_interval_minutes`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_config_default_poll_interval(config_file):
    config = load_config(config_file)
    assert config.schedule.poll_interval_minutes == 60


def test_config_reads_poll_interval(tmp_path):
    import yaml
    content = {
        "user": {"desired_role": "SE", "desired_level": "Senior", "resume_path": "./r.pdf"},
        "filter": {"include_patterns": [], "exclude_patterns": [], "level_patterns": [], "llm_score_threshold": 7.0},
        "llm": {"model": "llama3.2", "base_url": "http://localhost:11434"},
        "notifications": {"type": "terminal"},
        "schedule": {"poll_interval_minutes": 30},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(content))
    config = load_config(str(p))
    assert config.schedule.poll_interval_minutes == 30
```

Create `tests/test_scheduler.py`:

```python
from pipeline.config import Config, UserConfig, FilterConfig, LLMConfig, NotificationsConfig, ScheduleConfig


def _config(interval):
    return Config(
        user=UserConfig(desired_role="SE", desired_level="Senior", resume_path="./r.pdf"),
        filter=FilterConfig(include_patterns=[], exclude_patterns=[], level_patterns=[], llm_score_threshold=7.0),
        llm=LLMConfig(model="llama3.2"),
        notifications=NotificationsConfig(type="terminal"),
        schedule=ScheduleConfig(poll_interval_minutes=interval),
    )


def test_scheduler_uses_interval_trigger(monkeypatch):
    from pipeline import scheduler as sched_mod
    captured = {}

    class FakeScheduler:
        def add_job(self, func, trigger, **kwargs):
            captured["trigger"] = trigger
            captured["kwargs"] = kwargs

        def start(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(sched_mod, "BlockingScheduler", lambda: FakeScheduler())
    try:
        sched_mod.start_scheduler(_config(45), ":memory:")
    except KeyboardInterrupt:
        pass
    assert captured["trigger"] == "interval"
    assert captured["kwargs"]["minutes"] == 45
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_config.py tests/test_scheduler.py -v`
Expected: FAIL — `ScheduleConfig` does not exist / `Config` has no `schedule`.

- [ ] **Step 3: Add `ScheduleConfig` to `pipeline/config.py`**

Add the dataclass (place it after `NotificationsConfig`):

```python
@dataclass
class ScheduleConfig:
    poll_interval_minutes: int = 60
```

Add a defaulted `schedule` field to `Config` (must come after the existing non-defaulted fields):

```python
@dataclass
class Config:
    user: UserConfig
    filter: FilterConfig
    llm: LLMConfig
    notifications: NotificationsConfig
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
```

In `load_config`, build the schedule from an optional `schedule` block:

```python
    return Config(
        user=UserConfig(**data["user"]),
        filter=FilterConfig(**data["filter"]),
        llm=LLMConfig(**data["llm"]),
        notifications=NotificationsConfig(**data["notifications"]),
        schedule=ScheduleConfig(**data.get("schedule", {})),
    )
```

(`field` is already imported at the top of `pipeline/config.py`.)

- [ ] **Step 4: Add the `schedule` block to `config.yaml`**

Append to `config.yaml`:

```yaml
schedule:
  poll_interval_minutes: 60
```

- [ ] **Step 5: Switch `pipeline/scheduler.py` to an interval trigger**

Replace the `add_job` / print lines in `start_scheduler`. The function becomes:

```python
def start_scheduler(config: Config, db_path: str = "auto_apply.db") -> None:
    scheduler = BlockingScheduler()

    def poll_job():
        conn = init_db(db_path)
        try:
            result = run_pipeline(config, conn)
            print_digest(result)
        finally:
            conn.close()

    minutes = config.schedule.poll_interval_minutes
    scheduler.add_job(poll_job, "interval", minutes=minutes)
    print(f"Scheduler started. Polling every {minutes} min. Press Ctrl+C to stop.")
    scheduler.start()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_config.py tests/test_scheduler.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pipeline/config.py config.yaml pipeline/scheduler.py tests/test_config.py tests/test_scheduler.py
git commit -m "feat: configurable poll interval with APScheduler interval trigger"
```

---

### Task 5: Application DB helpers

**Files:**
- Modify: `pipeline/db.py` (add `job_exists`, `create_application`, `update_application_status`, `get_applications`)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `applications` columns from Task 1; existing `upsert_company`, `upsert_jobs`.
- Produces:
  - `job_exists(conn, job_id: str, company_id: int) -> bool`
  - `create_application(conn, job_id: str, company_id: int) -> None` (status `applied`; raises `sqlite3.IntegrityError` on duplicate pair)
  - `update_application_status(conn, job_id: str, company_id: int, status: str) -> int` (returns affected row count)
  - `get_applications(conn, status: str | None = None) -> list[dict]` (joined to job title/`job_state` and company name)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def _company_and_job(conn, job_id="j1", state="open"):
    from pipeline.db import upsert_company, upsert_jobs
    from models.company import Company
    from models.job import Job
    c = upsert_company(conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    conn.execute(
        "INSERT INTO jobs (id, company_id, title, first_seen_at, job_state) VALUES (?, ?, 'Eng', '2026-01-01', ?)",
        (job_id, c.id, state),
    )
    conn.commit()
    return c.id


def test_create_application_sets_applied(db_conn):
    from pipeline.db import create_application
    cid = _company_and_job(db_conn)
    create_application(db_conn, "j1", cid)
    row = db_conn.execute("SELECT status, applied_at, updated_at FROM applications WHERE job_id='j1'").fetchone()
    assert row["status"] == "applied"
    assert row["applied_at"] is not None
    assert row["updated_at"] is not None


def test_create_application_duplicate_raises(db_conn):
    import sqlite3
    import pytest
    from pipeline.db import create_application
    cid = _company_and_job(db_conn)
    create_application(db_conn, "j1", cid)
    with pytest.raises(sqlite3.IntegrityError):
        create_application(db_conn, "j1", cid)


def test_update_application_status(db_conn):
    from pipeline.db import create_application, update_application_status
    cid = _company_and_job(db_conn)
    create_application(db_conn, "j1", cid)
    affected = update_application_status(db_conn, "j1", cid, "interviewing")
    assert affected == 1
    row = db_conn.execute("SELECT status FROM applications WHERE job_id='j1'").fetchone()
    assert row["status"] == "interviewing"


def test_update_application_status_no_row(db_conn):
    from pipeline.db import update_application_status
    cid = _company_and_job(db_conn)
    assert update_application_status(db_conn, "nope", cid, "offer") == 0


def test_get_applications_joins_and_filters(db_conn):
    from pipeline.db import create_application, update_application_status, get_applications
    cid = _company_and_job(db_conn, job_id="j1", state="closed")
    create_application(db_conn, "j1", cid)
    rows = get_applications(db_conn)
    assert len(rows) == 1
    assert rows[0]["title"] == "Eng"
    assert rows[0]["company_name"] == "Stripe"
    assert rows[0]["job_state"] == "closed"
    assert rows[0]["status"] == "applied"
    update_application_status(db_conn, "j1", cid, "offer")
    assert get_applications(db_conn, status="applied") == []
    assert len(get_applications(db_conn, status="offer")) == 1


def test_job_exists(db_conn):
    from pipeline.db import job_exists
    cid = _company_and_job(db_conn)
    assert job_exists(db_conn, "j1", cid) is True
    assert job_exists(db_conn, "missing", cid) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db.py -k "application or job_exists" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement the functions**

Add to `pipeline/db.py`:

```python
def job_exists(conn: sqlite3.Connection, job_id: str, company_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE id=? AND company_id=?", (job_id, company_id)
    ).fetchone()
    return row is not None


def create_application(conn: sqlite3.Connection, job_id: str, company_id: int) -> None:
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO applications (job_id, company_id, applied_at, status, updated_at) "
        "VALUES (?, ?, ?, 'applied', ?)",
        (job_id, company_id, now, now),
    )
    conn.commit()


def update_application_status(
    conn: sqlite3.Connection, job_id: str, company_id: int, status: str
) -> int:
    now = datetime.now().isoformat()
    cur = conn.execute(
        "UPDATE applications SET status=?, updated_at=? WHERE job_id=? AND company_id=?",
        (status, now, job_id, company_id),
    )
    conn.commit()
    return cur.rowcount


def get_applications(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    query = (
        "SELECT a.job_id, a.company_id, a.applied_at, a.status, a.updated_at, "
        "       j.title, j.job_state, c.name AS company_name "
        "FROM applications a "
        "JOIN jobs j ON a.job_id = j.id AND a.company_id = j.company_id "
        "JOIN companies c ON a.company_id = c.id"
    )
    params: tuple = ()
    if status:
        query += " WHERE a.status = ?"
        params = (status,)
    query += " ORDER BY a.updated_at DESC"
    return [dict(row) for row in conn.execute(query, params).fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pipeline/db.py tests/test_db.py
git commit -m "feat: add application-tracking DB helpers"
```

---

### Task 6: Application-status CLI commands

**Files:**
- Modify: `main.py` (imports, `VALID_STATUSES`, `apply`, `set-status`, `list-applications` commands)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `create_application`, `update_application_status`, `get_applications`, `job_exists` (Task 5); existing `init_db`, `DB_PATH`, `cli`.
- Produces: `apply <job_id> <company_id>`, `set-status <job_id> <company_id> <status>`, `list-applications [--status]` CLI commands.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py` (the top already imports `patch`; add `from pipeline.db import init_db, upsert_company, upsert_jobs, get_applications`, `from models.company import Company`, and `from models.job import Job` at the top of the file):

```python
def _seed_db(path):
    conn = init_db(path)
    c = upsert_company(conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(conn, [Job(id="j1", company_id=c.id, title="Eng", url=None, location=None, description=None)])
    conn.close()
    return c


def test_apply_creates_application(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    assert result.exit_code == 0
    assert "applied" in result.output.lower()
    conn = init_db(path)
    assert len(get_applications(conn)) == 1
    conn.close()


def test_apply_unknown_job_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["apply", "missing", str(company.id)])
    assert result.exit_code != 0
    assert "No job" in result.output


def test_apply_duplicate_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    result = CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    assert result.exit_code != 0
    assert "Already tracking" in result.output


def test_set_status_updates(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    result = CliRunner().invoke(cli, ["set-status", "j1", str(company.id), "interviewing"])
    assert result.exit_code == 0
    assert "interviewing" in result.output


def test_set_status_invalid_status_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["set-status", "j1", str(company.id), "bogus"])
    assert result.exit_code != 0
    assert "Invalid status" in result.output


def test_set_status_without_application_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["set-status", "j1", str(company.id), "offer"])
    assert result.exit_code != 0
    assert "No tracked application" in result.output


def test_list_applications_marks_closed(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    conn = init_db(path)
    c = upsert_company(conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    conn.execute("INSERT INTO jobs (id, company_id, title, first_seen_at, job_state) VALUES ('j1', ?, 'Eng', '2026-01-01', 'closed')", (c.id,))
    conn.commit()
    conn.close()
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["apply", "j1", str(c.id)])
    result = CliRunner().invoke(cli, ["list-applications"])
    assert result.exit_code == 0
    assert "CLOSED" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cli.py -k "apply or set_status or list_applications" -v`
Expected: FAIL — no such commands.

- [ ] **Step 3: Implement the commands in `main.py`**

Add `import sqlite3` at the top of `main.py`, and extend the `pipeline.db` import to include the new helpers:

```python
from pipeline.db import (
    init_db, upsert_company, get_all_companies, get_matched_jobs,
    create_application, update_application_status, get_applications, job_exists,
)
```

Add the status constant near `DB_PATH`:

```python
VALID_STATUSES = ("applied", "interviewing", "offer", "rejected")
```

Add the three commands (place them after `show_matches`, before `if __name__ == "__main__":`):

```python
@cli.command()
@click.argument("job_id")
@click.argument("company_id", type=int)
def apply(job_id, company_id):
    """Mark yourself as having applied to a job."""
    conn = init_db(DB_PATH)
    try:
        if not job_exists(conn, job_id, company_id):
            raise click.UsageError(f"No job {job_id} for company {company_id}.")
        state_row = conn.execute(
            "SELECT job_state FROM jobs WHERE id=? AND company_id=?", (job_id, company_id)
        ).fetchone()
        try:
            create_application(conn, job_id, company_id)
        except sqlite3.IntegrityError:
            raise click.UsageError(
                f"Already tracking an application for {job_id}. Use set-status to update it."
            )
        note = " (job is closed)" if state_row["job_state"] == "closed" else ""
        click.echo(f"✓ Marked applied: {job_id}{note}")
    finally:
        conn.close()


@cli.command(name="set-status")
@click.argument("job_id")
@click.argument("company_id", type=int)
@click.argument("status")
def set_status(job_id, company_id, status):
    """Update the status of a tracked application."""
    if status not in VALID_STATUSES:
        raise click.UsageError(
            f"Invalid status '{status}'. Choose from: {', '.join(VALID_STATUSES)}"
        )
    conn = init_db(DB_PATH)
    try:
        updated = update_application_status(conn, job_id, company_id, status)
        if updated == 0:
            raise click.UsageError(
                f"No tracked application for {job_id}. Use apply first."
            )
        click.echo(f"✓ {job_id} → {status}")
    finally:
        conn.close()


@cli.command(name="list-applications")
@click.option("--status", default=None, help="Filter by status")
def list_applications(status):
    """List tracked job applications."""
    conn = init_db(DB_PATH)
    try:
        apps = get_applications(conn, status)
        if not apps:
            click.echo("No tracked applications.")
            return
        for a in apps:
            closed = " [CLOSED]" if a["job_state"] == "closed" else ""
            click.echo(f"  [{a['status']}] {a['company_name']} — {a['title']}{closed}")
    finally:
        conn.close()
```

- [ ] **Step 4: Run the CLI tests to verify they pass**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS (all CLI tests).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest`
Expected: all pass, integration tests deselected.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: add apply / set-status / list-applications CLI commands"
```

---

## Notes

- **No new integration tests.** Reconciliation is exercised through the mockable `fetch_jobs_for_company` seam; no live network needed.
- **Migration vs. fixture split:** the lifecycle columns and the applications uniqueness live in `db/schema.sql` (so the `db_conn` fixture, which loads the schema directly, gets them) *and* in `_migrate` (so pre-existing on-disk DBs upgrade). The unique index in `_migrate` is what upgrades a legacy `applications` table that predates the inline `UNIQUE` constraint.
- **`poll_company` contract change** (Task 3) is the load-bearing task: it changes the return type and updates every caller and test in the same commit to keep the suite green.
