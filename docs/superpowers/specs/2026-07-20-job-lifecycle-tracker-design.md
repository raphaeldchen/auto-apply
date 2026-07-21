# Job Lifecycle Tracker & Higher-Frequency Polling — Design Spec

**Date:** 2026-07-20
**Status:** Approved (design)

## Goal

Turn the auto-apply tool from a one-shot scraper into a scraper *and* tracker that:
1. Captures jobs closer to when they are released (higher-frequency polling).
2. Knows when a captured job has closed / been taken down (freshness lifecycle).
3. Lets the user track their own application status over time (applied / interviewing / offer / rejected).

Concepts are borrowed selectively from the open-source `job-scraper-main/job_manager.py`, adapted to our ATS-polling architecture rather than its LinkedIn-search architecture.

## Context

Our discovery model already fetches a company's **entire ATS board** on every poll (`pipeline/discovery/poller.py::fetch_jobs_for_company`), then returns only the *new* jobs. This is the freshest possible signal — the ATS is the origin — but we currently:
- have no notion of a job being alive or dead (`jobs` has no lifecycle column);
- poll only once per day (`pipeline/scheduler.py` uses a fixed `cron` trigger at 08:00);
- have an unused stub `applications` table (`db/schema.sql`).

Because we already fetch the whole board, **disappearance from the board is a nearly-free, authoritative closure signal** — no per-job URL re-checks needed (unlike `job_manager.py`, which must re-hit each LinkedIn URL because it discovers via search, not by board).

## Deliberate scope trims (vs a full `job_manager.py` port)

- **No time-based "expired" state.** Disappearance is the closure signal; marking still-live jobs stale after N days is redundant and risks hiding open jobs. States are just `open` / `closed`.
- **No hard-delete garbage collection.** `job_manager.py` deletes old dead rows to save Supabase storage; on local SQLite, retained closed jobs are valuable history (jobs you missed). Closed jobs are kept, marked `closed`.
- **Closure is factual, not suppressed by application.** `job_manager.py` skips expiry for applied jobs. Here, a job that genuinely leaves the board is `closed` regardless; the user's application row is always preserved and surfaced independently.

## Data model (`db/schema.sql`)

### `jobs` — three new columns

| Column | Type | Meaning |
|--------|------|---------|
| `job_state` | `TEXT NOT NULL DEFAULT 'open'` | `open` \| `closed` |
| `last_seen_at` | `TEXT` | Timestamp of the most recent **successful** poll that returned this job |
| `closed_at` | `TEXT` | Set when the job transitions to `closed`; cleared if it later reopens |

Existing columns (`id`, `company_id`, `title`, `url`, `location`, `description`, `first_seen_at`, `filter_status`, `llm_score`, `llm_reason`, `kw_reason`) and the composite PK `(id, company_id)` are unchanged. New columns are additive with safe defaults.

**Migration:** the schema is applied via `CREATE TABLE IF NOT EXISTS` at `init_db()`, which will **not** add columns to a pre-existing DB. `init_db` must gain idempotent `ALTER TABLE ... ADD COLUMN` guards (checking `PRAGMA table_info`) for the three new `jobs` columns and the new `applications.updated_at`, so existing local DBs upgrade in place without a re-init. The `UNIQUE(job_id, company_id)` constraint on `applications` (below) applies to fresh DBs; for an existing DB it is added only if the table has no duplicate rows (personal single-user DB — expected clean).

### `applications` — the app-status home (already exists, currently unused)

| Column | Type | Meaning |
|--------|------|---------|
| `id` | `INTEGER PK AUTOINCREMENT` | (existing) |
| `job_id` | `TEXT NOT NULL` | (existing) FK-ish to `jobs.id` |
| `company_id` | `INTEGER NOT NULL` | (existing) FK-ish to `jobs.company_id` |
| `applied_at` | `TEXT` | (existing) set when the row is created |
| `status` | `TEXT` | (existing) `applied` \| `interviewing` \| `offer` \| `rejected` |
| `updated_at` | `TEXT` | **new** — set on every status change |

At most one row per `(job_id, company_id)` — enforced by a `UNIQUE(job_id, company_id)` constraint so `apply` cannot create duplicates. The two lifecycles stay separate: the **posting's** life (`job_state`) lives on `jobs`; the **user's** relationship to it lives in `applications`.

## Reconciliation engine (the freshness core)

### The `poll_company` contract change

