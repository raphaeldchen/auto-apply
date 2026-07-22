import pytest
import sqlite3
from pathlib import Path

@pytest.fixture
def db_conn():
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(schema)
    conn.commit()
    yield conn
    conn.close()


class _NoCloseConn:
    """Proxy that ignores close() so CLI commands can't tear down the shared
    in-memory fixture between invocations within one test."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


@pytest.fixture
def cli_db(db_conn):
    return _NoCloseConn(db_conn)
