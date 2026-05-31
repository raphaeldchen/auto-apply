# Workday Playwright Client

**Date:** 2026-05-31
**Status:** Approved

## Problem

Workday's CXS API (`/wday/cxs/.../jobs`) returns HTTP 422 for all automated requests due to Cloudflare bot detection. This breaks both `fetch_jobs` (job polling) and `probe_workday` (auto-detection). A headless Chromium browser via Playwright handles the Cloudflare challenge automatically.

## Components

### `pipeline/discovery/clients/workday.py` (rewrite)

**`_parse_jobs(data: dict, base_url: str) -> list[RawJob]`**
Pure function. Maps a Workday CXS API JSON response (`{"total": N, "jobPostings": [...]}`) to a list of `RawJob` objects. Extracted so it can be tested without a browser.

**`fetch_jobs(board_token: str) -> list[RawJob]`**
Replaces httpx with `sync_playwright` (Playwright's synchronous API, compatible with the existing sync `fetch_jobs` contract):
1. Split `board_token` on `/` → `subdomain`, `board`
2. Launch headless Chromium
3. Set up a response interceptor on `**/wday/cxs/**/jobs`
4. Navigate to `https://{subdomain}.myworkdayjobs.com/en-US/{board}`
5. Capture the initial XHR response (first 20 jobs)
6. Repeatedly click the "Load more jobs" button until it's absent, capturing each subsequent XHR response
7. Close browser, return all collected jobs via `_parse_jobs`

**`probe_workday(slug: str) -> tuple[str, str] | None`**
Replaces httpx with `async_playwright`. Removes the `client: httpx.AsyncClient` parameter — no shared client needed. One browser instance, tries combinations sequentially:
- For each version in `WORKDAY_VERSIONS`, for each board in `WORKDAY_BOARD_NAMES`:
  - Navigate to `https://{slug}.{version}.myworkdayjobs.com/en-US/{board}`
  - Intercept the first CXS response; if status 200 → return `("workday", f"{slug}.{version}/{board}")`
  - If page errors or no valid response → continue

**Constants (updated):**
```python
WORKDAY_VERSIONS = ["wd5", "wd3", "wd1", "wd2"]
WORKDAY_BOARD_NAMES = ["ExternalCareerSite", "External", "Careers", "externalsite", "Workday"]
```
`"Workday"` added to cover Workday, Inc. themselves.

### `pipeline/discovery/detector.py` (small change)

Update the `probe_workday` call to drop the `client` argument:
```python
# Before
result = await probe_workday(client, slug)
# After
result = await probe_workday(slug)
```

### `pyproject.toml`

Add `playwright>=1.40` to `[project] dependencies`.

## Testing

| What | How |
|---|---|
| `_parse_jobs` | Unit tests with fixture JSON — no browser needed |
| `fetch_jobs`, `probe_workday` | `@pytest.mark.integration` — skipped in normal suite, require real browser + network |
| Existing httpx mock tests | Replaced by `_parse_jobs` unit tests |

The `asyncio_mode = "auto"` config in `pyproject.toml` already handles async tests.

## Installation Note

After adding the dependency, Chromium must be installed once:
```bash
pip install playwright
playwright install chromium
```

## Out of Scope

- Other ATS clients (Greenhouse, Lever, Ashby use GET APIs unaffected by Cloudflare)
- Persistent browser sessions across pipeline runs
