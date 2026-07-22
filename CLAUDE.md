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
| `pipeline/materials/aliases.py` | Skill lexicon (`aliases.yaml`) matcher: canonical terms, boundary-aware, case-sensitive short terms |
| `pipeline/materials/profile.py` | Loads `profile.yaml` → `FactBase` of ID-addressable bullets (`{section_id}.{index}`) |
| `pipeline/materials/jd_analyzer.py` | Regex JD analysis: keywords, years, degrees, level, clearance/sponsorship flags |
| `pipeline/materials/coverage.py` | JD keywords × fact base → have/partial/lack rows + weighted score |
| `pipeline/materials/selector.py` | Deterministic greedy bullet selection (min-per-section → marginal coverage → fill) |
| `pipeline/materials/renderer.py` | Jinja2 (autoescaped) resume HTML + Playwright Chromium PDF |
| `pipeline/materials/verify.py` | Rephrase verifier: numeric multiset invariance, entity whitelist, proper-noun check |
| `pipeline/materials/rephrase.py` | Anthropic Messages call proposing rephrases; every candidate verified, fail-closed to verbatim |
| `pipeline/materials/letter.py` | Fact-cited cover-letter generation: verify → one retry with violations fed back → fail closed to no letter |
| `pipeline/apply/answers.py` | Answer memory (`answers.yaml`): pattern→answer entries, EEO/sensitive question detection |
| `pipeline/apply/questions.py` | Greenhouse `?questions=true` form-schema fetcher → `FormQuestion` |
| `pipeline/apply/planner.py` | Questions × memory × profile → fill plan (auto/attachment/answered/sensitive/needs_input); never guesses |
| `pipeline/notifier.py` | Terminal digest printer |
| `pipeline/scheduler.py` | APScheduler wrapper for daily runs |
| `models/` | Plain dataclasses: `Company`, `Job`, `RawJob`, `DigestResult`, `CompanyDigest`, `Profile`/`FactBase` |
| `db/schema.sql` | SQLite DDL for `companies`, `jobs`, `applications` tables |

### Materials pipeline invariant

"LLM proposes, harness disposes": generated resumes and cover letters may only contain facts from `profile.yaml` (the fact base). The `tailor` command is fully deterministic by default; `--polish` adds LLM rephrasing where every candidate must pass `verify_rephrase` or that bullet falls back to verbatim. The `letter` command requires every paragraph to cite bullet ids/skills; `verify_letter` checks terms, numbers, company/title presence, and cross-company contamination — an unverifiable letter is simply not produced. Never bypass the verifiers or add free-form LLM rewriting. Every output gets a `{out}.manifest.json` provenance record.

### Config (`config.yaml`)

`filter.llm_score_threshold` controls the cutoff (0–10) for what counts as a match. The LLM model and Ollama base URL are under `llm:`. All filter patterns are case-insensitive substring matches applied to the job title.

`generation.tiers` (optional) maps company tier → Claude model for `tailor --polish`; defaults are reach=`claude-opus-4-8`, target=`claude-sonnet-5`, standard=`claude-haiku-4-5`. Partial overrides merge with defaults. Requires `ANTHROPIC_API_KEY`; without it, polish fails closed to the verbatim resume.

`user.answers_path` (default `answers.yaml`) is the answer memory used by the `questions` command; empty answers are treated as pending and never filled, and EEO/self-identification questions are only answered if the user explicitly stored an entry.
