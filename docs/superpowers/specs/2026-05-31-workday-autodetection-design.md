# Workday Auto-Detection

**Date:** 2026-05-31
**Status:** Approved

## Summary

Add auto-detection support for Workday ATS to the `detect_ats` pipeline. Given a company name, the detector will probe common Workday subdomain + version + board name combinations concurrently and return the first match. This removes the requirement to pass `--ats-type workday --slug` manually for most companies.

## Approach

Lean probing: try a small fixed set of board names across all Workday version numbers, fired concurrently. Workday probes only run after Greenhouse/Lever/Ashby probes fail, so there is no cost for companies already on those platforms.

## Constants (added to `pipeline/discovery/clients/workday.py`)

```python
WORKDAY_VERSIONS = ["wd5", "wd3", "wd1", "wd2"]  # ordered by real-world frequency
WORKDAY_BOARD_NAMES = ["ExternalCareerSite", "External", "Careers", "externalsite"]
```

Total combinations per slug variant: 4 versions × 4 board names = 16 probes.
Total with 3 slug variants: 48 concurrent probes.

## Probe Mechanism

Each probe POSTs to the Workday jobs endpoint with a minimal body (`limit=1`) and checks for HTTP 200. This reuses the same URL pattern as `fetch_jobs`:

```
POST https://{subdomain}.myworkdayjobs.com/wday/cxs/{subdomain}/{board}/jobs
Body: {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
```

A 200 response indicates a valid board. The returned `board_token` uses the composite format: `{slug}.{version}/{board}` (e.g. `stripe.wd5/ExternalCareerSite`).

## Components

### `pipeline/discovery/clients/workday.py` (modify)

Add:
- `WORKDAY_VERSIONS` and `WORKDAY_BOARD_NAMES` constants
- `async def probe_workday(client: httpx.AsyncClient, slug: str) -> tuple[str, str] | None`
  - Generates all `(subdomain, board)` combinations where `subdomain = f"{slug}.{version}"`
  - Fires all probes concurrently via `asyncio.gather`
  - Returns `("workday", f"{subdomain}/{board}")` for the first 200 response, or `None`

### `pipeline/discovery/detector.py` (modify)

In `detect_ats`, after the existing 3-ATS probe loop returns no result, iterate over slug variants calling `probe_workday(client, slug)` and return the first non-None result.

Workday is intentionally absent from `_ATS_PROBE_URLS` — its probe is POST-based and multi-dimensional, so it runs separately rather than through the generic `_probe` helper.

## Data Flow

```
detect_ats("Stripe")
  └─ generate_slug_variants("Stripe")  →  ["stripe", "stripe-inc", ...]
  └─ probe Greenhouse / Lever / Ashby  →  None
  └─ probe_workday(client, "stripe")
       └─ stripe.wd5/ExternalCareerSite  →  200 ✓
       └─ return ("workday", "stripe.wd5/ExternalCareerSite")
```

## Unchanged

- `--ats-type workday --slug` manual override continues to work as before
- `fetch_jobs` is unchanged
- No schema changes

## Usage After This Change

```bash
# Workday now detected automatically — no --ats-type needed
python main.py add-company --name "Stripe"
# ✓ Stripe → workday (token: stripe.wd5/ExternalCareerSite)
```
