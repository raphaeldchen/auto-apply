from models.company import Company
from models.job import Job
from pipeline.db import (
    upsert_company, get_all_companies, get_active_companies,
    get_seen_job_ids, upsert_jobs, update_job_filter_status, get_matched_jobs,
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


def test_init_db_has_lifecycle_columns(tmp_path):
    from pipeline.db import init_db
    conn = init_db(str(tmp_path / "fresh.db"))
    job_cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"job_state", "last_seen_at", "closed_at"} <= job_cols
    app_cols = {r["name"] for r in conn.execute("PRAGMA table_info(applications)")}
    assert "updated_at" in app_cols
    conn.close()


def test_applications_reject_duplicate_pair(tmp_path):
    import sqlite3
    import pytest
    from pipeline.db import init_db
    conn = init_db(str(tmp_path / "fresh.db"))
    conn.execute("INSERT INTO applications (job_id, company_id, status) VALUES ('j1', 1, 'applied')")
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO applications (job_id, company_id, status) VALUES ('j1', 1, 'applied')")
        conn.commit()
    conn.close()


def test_init_db_migrates_legacy_db(tmp_path):
    import sqlite3
    from pipeline.db import init_db
    path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(path)
    legacy.executescript(
        """
        CREATE TABLE jobs (
            id TEXT NOT NULL, company_id INTEGER NOT NULL, title TEXT NOT NULL,
            url TEXT, location TEXT, description TEXT, first_seen_at TEXT NOT NULL,
            filter_status TEXT NOT NULL DEFAULT 'new', llm_score REAL, llm_reason TEXT,
            kw_reason TEXT, PRIMARY KEY (id, company_id)
        );
        CREATE TABLE applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
            company_id INTEGER NOT NULL, applied_at TEXT, status TEXT
        );
        """
    )
    legacy.commit()
    legacy.close()

    conn = init_db(path)
    job_cols = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"job_state", "last_seen_at", "closed_at"} <= job_cols
    app_cols = {r["name"] for r in conn.execute("PRAGMA table_info(applications)")}
    assert "updated_at" in app_cols
    conn.close()
