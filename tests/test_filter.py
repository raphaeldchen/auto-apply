from unittest.mock import patch
from models.company import Company
from models.job import Job
from pipeline.config import Config, UserConfig, FilterConfig, NotificationsConfig
from pipeline.db import upsert_company, upsert_jobs
from pipeline.filter import filter_jobs

def _config(threshold: float = 7.0) -> Config:
    return Config(
        user=UserConfig(desired_role="Software Engineer", desired_level="Senior", resume_path="./resume.pdf"),
        filter=FilterConfig(include_patterns=["software engineer"], exclude_patterns=["intern"], level_patterns=["senior"], llm_score_threshold=threshold),
        notifications=NotificationsConfig(type="terminal"),
    )

def _seed_jobs(db_conn) -> tuple[Company, list[Job]]:
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    jobs = [
        Job(id="j1", company_id=company.id, title="Senior Software Engineer", url=None, location=None, description="Great role"),
        Job(id="j2", company_id=company.id, title="Software Engineer Intern", url=None, location=None, description="Internship"),
        Job(id="j3", company_id=company.id, title="Senior Software Engineer II", url=None, location=None, description="Another good role"),
    ]
    upsert_jobs(db_conn, jobs)
    return company, jobs

def test_filter_jobs_routes_to_correct_buckets(db_conn):
    _, jobs = _seed_jobs(db_conn)
    with patch("pipeline.filter.score_job", return_value=(8.0, "strong match")):
        matched, kw_filtered, llm_filtered = filter_jobs(jobs, _config(), db_conn)
    assert len(kw_filtered) == 1
    assert kw_filtered[0].id == "j2"
    assert len(matched) == 2

def test_filter_jobs_routes_to_llm_filtered_below_threshold(db_conn):
    _, jobs = _seed_jobs(db_conn)
    with patch("pipeline.filter.score_job", return_value=(5.0, "weak match")):
        matched, kw_filtered, llm_filtered = filter_jobs(jobs, _config(), db_conn)
    assert len(llm_filtered) == 2
    assert len(matched) == 0

def test_filter_jobs_sets_llm_score_on_job(db_conn):
    _, jobs = _seed_jobs(db_conn)
    with patch("pipeline.filter.score_job", return_value=(9.1, "exact match")):
        matched, _, _ = filter_jobs(jobs, _config(), db_conn)
    assert matched[0].llm_score == 9.1
    assert matched[0].llm_reason == "exact match"