Today `poll_company` catches all fetch failures and returns `[]`, which is indistinguishable from "the board is legitimately empty." That ambiguity is dangerous for disappearance-detection: a blocked Workday poll (HTTP 406) returning `[]` would look like "every job at this company closed."

`poll_company` will return a richer result so the caller can tell success from failure:

```
PollResult(success: bool, current_ids: set[str], new_jobs: list[Job])
```

- `success=True` + `current_ids` = the full set of job IDs the board returned this poll.
- `success=False` (any caught exception) → `current_ids` is empty and **must not be used for reconciliation**.
- `new_jobs` = the previously-unseen jobs (same meaning as today's return value).

### Reconciliation rules (run only when `success` is True)

For the polled company, within one transaction:
1. **Present jobs** (`id in current_ids`): ensure `job_state='open'`, refresh `last_seen_at=now`, clear `closed_at`. This also **reopens** a previously-`closed` job that reappeared.
2. **Absent open jobs** (stored `open` jobs for this company whose `id not in current_ids`): set `job_state='closed'`, `closed_at=now`.
3. On `success=False`: **skip reconciliation entirely** — touch no rows for this company. This is the failure guard.

A *successful* poll that returns zero jobs **is honored** (a small company legitimately closed its last posting): only *failed* polls are guarded, and those raise exceptions that the client catches, so they surface as `success=False`, never as a valid empty set.

### Where it runs

Reconciliation is invoked from the poll path (`poll_company` itself, or a helper it calls, using the existing `conn`). `run_pipeline` (`pipeline/runner.py`) continues to drive per-company polling and is updated for the new return shape; the digest still reports newly-matched jobs as today.

## Scheduling (`config.yaml` + `pipeline/scheduler.py`)

- Add `schedule.poll_interval_minutes` to `config.yaml` (default **60**), parsed into the typed `Config` dataclass (`pipeline/config.py`).
- `scheduler.py` switches from the fixed daily `cron` trigger to an APScheduler `interval` trigger driven by that value.
- The `run --schedule` CLI entry point is unchanged in surface.

## Application-status CLI (`main.py`)

- `apply <job_id> <company_id>` — create an application row with `status='applied'`, `applied_at=now`, `updated_at=now`. Idempotent: if a row for `(job_id, company_id)` already exists, error and direct the user to `set-status` rather than duplicating. Allowed even if the job is `closed` (the user may have applied before it closed); the current `job_state` is shown in the confirmation.
- `set-status <job_id> <company_id> <status>` — update `status` and `updated_at`; `status` validated against the allowed set.
- `list-applications [--status <status>]` — list tracked applications joined to `jobs` (title, company name, `job_state`), so the user can see whether a job they applied to has since closed. Optional `--status` filter.

## Error handling & edge cases

- **Failed poll** (client exception): `success=False` → no reconciliation, no false closures. (Covers the Workday 406 case.)
- **Reappearing job**: presence in a successful poll reopens it (`open`, refreshed `last_seen_at`, `closed_at` cleared).
- **Empty-but-successful poll**: honored — the company's open jobs are all closed.
- **Deactivated company** (no longer polled): its jobs keep their last `job_state`; they are simply no longer reconciled. No time-based staleness in v1.
- **Applying to a closed job**: allowed; `job_state` surfaced so the user has context.
- **`set-status` / `apply` on a non-existent job or with an invalid status**: clean error message, non-zero exit, no row written.

## Testing

Unit tests (in-memory SQLite fixture, mirroring existing `tests/` patterns):
- **Reconciliation**: open→closed on disappearance; closed→reopen on reappearance; present jobs refresh `last_seen_at`; **empty-but-successful** poll closes all; **failed poll guard** leaves every row untouched.
- **`poll_company` return shape**: `PollResult` fields correct on success and on caught failure (success flag false, `current_ids` empty).
- **Config**: `poll_interval_minutes` parsed with default.
- **CLI**: `apply` creates a row; `set-status` updates status + `updated_at` and rejects invalid status; `list-applications` joins and filters correctly; applying to a closed job succeeds and surfaces `job_state`.

No new integration tests required — reconciliation is exercised through the existing (mockable) client seam, not live network.

## Out of scope (possible future specs)

- Aggregator/breadth sources (CareersFuture-style public APIs) for jobs beyond registered companies.
- Per-source polling cadence (single interval for now).
- Cloud-LLM scoring / LiteLLM abstraction (staying on local Ollama).
- Manual hard-delete/archival command for closed jobs.
