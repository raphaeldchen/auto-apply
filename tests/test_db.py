import sqlite3

from models.company import Company
from models.job import Job
from pipeline.db import (
    upsert_company, get_all_companies, get_active_companies,
    get_seen_job_ids, upsert_jobs, update_job_filter_status, get_matched_jobs,
    init_db, set_company_tier, get_job,
)

def test_upsert_company_creates_and_returns_id(db_conn):
    c = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                board_token="stripe", status="active")
    saved = upsert_company(db_conn, c)
    assert saved.id is not None

def test_upsert_company_updates_on_duplicate_name(db_conn):
    c = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                board_token="stripe", status="active")
    upsert_company(db_conn, c)
    c2 = Company(name="Stripe", slug="stripe", ats_type="lever",
                 board_token="stripe-new", status="active")
    saved = upsert_company(db_conn, c2)
    companies = get_all_companies(db_conn)
    assert len(companies) == 1
    assert companies[0].ats_type == "lever"

def test_get_active_companies_excludes_unsupported(db_conn):
    upsert_company(db_conn, Company(name="A", slug="a", ats_type="greenhouse",
                                    board_token="a", status="active"))
    upsert_company(db_conn, Company(name="B", slug="b", ats_type=None,
                                    board_token=None, status="unsupported"))
    assert len(get_active_companies(db_conn)) == 1

def test_get_seen_job_ids_returns_existing(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe",
                                         ats_type="greenhouse", board_token="stripe",
                                         status="active"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="SWE",
                               url=None, location=None, description=None)])
    update_job_filter_status(db_conn, "j1", c.id, "matched")
    seen = get_seen_job_ids(db_conn, c.id)
    assert "j1" in seen

def test_get_seen_job_ids_excludes_kw_filtered(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe",
                                         ats_type="greenhouse", board_token="stripe",
                                         status="active"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="SWE",
                               url=None, location=None, description=None)])
    update_job_filter_status(db_conn, "j1", c.id, "kw_filtered", kw_reason="no include pattern match")
    seen = get_seen_job_ids(db_conn, c.id)
    assert "j1" not in seen

def test_upsert_jobs_ignores_duplicate(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe",
                                         ats_type="greenhouse", board_token="stripe",
                                         status="active"))
    job = Job(id="j1", company_id=c.id, title="SWE", url=None, location=None, description=None)
    upsert_jobs(db_conn, [job])
    upsert_jobs(db_conn, [job])
    seen = get_seen_job_ids(db_conn, c.id)
    assert len(seen) == 1

def test_get_job_returns_job(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                                        board_token="stripe", status="active"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="ML Intern",
                              url=None, location=None, description="Python required")])
    job = get_job(db_conn, "j1", c.id)
    assert job is not None
    assert job.description == "Python required"

def test_get_job_missing_returns_none(db_conn):
    assert get_job(db_conn, "nope", 1) is None

def test_company_tier_defaults_to_standard(db_conn):
    c = Company(name="Humana", slug="humana", ats_type="workday",
                board_token="humana/External", status="active")
    upsert_company(db_conn, c)
    companies = get_all_companies(db_conn)
    assert companies[0].tier == "standard"

def test_upsert_company_persists_tier(db_conn):
    c = Company(name="OpenAI", slug="openai", ats_type="greenhouse",
                board_token="openai", status="active", tier="reach")
    upsert_company(db_conn, c)
    companies = get_all_companies(db_conn)
    assert companies[0].tier == "reach"

def test_upsert_company_updates_tier_on_duplicate_name(db_conn):
    c = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                board_token="stripe", status="active", tier="standard")
    upsert_company(db_conn, c)
    c2 = Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                 board_token="stripe", status="active", tier="reach")
    upsert_company(db_conn, c2)
    companies = get_all_companies(db_conn)
    assert len(companies) == 1
    assert companies[0].tier == "reach"

def test_set_company_tier_updates_existing(db_conn):
    upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                                    board_token="stripe", status="active"))
    assert set_company_tier(db_conn, "Stripe", "reach") is True
    assert get_all_companies(db_conn)[0].tier == "reach"

def test_set_company_tier_unknown_company_returns_false(db_conn):
    assert set_company_tier(db_conn, "Nope Inc", "reach") is False

def test_init_db_migrates_existing_db_without_tier_column(tmp_path):
    db_file = tmp_path / "old.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """CREATE TABLE companies (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT NOT NULL UNIQUE,
               slug TEXT NOT NULL,
               ats_type TEXT,
               board_token TEXT,
               status TEXT NOT NULL DEFAULT 'active',
               detected_at TEXT)"""
    )
    conn.execute("INSERT INTO companies (name, slug, status) VALUES ('Old Co', 'old', 'active')")
    conn.commit()
    conn.close()
    conn = init_db(str(db_file))
    try:
        row = conn.execute("SELECT tier FROM companies WHERE name = 'Old Co'").fetchone()
        assert row["tier"] == "standard"
    finally:
        conn.close()

def test_get_matched_jobs_includes_company_tier(db_conn):
    c = upsert_company(db_conn, Company(name="OpenAI", slug="openai",
                                        ats_type="greenhouse", board_token="openai",
                                        status="active", tier="reach"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="ML Intern",
                              url=None, location=None, description=None)])
    update_job_filter_status(db_conn, "j1", c.id, "matched", 9.0, "great fit")
    matched = get_matched_jobs(db_conn)
    assert matched[0][1].tier == "reach"

def test_update_job_filter_status(db_conn):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe",
                                         ats_type="greenhouse", board_token="stripe",
                                         status="active"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="SWE",
                               url=None, location=None, description=None)])
    update_job_filter_status(db_conn, "j1", c.id, "matched", 8.5, "strong match")
    matched = get_matched_jobs(db_conn)
    assert len(matched) == 1
    job, company = matched[0]
    assert job.llm_score == 8.5
    assert job.llm_reason == "strong match"
