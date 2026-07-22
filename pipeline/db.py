import sqlite3
from pathlib import Path
from datetime import datetime
from models.company import Company
from models.job import Job


def init_db(db_path: str = "auto_apply.db") -> sqlite3.Connection:
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema)
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    # CREATE IF NOT EXISTS never alters existing tables, so columns added to
    # schema.sql after a DB was created must also be added here.
    company_cols = {row["name"] for row in conn.execute("PRAGMA table_info(companies)")}
    if "tier" not in company_cols:
        conn.execute("ALTER TABLE companies ADD COLUMN tier TEXT NOT NULL DEFAULT 'standard'")


def upsert_company(conn: sqlite3.Connection, company: Company) -> Company:
    conn.execute(
        """INSERT INTO companies (name, slug, ats_type, board_token, status, tier, detected_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name) DO UPDATE SET
             slug=excluded.slug,
             ats_type=excluded.ats_type,
             board_token=excluded.board_token,
             status=excluded.status,
             tier=excluded.tier,
             detected_at=COALESCE(companies.detected_at, excluded.detected_at)""",
        (company.name, company.slug, company.ats_type, company.board_token,
         company.status, company.tier, datetime.now().isoformat()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM companies WHERE name = ?", (company.name,)).fetchone()
    company.id = row["id"]
    return company


def get_all_companies(conn: sqlite3.Connection) -> list[Company]:
    rows = conn.execute("SELECT * FROM companies").fetchall()
    return [_row_to_company(row) for row in rows]


def get_active_companies(conn: sqlite3.Connection) -> list[Company]:
    rows = conn.execute("SELECT * FROM companies WHERE status = 'active'").fetchall()
    return [_row_to_company(row) for row in rows]


def get_seen_job_ids(conn: sqlite3.Connection, company_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT id FROM jobs WHERE company_id = ? AND filter_status != 'kw_filtered'",
        (company_id,),
    ).fetchall()
    return {row["id"] for row in rows}


def upsert_jobs(conn: sqlite3.Connection, jobs: list[Job]) -> None:
    now = datetime.now().isoformat()
    conn.executemany(
        """INSERT INTO jobs (id, company_id, title, url, location, description, first_seen_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id, company_id) DO NOTHING""",
        [(j.id, j.company_id, j.title, j.url, j.location, j.description, now) for j in jobs],
    )
    conn.commit()


def update_job_filter_status(
    conn: sqlite3.Connection,
    job_id: str,
    company_id: int,
    status: str,
    llm_score: float | None = None,
    llm_reason: str | None = None,
    kw_reason: str | None = None,
) -> None:
    conn.execute(
        "UPDATE jobs SET filter_status=?, llm_score=?, llm_reason=?, kw_reason=? WHERE id=? AND company_id=?",
        (status, llm_score, llm_reason, kw_reason, job_id, company_id),
    )
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: str, company_id: int) -> Job | None:
    row = conn.execute(
        """SELECT id as job_id, company_id, title, url, location, description,
                  first_seen_at, filter_status, llm_score, llm_reason, kw_reason
           FROM jobs WHERE id = ? AND company_id = ?""",
        (job_id, company_id),
    ).fetchone()
    return _row_to_job(row) if row else None


def set_company_tier(conn: sqlite3.Connection, name: str, tier: str) -> bool:
    cur = conn.execute("UPDATE companies SET tier = ? WHERE name = ?", (tier, name))
    conn.commit()
    return cur.rowcount > 0


def get_matched_jobs(conn: sqlite3.Connection, days: int = 7) -> list[tuple[Job, Company]]:
    rows = conn.execute(
        """SELECT j.id as job_id, j.company_id, j.title, j.url, j.location, j.description,
                  j.first_seen_at, j.filter_status, j.llm_score, j.llm_reason, j.kw_reason,
                  c.id as company_db_id, c.name as company_name, c.slug as company_slug,
                  c.ats_type, c.board_token, c.status as company_status, c.tier as company_tier,
                  c.detected_at as company_detected_at
           FROM jobs j JOIN companies c ON j.company_id = c.id
           WHERE j.filter_status = 'matched'
             AND j.first_seen_at >= datetime('now', ?)
           ORDER BY j.first_seen_at DESC""",
        (f"-{days} days",),
    ).fetchall()
    return [(_row_to_job(row), _row_to_company_from_join(row)) for row in rows]


def _row_to_company(row: sqlite3.Row) -> Company:
    return Company(
        id=row["id"], name=row["name"], slug=row["slug"],
        ats_type=row["ats_type"], board_token=row["board_token"], status=row["status"],
        tier=row["tier"], detected_at=row["detected_at"],
    )


def _row_to_company_from_join(row: sqlite3.Row) -> Company:
    return Company(
        id=row["company_db_id"], name=row["company_name"], slug=row["company_slug"],
        ats_type=row["ats_type"], board_token=row["board_token"], status=row["company_status"],
        tier=row["company_tier"], detected_at=row["company_detected_at"],
    )


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["job_id"], company_id=row["company_id"], title=row["title"],
        url=row["url"], location=row["location"], description=row["description"],
        first_seen_at=row["first_seen_at"], filter_status=row["filter_status"],
        llm_score=row["llm_score"], llm_reason=row["llm_reason"],
        kw_reason=row["kw_reason"],
    )
