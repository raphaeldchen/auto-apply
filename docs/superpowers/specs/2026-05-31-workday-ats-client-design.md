# Workday ATS Client

**Date:** 2026-05-31
**Status:** Approved

## Summary

Add a Workday ATS client to the discovery pipeline. Workday companies are registered manually (no auto-detection); a new `--ats-type` flag on `add-company` bypasses the detection step when the user already knows the ATS.

## Token Format

Workday requires two identifiers: a company subdomain (which includes the Workday version) and a board name. These are stored together in the existing `board_token` column as a single composite string split by `/`:

```
{subdomain}/{board}
```

Examples:
- `stripe.wd5/ExternalCareerSite`
- `google.wd3/GoogleCareers`

No schema changes are needed.

## Components

### `pipeline/discovery/clients/workday.py` (new)

- Splits `board_token` on `/` to extract `subdomain` and `board`
- POSTs to `https://{subdomain}.myworkdayjobs.com/wday/cxs/{subdomain}/{board}/jobs` with body `{"appliedFacets": {}, "limit": 20, "offset": <n>, "searchText": ""}`
- Paginates by incrementing `offset` by 20 until all jobs are fetched (`offset >= total`)
- Maps response `jobPostings` entries to `RawJob`:
  - `id`: `externalPath` field (unique per posting)
  - `title`: `title` field
  - `url`: `https://{subdomain}.myworkdayjobs.com{externalPath}`
  - `location`: `locationsText` field
  - `description`: `None` (list endpoint does not reliably return full descriptions; the LLM scorer already handles this gracefully)

### `pipeline/discovery/poller.py` (modify)

Add `"workday": workday.fetch_jobs` to `_CLIENT_MAP`. Workday is intentionally absent from `detector.py`'s `_ATS_PROBE_URLS` — auto-detection is out of scope.

### `main.py` (modify)

Add `--ats-type` option to the `add-company` command. Behavior:

- `--ats-type` + `--slug` both provided → skip `detect_ats()`, register company directly with the given values
- Only `--slug` provided → existing behavior (run detection with that slug override)
- Neither provided → existing behavior (run detection with auto-generated slug variants)

## Out of Scope

- Auto-detection of Workday companies
- Fetching per-job descriptions (can be added later via the detail endpoint `…/job/{path}/jobDetails`)

## Usage Example

```bash
python main.py add-company --name "Stripe" --ats-type workday --slug "stripe.wd5/ExternalCareerSite"
python main.py run
```
