from unittest.mock import patch
from models.company import Company
from models.job import Job, RawJob
from pipeline.db import upsert_company, upsert_jobs, get_seen_job_ids
from pipeline.discovery.poller import poll_company, PollResult

def test_poll_returns_only_new_jobs(db_conn):
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(db_conn, [Job(id="old-1", company_id=company.id, title="Old Job", url=None, location=None, description=None)])
    raw = [
        RawJob(id="old-1", title="Old Job", url=None, location=None, description=None),
        RawJob(id="new-2", title="New Job", url=None, location=None, description=None),
    ]
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", return_value=raw):
        result = poll_company(company, db_conn)
    assert result.success is True
    assert len(result.new_jobs) == 1
    assert result.new_jobs[0].id == "new-2"
    assert result.new_jobs[0].company_id == company.id

def test_poll_persists_all_jobs_not_just_new(db_conn):
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    raw = [RawJob(id="j1", title="Job 1", url=None, location=None, description=None)]
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", return_value=raw):
        poll_company(company, db_conn)
    seen = get_seen_job_ids(db_conn, company.id)
    assert "j1" in seen

def test_poll_returns_empty_on_http_error(db_conn):
    import httpx
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", side_effect=httpx.HTTPError("connection refused")):
        result = poll_company(company, db_conn)
    assert result.success is False
    assert result.new_jobs == []


def test_poll_returns_empty_on_malformed_token(db_conn):
    company = upsert_company(
        db_conn,
        Company(
            name="BadCo",
            slug="bad-token-no-slash",
            ats_type="workday",
            board_token="bad-token-no-slash",
            status="active",
        ),
    )
    with patch(
        "pipeline.discovery.poller.fetch_jobs_for_company",
        side_effect=ValueError("no slash"),
    ):
        result = poll_company(company, db_conn)
    assert result.success is False
    assert result.new_jobs == []

def test_poll_returns_empty_on_playwright_error(db_conn, monkeypatch):
    from playwright.sync_api import Error as PlaywrightError
    from pipeline.discovery import poller
    company = upsert_company(db_conn, Company(
        name="Workday", slug="workday.wd5/Workday", ats_type="workday",
        board_token="workday.wd5/Workday", status="active"))

    def boom(token):
        raise PlaywrightError("navigation timeout")

    monkeypatch.setitem(poller._CLIENT_MAP, "workday", boom)
    result = poller.poll_company(company, db_conn)
    assert result.success is False
    assert result.new_jobs == []


def test_poll_marks_disappeared_job_closed(db_conn):
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(db_conn, [Job(id="gone-1", company_id=company.id, title="Gone", url=None, location=None, description=None)])
    raw = [RawJob(id="present-2", title="Present", url=None, location=None, description=None)]
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", return_value=raw):
        result = poll_company(company, db_conn)
    assert result.success is True
    gone = db_conn.execute("SELECT job_state FROM jobs WHERE id='gone-1' AND company_id=?", (company.id,)).fetchone()
    present = db_conn.execute("SELECT job_state FROM jobs WHERE id='present-2' AND company_id=?", (company.id,)).fetchone()
    assert gone["job_state"] == "closed"
    assert present["job_state"] == "open"


def test_poll_failure_does_not_close_jobs(db_conn):
    import httpx
    company = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(db_conn, [Job(id="keep-1", company_id=company.id, title="Keep", url=None, location=None, description=None)])
    with patch("pipeline.discovery.poller.fetch_jobs_for_company", side_effect=httpx.HTTPError("down")):
        result = poll_company(company, db_conn)
    assert result.success is False
    row = db_conn.execute("SELECT job_state FROM jobs WHERE id='keep-1' AND company_id=?", (company.id,)).fetchone()
    assert row["job_state"] == "open"
