# Workday Hardening & Seed-List Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Workday polling failures non-fatal, and add a seed-list-driven CLI command to bulk-register companies known to use Workday.

**Architecture:** Add Playwright's `Error` to `poll_company`'s caught exceptions so a bad Workday board is logged and skipped, not fatal. Add a new `pipeline/discovery/seed.py` module (`load_seed_companies`, `resolve_workday_company`, `register_seed_companies`) plus a `companies_seed.yaml` file and an `add-companies` CLI command. Bulk registration probes each company **Workday-only** (via slug variants) rather than running the full multi-ATS sweep.

**Tech Stack:** Python 3.14, Click, Playwright (sync + async), PyYAML, pytest (+ pytest-asyncio, `asyncio_mode = auto`), SQLite.

## Global Constraints

- Company probing across the seed list runs **sequentially**, not concurrently: each `probe_workday` launches its own Chromium browser, so a `gather` over 15-20 names would launch that many browsers at once. `probe_workday` already parallelizes its 4 version-probes inside one browser.
- Seed registration is **Workday-only** — call `probe_workday` via slug variants, never the full `detect_ats` sweep.
- Do not abort a batch on a single miss; collect and report registered / skipped / missed.
- Reuse existing DB helpers (`get_all_companies`, `upsert_company`) — do not add a new per-name lookup.
- Tests default to `-m 'not integration'` (see `pyproject.toml`); integration tests need `playwright install chromium` + network.
- Run tests with `python3 -m pytest` (no bare `python` on this machine).

---

### Task 1: Harden `poll_company` against Playwright errors

**Files:**
- Modify: `pipeline/discovery/poller.py` (imports + `except` tuple in `poll_company`)
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: existing `poll_company(company, conn) -> list[Job]`, `pipeline.discovery.poller._CLIENT_MAP`.
- Produces: no signature change; `poll_company` now also survives `playwright.sync_api.Error`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_poller.py`:

```python
def test_poll_returns_empty_on_playwright_error(db_conn, monkeypatch):
    from playwright.sync_api import Error as PlaywrightError
    from pipeline.discovery import poller
    company = upsert_company(db_conn, Company(
        name="Workday", slug="workday.wd5/Workday", ats_type="workday",
        board_token="workday.wd5/Workday", status="active"))

    def boom(token):
        raise PlaywrightError("navigation timeout")

    monkeypatch.setitem(poller._CLIENT_MAP, "workday", boom)
    new_jobs = poller.poll_company(company, db_conn)
    assert new_jobs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_poller.py::test_poll_returns_empty_on_playwright_error -v`
Expected: FAIL — `PlaywrightError` propagates out of `poll_company` (uncaught).

- [ ] **Step 3: Add the import and extend the except tuple**

In `pipeline/discovery/poller.py`, add near the top imports:

```python
from playwright.sync_api import Error as PlaywrightError
```

Change the `except` line in `poll_company` from:

```python
    except (httpx.HTTPError, KeyError, ValueError) as e:
```

to:

```python
    except (httpx.HTTPError, KeyError, ValueError, PlaywrightError) as e:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_poller.py -v`
Expected: PASS (all poller tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/poller.py tests/test_poller.py
git commit -m "fix: skip Workday boards that raise Playwright errors instead of crashing the run"
```

---

### Task 2: Seed file + loader

**Files:**
- Create: `companies_seed.yaml`
- Create: `pipeline/discovery/seed.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Produces: `load_seed_companies(path: str) -> list[str]` — returns the `companies` list from a YAML file, or `[]` if the file is empty / missing the key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seed.py`:

```python
from pipeline.discovery import seed


def test_load_seed_companies_reads_list(tmp_path):
    f = tmp_path / "seed.yaml"
    f.write_text("companies:\n  - Foo\n  - Bar\n")
    assert seed.load_seed_companies(str(f)) == ["Foo", "Bar"]


def test_load_seed_companies_empty_file(tmp_path):
    f = tmp_path / "seed.yaml"
    f.write_text("")
    assert seed.load_seed_companies(str(f)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: pipeline.discovery.seed`.

- [ ] **Step 3: Create the module with the loader**

Create `pipeline/discovery/seed.py`:

```python
import yaml


def load_seed_companies(path: str) -> list[str]:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    return data.get("companies", [])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 5: Create the seed YAML file**

Create `companies_seed.yaml`:

```yaml
# Companies believed to use the Workday ATS.
# VERIFY each entry — ATS choice changes over time. Prune and extend freely.
# `add-companies` probes each name Workday-only; misses are reported, not fatal.
companies:
  - "Salesforce"
  - "Adobe"
  - "NVIDIA"
  - "Netflix"
  - "Airbnb"
  - "Workday"
  - "Target"
  - "Best Buy"
  - "Comcast"
  - "Mastercard"
  - "Visa"
  - "Nordstrom"
  - "CVS Health"
  - "Bank of America"
  - "Toyota"
  - "Unilever"
  - "Accenture"
  - "Sanofi"
