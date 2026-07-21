import sqlite3
from datetime import datetime
from models.digest import DigestResult, CompanyDigest
from pipeline.config import Config
from pipeline.db import get_active_companies, get_all_companies
from pipeline.discovery.poller import poll_company
from pipeline.filter import filter_jobs

def run_pipeline(config: Config, conn: sqlite3.Connection) -> DigestResult:
    active = get_active_companies(conn)
    all_companies = get_all_companies(conn)
    unsupported = [c for c in all_companies if c.status == "unsupported"]
    company_digests = []
    for company in active:
        poll = poll_company(company, conn)
        matched, kw_filtered, llm_filtered = filter_jobs(poll.new_jobs, config, conn)
        company_digests.append(CompanyDigest(company=company, matched=matched, kw_filtered=kw_filtered, llm_filtered=llm_filtered))
    return DigestResult(
        date=datetime.now().strftime("%Y-%m-%d"),
        companies=company_digests,
        unsupported_companies=unsupported,
    )
