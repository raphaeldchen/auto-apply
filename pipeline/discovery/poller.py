import sqlite3
import httpx
from models.company import Company
from models.job import Job, RawJob
from pipeline.db import get_seen_job_ids, upsert_jobs
from pipeline.discovery.clients import greenhouse, lever, ashby, workday

_CLIENT_MAP = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
    "workday": workday.fetch_jobs,
}

def fetch_jobs_for_company(company: Company) -> list[RawJob]:
    return _CLIENT_MAP[company.ats_type](company.board_token)

def poll_company(company: Company, conn: sqlite3.Connection) -> list[Job]:
    try:
        raw_jobs = fetch_jobs_for_company(company)
    except (httpx.HTTPError, KeyError, ValueError) as e:
        print(f"Failed to fetch jobs for {company.name}: {e}")
        return []
    seen_ids = get_seen_job_ids(conn, company.id)
    all_jobs = [
        Job(id=r.id, company_id=company.id, title=r.title, url=r.url, location=r.location, description=r.description)
        for r in raw_jobs
    ]
    upsert_jobs(conn, all_jobs)
    return [j for j in all_jobs if j.id not in seen_ids]