```

- [ ] **Step 6: Commit**

```bash
git add pipeline/discovery/seed.py tests/test_seed.py companies_seed.yaml
git commit -m "feat: add Workday seed-list loader and starter companies_seed.yaml"
```

---

### Task 3: Workday-only resolver

**Files:**
- Modify: `pipeline/discovery/seed.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `generate_slug_variants(name: str) -> list[str]` from `pipeline.discovery.detector`; `probe_workday(slug: str) -> tuple[str, str] | None` from `pipeline.discovery.clients.workday`.
- Produces: `async def resolve_workday_company(name: str) -> tuple[str, str] | None` — returns the first `("workday", board_token)` hit across the name's slug variants, else `None`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seed.py`:

```python
from unittest.mock import patch, AsyncMock


async def test_resolve_workday_company_returns_first_hit():
    with patch("pipeline.discovery.seed.generate_slug_variants", return_value=["a", "b"]), \
         patch("pipeline.discovery.seed.probe_workday",
               new=AsyncMock(side_effect=[None, ("workday", "b.wd5/Careers")])):
        result = await seed.resolve_workday_company("Foo")
    assert result == ("workday", "b.wd5/Careers")


async def test_resolve_workday_company_returns_none_when_no_hit():
    with patch("pipeline.discovery.seed.generate_slug_variants", return_value=["a", "b"]), \
         patch("pipeline.discovery.seed.probe_workday", new=AsyncMock(return_value=None)):
        result = await seed.resolve_workday_company("Nope")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_seed.py::test_resolve_workday_company_returns_first_hit -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'resolve_workday_company'`.

- [ ] **Step 3: Implement the resolver**

In `pipeline/discovery/seed.py`, add imports at the top (below `import yaml`):

```python
from pipeline.discovery.detector import generate_slug_variants
from pipeline.discovery.clients.workday import probe_workday
```

Add the function:

```python
async def resolve_workday_company(name: str) -> tuple[str, str] | None:
    for slug in generate_slug_variants(name):
        result = await probe_workday(slug)
        if result is not None:
            return result
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_seed.py -v`
Expected: PASS (all four seed tests so far).

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/seed.py tests/test_seed.py
git commit -m "feat: add Workday-only resolver over company slug variants"
```

---

### Task 4: Bulk registration orchestration

**Files:**
- Modify: `pipeline/discovery/seed.py`
- Test: `tests/test_seed.py`

**Interfaces:**
- Consumes: `get_all_companies(conn)` and `upsert_company(conn, company)` from `pipeline.db`; `Company` from `models.company`; `resolve_workday_company` from Task 3.
- Produces: `async def register_seed_companies(conn, names: list[str]) -> dict[str, list[str]]` — returns `{"registered": [...], "skipped": [...], "missed": [...]}`. Skips names already in the DB; registers hits as `ats_type="workday"` with `slug`/`board_token` set to the resolved token; collects misses. Probes sequentially in list order.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seed.py`:

```python
from pipeline.db import upsert_company, get_all_companies
from models.company import Company


async def test_register_skips_existing(db_conn):
    upsert_company(db_conn, Company(
        name="Foo", slug="foo", ats_type="workday",
        board_token="foo.wd5/Careers", status="active"))
    with patch("pipeline.discovery.seed.resolve_workday_company",
               new=AsyncMock()) as mock_resolve:
        result = await seed.register_seed_companies(db_conn, ["Foo"])
    mock_resolve.assert_not_called()
    assert result["skipped"] == ["Foo"]
    assert result["registered"] == []
    assert result["missed"] == []


async def test_register_records_hits_and_misses(db_conn):
    async def fake_resolve(name):
        return ("workday", "bar.wd5/Careers") if name == "Bar" else None

    with patch("pipeline.discovery.seed.resolve_workday_company", new=fake_resolve):
        result = await seed.register_seed_companies(db_conn, ["Bar", "Baz"])
    assert result["registered"] == ["Bar"]
    assert result["missed"] == ["Baz"]
    names = {c.name for c in get_all_companies(db_conn)}
    assert "Bar" in names
    assert "Baz" not in names
    bar = next(c for c in get_all_companies(db_conn) if c.name == "Bar")
    assert bar.ats_type == "workday"
    assert bar.board_token == "bar.wd5/Careers"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_seed.py::test_register_skips_existing -v`
Expected: FAIL — `AttributeError: ... 'register_seed_companies'`.

- [ ] **Step 3: Implement the orchestration**

In `pipeline/discovery/seed.py`, add imports at the top:

```python
from pipeline.db import get_all_companies, upsert_company
from models.company import Company
```

Add the function:

