import sqlite3
from dataclasses import dataclass, field
import httpx
from playwright.sync_api import Error as PlaywrightError
from models.company import Company
from models.job import Job, RawJob
from pipeline.db import get_seen_job_ids, upsert_jobs, reconcile_job_states
from pipeline.discovery.clients import greenhouse, lever, ashby, workday

_CLIENT_MAP = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
    "workday": workday.fetch_jobs,
}

@dataclass
class PollResult:
    success: bool
    current_ids: set[str] = field(default_factory=set)
    new_jobs: list[Job] = field(default_factory=list)

def fetch_jobs_for_company(company: Company) -> list[RawJob]:
    return _CLIENT_MAP[company.ats_type](company.board_token)

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
