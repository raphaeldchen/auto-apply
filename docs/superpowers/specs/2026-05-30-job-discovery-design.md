# Job Application Automation Agent — Discovery & Filter Design

## Overview

Personal-use AI agent that monitors a user-configured list of target companies' ATS job boards daily, filters new postings for relevance, and (in future phases) tailors resumes and submits applications automatically.

## Scope

This spec covers **Stages 1 & 2** of the pipeline: discovery and filtering.  
Stages 3 (resume tailoring) and 4 (auto-apply) are out of scope and reserved as designed plug-in slots.

---

## Architecture

Four-stage modular pipeline triggered by a daily scheduler:

```
[Scheduler] → [Stage 1: Discover] → [Stage 2: Filter] → [Stage 3: Tailor*] → [Stage 4: Apply*]
                                                                  * future
```

Each stage is an independent module with a well-defined input/output interface. This allows stages to be tested in isolation and extended without touching upstream logic.

**Output (Phase 1):** Terminal digest printed at the end of each daily run.  
**Planned output (future):** Email or SMS notification.

---

## Stage 1: Discovery

### Supported ATSes

| ATS        | Public API endpoint                                              | Auth         |
|------------|------------------------------------------------------------------|--------------|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`        | None — public |
| Lever      | `https://api.lever.co/v0/postings/{slug}`                        | None — public |
| Ashby      | `https://api.ashbyhq.com/posting-api/job-board/{slug}`           | None — public |

Companies using any other ATS are flagged as `unsupported` and skipped in daily runs. Users are notified at setup time.

### Company Registration

**Auto-detection flow:**

1. Generate slug variants from the company name:
   - Lowercase, strip legal suffixes (`Inc`, `Corp`, `LLC`, `Ltd`, `Co`)
   - Strip punctuation (commas, periods, ampersands)
   - Produce 3 spacing variants per base: hyphenated (`open-ai`), concatenated (`openai`), underscored (`open_ai`)
2. Probe all 3 ATSes × all slug variants in parallel (async HTTP)
3. First `200 OK` → save `company`, `ats_type`, `board_token` to SQLite
4. All probes `404` → flag as `unsupported`; user may retry with `--slug` override

### Daily Job Fetch & Diff

For each `active` company:

1. Fetch full current job list from its ATS API
2. Compare job IDs against `jobs` table in SQLite
3. Upsert the full list (enabling future "job closed" detection)
4. Emit only new job IDs downstream to Stage 2

---

## Stage 2: Filter

### Pass 1 — Keyword Pre-filter

Runs on job **title only**. No API calls. All patterns are case-insensitive substring matches.

| Config key          | Behaviour                                          |
|---------------------|----------------------------------------------------|
| `include_patterns`  | At least one must match — otherwise reject         |
| `exclude_patterns`  | Any match → auto-reject                            |
| `level_patterns`    | If non-empty, at least one must match title        |

Rejected jobs are written to SQLite with `filter_status = kw_filtered` (not discarded — enables auditing).

### Pass 2 — LLM Relevance Scorer

Runs only on jobs that passed the keyword filter.

**Input:** job title + full description + `desired_role` + `desired_level`  
**Output:** `{"score": float, "reason": str}` (structured JSON response)

**Scoring criteria instructed in prompt:**
- Is this the right role type?
- Is this the right seniority level?
- Is this full-time (not contract or intern)?

**Threshold:** `llm_score_threshold` (default `7.0`, configurable)
- `score ≥ threshold` → `filter_status = matched`
- `score < threshold` → `filter_status = llm_filtered`

The `reason` string is surfaced in the terminal digest and stored in SQLite for auditability.

---

## Data Model

### SQLite Schema

```sql
CREATE TABLE companies (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    ats_type    TEXT,                        -- 'greenhouse' | 'lever' | 'ashby' | NULL
    board_token TEXT,
    status      TEXT NOT NULL DEFAULT 'active',  -- 'active' | 'unsupported'
    detected_at TIMESTAMP
);

CREATE TABLE jobs (
    id             TEXT    NOT NULL,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    title          TEXT    NOT NULL,
    url            TEXT,
    location       TEXT,
    description    TEXT,
    first_seen_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    filter_status  TEXT NOT NULL DEFAULT 'new',
                   -- 'new' | 'kw_filtered' | 'llm_filtered' | 'matched'
    llm_score      REAL,
    llm_reason     TEXT,
    PRIMARY KEY (id, company_id)
);

-- Reserved for Stage 4
CREATE TABLE applications (
    id          INTEGER PRIMARY KEY,
    job_id      TEXT    NOT NULL,
    company_id  INTEGER NOT NULL,
    applied_at  TIMESTAMP,
    status      TEXT    -- 'pending' | 'submitted' | 'failed'
);
```

---

## Configuration

`config.yaml` at the project root. Companies are **not** listed here — they are managed via the CLI and stored in SQLite (single source of truth).

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
  type: terminal   # terminal | email | sms (future)
```

Companies are added with:
```
python main.py add-company --name "Stripe"            # auto-detect slug
python main.py add-company --name "Warner Bros" --slug warnermedia  # manual override
python main.py list-companies                          # show all registered companies + ATS
```

---

## Terminal Digest Format

```
=== Auto-Apply Daily Digest — 2026-05-30 ===

Stripe (Greenhouse)
  ✓ Senior Software Engineer, Backend — score 8.4 — "strong backend match, explicitly L5"
  ✗ [kw_filtered] Staff Engineer — excluded pattern: "staff"

OpenAI (Lever)
  ✓ Senior SWE, Foundations — score 9.1 — "exact role and level match"

Acme Corp
  ⚠ Unsupported ATS — run: python main.py add-company --name "Acme Corp" --slug <slug>

3 new matched jobs. Run python main.py show-matches to review.
```

---

## Project Structure

```
auto-apply/
├── main.py                       # CLI entrypoint (add-company, list-companies, run, show-matches)
├── config.yaml                   # User configuration
├── db/
│   └── schema.sql
├── pipeline/
│   ├── scheduler.py              # APScheduler — daily trigger
│   ├── discovery/
│   │   ├── detector.py           # ATS auto-detection + slug variant generation
│   │   ├── poller.py             # Daily fetch + diff against job store
│   │   └── clients/
│   │       ├── greenhouse.py
│   │       ├── lever.py
│   │       └── ashby.py
│   ├── filter/
│   │   ├── keyword.py            # Pass 1 — title pattern matching
│   │   └── llm_scorer.py         # Pass 2 — LLM relevance scoring
│   └── notifier.py               # Terminal digest (+ future email/SMS)
└── models/
    ├── company.py
    └── job.py
```

---

## Out of Scope (Phase 1)

- Resume tailoring (Stage 3)
- Application form submission (Stage 4)
- Email / SMS notifications
- Multi-user support
- Workday, iCIMS, SmartRecruiters, or other ATS support
