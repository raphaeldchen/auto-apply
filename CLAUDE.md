# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable + dev deps)
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test file
pytest tests/test_runner.py

# Run a single test by name
pytest tests/test_filter.py::test_keyword_filter_match -v

# CLI entry point (from repo root)
python main.py add-company --name "Acme Corp"
python main.py run
python main.py run --schedule          # APScheduler daily loop
python main.py show-matches --days 14
```

The LLM scorer calls a local Ollama instance (`http://localhost:11434` by default). Tests that exercise `score_job` need Ollama running, or mock `httpx.post`.

## Architecture

### Data flow

```
add-company  →  detect_ats()  →  upsert_company()  →  companies table
run          →  run_pipeline()
                  └─ poll_company()         # fetch RawJobs from ATS API, upsert all, return only *new* ones
                       └─ filter_jobs()
                            ├─ keyword_filter()   → kw_filtered (skip LLM)
                            └─ score_job()        → matched / llm_filtered
```

### Key design decisions

**Two-stage filtering**: `keyword_filter` runs first as a cheap gate; only jobs that pass go to the LLM scorer. `filter/__init__.py` owns this sequencing.

**"New job" definition**: `get_seen_job_ids` returns jobs whose `filter_status != 'kw_filtered'`. This means keyword-rejected jobs are re-evaluated on every run (intentional — patterns may change), while LLM-scored jobs (matched or llm_filtered) are treated as seen and skipped.

**Composite PK on jobs**: `(id, company_id)` — the same ATS job ID can theoretically appear across companies. `upsert_jobs` uses `ON CONFLICT DO NOTHING` to preserve `first_seen_at`.

**ATS detection**: `detector.py` probes all slug variants × all ATS types concurrently via `asyncio.gather`. Clients expose a module-level `{ATS}_URL` constant used both for probing and fetching.

### Module map

| Path | Responsibility |
|------|---------------|
| `main.py` | Click CLI — `add-company`, `list-companies`, `run`, `show-matches` |
| `pipeline/config.py` | Typed dataclass config loaded from `config.yaml` |
| `pipeline/db.py` | All SQLite operations; schema loaded from `db/schema.sql` on `init_db()` |
| `pipeline/runner.py` | Orchestrates poll → filter loop per active company |
| `pipeline/discovery/detector.py` | Async ATS auto-detection by probing slug variants |
| `pipeline/discovery/poller.py` | Fetches raw jobs, deduplicates against DB, returns new `Job` objects |
| `pipeline/discovery/clients/` | One module per ATS (Greenhouse, Lever, Ashby) exposing `fetch_jobs(token)` |
| `pipeline/filter/keyword.py` | Regex-based include/exclude/level pattern matching |
| `pipeline/filter/llm_scorer.py` | Ollama `/api/chat` call returning `(score, reason)` |
| `pipeline/notifier.py` | Terminal digest printer |
| `pipeline/scheduler.py` | APScheduler wrapper for daily runs |
| `models/` | Plain dataclasses: `Company`, `Job`, `RawJob`, `DigestResult`, `CompanyDigest` |
| `db/schema.sql` | SQLite DDL for `companies`, `jobs`, `applications` tables |

### Config (`config.yaml`)

`filter.llm_score_threshold` controls the cutoff (0–10) for what counts as a match. The LLM model and Ollama base URL are under `llm:`. All filter patterns are case-insensitive substring matches applied to the job title.
