CREATE TABLE IF NOT EXISTS companies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    slug        TEXT    NOT NULL,
    ats_type    TEXT,
    board_token TEXT,
    status      TEXT    NOT NULL DEFAULT 'active',
    detected_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id             TEXT    NOT NULL,
    company_id     INTEGER NOT NULL REFERENCES companies(id),
    title          TEXT    NOT NULL,
    url            TEXT,
    location       TEXT,
    description    TEXT,
    first_seen_at  TEXT    NOT NULL,
    filter_status  TEXT    NOT NULL DEFAULT 'new',
    llm_score      REAL,
    llm_reason     TEXT,
    PRIMARY KEY (id, company_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT    NOT NULL,
    company_id  INTEGER NOT NULL,
    applied_at  TEXT,
    status      TEXT
);
