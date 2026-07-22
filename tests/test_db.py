import sqlite3

from models.company import Company
from models.job import Job
from pipeline.db import (
    upsert_company, get_all_companies, get_active_companies,
    get_seen_job_ids, upsert_jobs, update_job_filter_status, get_matched_jobs,
    get_open_job_ids, reconcile_job_states,
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


def _insert_job(conn, job_id, company_id, state="open"):
    # Ensure the company exists
    conn.execute(
        "INSERT OR IGNORE INTO companies (id, name, slug, ats_type, board_token, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (company_id, f"Company{company_id}", f"company{company_id}", "test", "token", "active"),
    )
    conn.execute(
        "INSERT INTO jobs (id, company_id, title, first_seen_at, job_state) "
        "VALUES (?, ?, 'T', '2026-01-01', ?)",
        (job_id, company_id, state),
    )
    conn.commit()


def test_reconcile_closes_absent_job(db_conn):
    _insert_job(db_conn, "gone", 1)
    _insert_job(db_conn, "here", 1)
    reconcile_job_states(db_conn, 1, {"here"})
    rows = {r["id"]: r for r in db_conn.execute(
        "SELECT id, job_state, closed_at, last_seen_at FROM jobs WHERE company_id = 1")}
    assert rows["gone"]["job_state"] == "closed"
    assert rows["gone"]["closed_at"] is not None
    assert rows["here"]["job_state"] == "open"
    assert rows["here"]["last_seen_at"] is not None


def test_reconcile_reopens_returning_job(db_conn):
    _insert_job(db_conn, "back", 1, state="closed")
    db_conn.execute("UPDATE jobs SET closed_at='2026-01-02' WHERE id='back'")
    db_conn.commit()
    reconcile_job_states(db_conn, 1, {"back"})
    row = db_conn.execute("SELECT job_state, closed_at FROM jobs WHERE id='back'").fetchone()
    assert row["job_state"] == "open"
    assert row["closed_at"] is None


def test_reconcile_empty_current_closes_all_open(db_conn):
    _insert_job(db_conn, "a", 1)
    _insert_job(db_conn, "b", 1)
    reconcile_job_states(db_conn, 1, set())
    states = {r["id"]: r["job_state"] for r in db_conn.execute(
        "SELECT id, job_state FROM jobs WHERE company_id = 1")}
    assert states == {"a": "closed", "b": "closed"}


def test_reconcile_scoped_to_company(db_conn):
    _insert_job(db_conn, "x", 1)
    _insert_job(db_conn, "x", 2)
    reconcile_job_states(db_conn, 1, set())
    c1 = db_conn.execute("SELECT job_state FROM jobs WHERE id='x' AND company_id=1").fetchone()
    c2 = db_conn.execute("SELECT job_state FROM jobs WHERE id='x' AND company_id=2").fetchone()
    assert c1["job_state"] == "closed"
    assert c2["job_state"] == "open"


def test_get_open_job_ids(db_conn):
    _insert_job(db_conn, "o", 1, state="open")
    _insert_job(db_conn, "c", 1, state="closed")
    assert get_open_job_ids(db_conn, 1) == {"o"}


def _company_and_job(conn, job_id="j1", state="open"):
    from pipeline.db import upsert_company, upsert_jobs
    from models.company import Company
    from models.job import Job
    c = upsert_company(conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    conn.execute(
        "INSERT INTO jobs (id, company_id, title, first_seen_at, job_state) VALUES (?, ?, 'Eng', '2026-01-01', ?)",
        (job_id, c.id, state),
    )
    conn.commit()
    return c.id


def test_create_application_sets_applied(db_conn):
    from pipeline.db import create_application
    cid = _company_and_job(db_conn)
    create_application(db_conn, "j1", cid)
    row = db_conn.execute("SELECT status, applied_at, updated_at FROM applications WHERE job_id='j1'").fetchone()
    assert row["status"] == "applied"
    assert row["applied_at"] is not None
    assert row["updated_at"] is not None


def test_create_application_duplicate_raises(db_conn):
    import sqlite3
    import pytest
    from pipeline.db import create_application
    cid = _company_and_job(db_conn)
    create_application(db_conn, "j1", cid)
    with pytest.raises(sqlite3.IntegrityError):
        create_application(db_conn, "j1", cid)


def test_update_application_status(db_conn):
    from pipeline.db import create_application, update_application_status
    cid = _company_and_job(db_conn)
    create_application(db_conn, "j1", cid)
    affected = update_application_status(db_conn, "j1", cid, "interviewing")
    assert affected == 1
    row = db_conn.execute("SELECT status FROM applications WHERE job_id='j1'").fetchone()
    assert row["status"] == "interviewing"


def test_update_application_status_no_row(db_conn):
    from pipeline.db import update_application_status
    cid = _company_and_job(db_conn)
    assert update_application_status(db_conn, "nope", cid, "offer") == 0


def test_get_applications_joins_and_filters(db_conn):
    from pipeline.db import create_application, update_application_status, get_applications
    cid = _company_and_job(db_conn, job_id="j1", state="closed")
    create_application(db_conn, "j1", cid)
    rows = get_applications(db_conn)
    assert len(rows) == 1
    assert rows[0]["title"] == "Eng"
    assert rows[0]["company_name"] == "Stripe"
    assert rows[0]["job_state"] == "closed"
    assert rows[0]["status"] == "applied"
    update_application_status(db_conn, "j1", cid, "offer")
    assert get_applications(db_conn, status="applied") == []
    assert len(get_applications(db_conn, status="offer")) == 1


def test_job_exists(db_conn):
    from pipeline.db import job_exists
    cid = _company_and_job(db_conn)
    assert job_exists(db_conn, "j1", cid) is True
    assert job_exists(db_conn, "missing", cid) is False


def test_get_company_returns_company_with_tier(db_conn):
    from pipeline.db import get_company
    c = upsert_company(db_conn, Company(name="OpenAI2", slug="openai2",
                                        ats_type="greenhouse", board_token="openai2",
                                        status="active", tier="reach"))
    found = get_company(db_conn, c.id)
    assert found.name == "OpenAI2"
    assert found.tier == "reach"

def test_get_company_missing_returns_none(db_conn):
    from pipeline.db import get_company
    assert get_company(db_conn, 9999) is None