```python
async def register_seed_companies(conn, names: list[str]) -> dict[str, list[str]]:
    existing = {c.name for c in get_all_companies(conn)}
    registered: list[str] = []
    skipped: list[str] = []
    missed: list[str] = []
    for name in names:
        if name in existing:
            skipped.append(name)
            continue
        result = await resolve_workday_company(name)
        if result is None:
            missed.append(name)
            continue
        _, board_token = result
        upsert_company(conn, Company(
            name=name, slug=board_token, ats_type="workday",
            board_token=board_token, status="active"))
        registered.append(name)
    return {"registered": registered, "skipped": skipped, "missed": missed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_seed.py -v`
Expected: PASS (all six seed tests).

- [ ] **Step 5: Commit**

```bash
git add pipeline/discovery/seed.py tests/test_seed.py
git commit -m "feat: add register_seed_companies bulk Workday registration"
```

---

### Task 5: `add-companies` CLI command

**Files:**
- Modify: `main.py` (import + new command)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `load_seed_companies`, `register_seed_companies` from `pipeline.discovery.seed`; existing `init_db`, `DB_PATH`, `cli` group in `main.py`.
- Produces: `add-companies --seed-file <path>` CLI command (default `companies_seed.yaml`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py` (extend the top import to `from unittest.mock import patch, AsyncMock`):

```python
def test_add_companies_reports_results(db_conn):
    fake = {"registered": ["Foo"], "skipped": ["Bar"], "missed": ["Baz"]}
    with patch("main.init_db", return_value=db_conn), \
         patch("main.load_seed_companies", return_value=["Foo", "Bar", "Baz"]), \
         patch("main.register_seed_companies", new=AsyncMock(return_value=fake)):
        runner = CliRunner()
        result = runner.invoke(cli, ["add-companies", "--seed-file", "x.yaml"])
    assert result.exit_code == 0
    assert "Foo" in result.output
    assert "Bar" in result.output
    assert "Baz" in result.output


def test_add_companies_empty_seed(db_conn):
    with patch("main.init_db", return_value=db_conn), \
         patch("main.load_seed_companies", return_value=[]):
        runner = CliRunner()
        result = runner.invoke(cli, ["add-companies", "--seed-file", "x.yaml"])
    assert result.exit_code == 0
    assert "No companies" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py::test_add_companies_reports_results -v`
Expected: FAIL — no such command `add-companies` (nonzero exit / usage error).

- [ ] **Step 3: Implement the command**

In `main.py`, add to the imports:

```python
from pipeline.discovery.seed import load_seed_companies, register_seed_companies
```

Add the command (place after `add_company`, before `list_companies`):

```python
@cli.command()
@click.option("--seed-file", default="companies_seed.yaml", show_default=True,
              help="YAML file with a 'companies' list")
def add_companies(seed_file):
    """Bulk-register companies from a seed list as Workday boards."""
    names = load_seed_companies(seed_file)
    if not names:
        click.echo(f"No companies found in {seed_file}.")
        return
    conn = init_db(DB_PATH)
    try:
        result = asyncio.run(register_seed_companies(conn, names))
    finally:
        conn.close()
    for name in result["registered"]:
        click.echo(f"✓ {name}")
    for name in result["skipped"]:
        click.echo(f"– {name} (already registered)")
    for name in result["missed"]:
        click.echo(f"✗ {name} — not found on Workday")
    click.echo(
        f"\n{len(result['registered'])} added, "
        f"{len(result['skipped'])} skipped, "
        f"{len(result['missed'])} not found."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS (all CLI tests).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest`
Expected: all pass, integration tests deselected.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: add add-companies CLI to bulk-register Workday seed list"
```

---

### Task 6: End-to-end verification (integration, live network)

**Files:** none (verification only)

**Interfaces:** none.

- [ ] **Step 1: Ensure Chromium is installed for Playwright**

Run: `python3 -m playwright install chromium`
Expected: chromium present (downloads if missing).

- [ ] **Step 2: Run the Workday integration tests**

Run: `python3 -m pytest tests/test_workday.py -m integration -v`
Expected: `test_fetch_jobs_returns_jobs_from_real_board` and `test_probe_workday_finds_workday_inc` PASS (confirms real browser fetch + probe paths work).

- [ ] **Step 3: Smoke-test the bulk command against a tiny seed**

Create a scratch seed file with one known-good name and run the command against a throwaway DB:

```bash
printf 'companies:\n  - "Workday"\n' > /tmp/seed_smoke.yaml
python3 main.py add-companies --seed-file /tmp/seed_smoke.yaml
```

Expected: `✓ Workday` printed and a summary line. (Uses the real `auto_apply.db`; the entry is a genuine Workday board, safe to keep or remove afterward.)

- [ ] **Step 4: No commit** (verification only). Report results.

---

## Notes

- **Deviation from spec:** the design suggested concurrent probing via `asyncio.gather`. This plan probes sequentially because each `probe_workday` launches its own Chromium browser; a `gather` over the seed list would launch 15-20 browsers simultaneously. Per-company probing is already internally parallel across the 4 Workday version subdomains.
