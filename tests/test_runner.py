from unittest.mock import patch
from models.company import Company
from models.job import Job
from models.digest import DigestResult
from pipeline.config import Config, UserConfig, FilterConfig, NotificationsConfig
from pipeline.db import upsert_company
from pipeline.runner import run_pipeline

def _config():
    return Config(
        user=UserConfig(desired_role="Software Engineer", desired_level="Senior", resume_path="./resume.pdf"),
        filter=FilterConfig(include_patterns=["software engineer"], exclude_patterns=[], level_patterns=[], llm_score_threshold=7.0),
        notifications=NotificationsConfig(type="terminal"),
    )

def test_run_pipeline_returns_digest(db_conn):
    upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    new_job = Job(id="j1", company_id=1, title="Senior Software Engineer", url=None, location=None, description="Great role")
    with patch("pipeline.runner.poll_company", return_value=[new_job]), \
         patch("pipeline.runner.filter_jobs", return_value=([new_job], [], [])):
        result = run_pipeline(_config(), db_conn)
    assert isinstance(result, DigestResult)
    assert len(result.companies) == 1
    assert result.companies[0].matched == [new_job]

def test_run_pipeline_includes_unsupported_companies(db_conn):
    upsert_company(db_conn, Company(name="Acme", slug="acme", ats_type=None, board_token=None, status="unsupported"))
    with patch("pipeline.runner.poll_company", return_value=[]), \
         patch("pipeline.runner.filter_jobs", return_value=([], [], [])):
        result = run_pipeline(_config(), db_conn)
    assert len(result.unsupported_companies) == 1
    assert result.unsupported_companies[0].name == "Acme"
