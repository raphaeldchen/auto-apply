# Workday Hardening & Seed-List Discovery — Design

**Date:** 2026-07-18
**Status:** Approved, pending implementation plan

## Problem

Workday support already exists: `pipeline/discovery/clients/workday.py` provides
Playwright-based `fetch_jobs` and `probe_workday`, wired into `detect_ats` and the
`add-company` CLI, with passing unit tests for `_parse_jobs`. Two gaps remain:

1. **Fragility.** `poll_company` does not catch Playwright exceptions, so a single
   bad Workday board can crash an entire `run` instead of being logged and skipped
   the way Greenhouse/Lever/Ashby failures are.
2. **No bulk onboarding.** Companies are added one at a time via `add-company`.
   There's no way to seed many known-Workday employers at once.

## Goals

- Make Workday polling failures non-fatal to a pipeline run.
- Confirm the Playwright `fetch_jobs` / `probe_workday` paths work end-to-end.
- Provide a curated seed list and a bulk-registration CLI command.

## Non-goals

- Scraping third-party "built with Workday" directories.
- Batch-probing large generic name lists (S&P 500, etc.) through the full ATS sweep.
- Guaranteeing seed-list accuracy — ATS choice changes over time; the list is a
  starting point the user maintains.

## Part 1 — Harden the Workday client

### Poller exception handling

`pipeline/discovery/poller.py:poll_company` currently catches
`(httpx.HTTPError, KeyError, ValueError)`. Playwright raises
`playwright.sync_api.Error` (and its subclass `TimeoutError`) on navigation and
selector failures. Add `playwright.sync_api.Error` to the caught tuple so a failed
Workday fetch is logged and returns `[]`, consistent with other ATS clients.

### End-to-end verification

Run the two `@pytest.mark.integration` tests in `tests/test_workday.py` live
(requires `playwright install chromium` and network access) to confirm the real
browser-automation paths work, not just the unit-tested `_parse_jobs` transform.

## Part 2 — Seed-list bulk registration

### Seed file

`companies_seed.yaml` at repo root. Flat list of company names:

```yaml
# Companies believed to use Workday ATS.
# VERIFY each entry — ATS choice changes over time. Prune/extend freely.
companies:
  - "Company A"
  - "Company B"
```

Ships with ~15–20 large employers believed to use Workday, each understood to be
"verify these," not authoritative.

### DB helper

Add a lookup in `pipeline/db.py` to check whether a company name is already
registered (e.g. `get_company_by_name`), so the bulk command can skip existing
entries. Reuse an existing helper if one already covers this.

### CLI command

`main.py add-companies --seed-file companies_seed.yaml`:

- Load the YAML `companies` list.
- Skip names already present in the `companies` table.
- For each remaining name, run `probe_workday` against slug variants of the name —
  **not** the full `detect_ats` sweep, since the list already asserts Workday. This
  is faster and avoids false positives from another ATS matching first.
- Probe concurrently via `asyncio.gather`, matching `detect_ats`'s pattern.
- On hit: `upsert_company` with `ats_type="workday"`, print `✓ {name} → {token}`.
- On miss: print `✗ {name} — not found on Workday`, leave unregistered, continue.
- A single miss never aborts the batch.

## Part 3 — Tests

- Unit tests for the bulk-add logic with `probe_workday` mocked:
  skip-if-exists, success path, miss path, mixed batch.
- Confirm the `poll_company` except clause includes `playwright.sync_api.Error`
  (covered by existing failure-path test style).

## Open questions

None outstanding.
