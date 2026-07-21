from models.company import Company
from models.job import Job
from pipeline.db import (
    upsert_company, get_all_companies, get_active_companies,
    get_seen_job_ids, upsert_jobs, update_job_filter_status, get_matched_jobs,
    get_open_job_ids, reconcile_job_states,
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
