from unittest.mock import patch, AsyncMock
from click.testing import CliRunner
from main import cli
from pipeline.db import init_db, upsert_company, upsert_jobs, get_applications
from models.company import Company
from models.job import Job


def test_add_company_with_ats_type_skips_detection(db_conn):
    with patch("main.init_db", return_value=db_conn):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add-company", "--name", "Stripe", "--ats-type", "workday", "--slug", "stripe.wd5/ExternalCareerSite"],
        )
    assert result.exit_code == 0
    assert "workday" in result.output
    assert "stripe.wd5/ExternalCareerSite" in result.output


def test_add_company_without_ats_type_calls_detection(db_conn):
    with patch("main.init_db", return_value=db_conn), \
         patch("main.detect_ats", return_value=("greenhouse", "stripe")) as mock_detect:
        runner = CliRunner()
        result = runner.invoke(cli, ["add-company", "--name", "Stripe"])
    mock_detect.assert_called_once()
    assert result.exit_code == 0


def test_add_company_ats_type_without_slug_errors():
    runner = CliRunner()
    result = runner.invoke(cli, ["add-company", "--name", "Stripe", "--ats-type", "workday"])
    assert result.exit_code != 0
    assert "slug" in result.output.lower()


def test_add_company_unknown_ats_type_errors():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["add-company", "--name", "Foo", "--ats-type", "invalid", "--slug", "foo/Bar"],
    )
    assert result.exit_code != 0
    assert "Unknown ATS type" in result.output or "invalid" in result.output


def test_add_companies_reports_results(db_conn):
    fake = {"registered": ["Foo"], "skipped": ["Bar"], "missed": ["Baz"], "errored": ["Qux"]}
    with patch("main.init_db", return_value=db_conn), \
         patch("main.load_seed_companies", return_value=["Foo", "Bar", "Baz", "Qux"]), \
         patch("main.register_seed_companies", new=AsyncMock(return_value=fake)):
        runner = CliRunner()
        result = runner.invoke(cli, ["add-companies", "--seed-file", "x.yaml"])
    assert result.exit_code == 0
    assert "Foo" in result.output
    assert "Bar" in result.output
    assert "Baz" in result.output
    assert "Qux" in result.output
    assert "probe failed" in result.output


def test_add_companies_empty_seed(db_conn):
    with patch("main.init_db", return_value=db_conn), \
         patch("main.load_seed_companies", return_value=[]):
        runner = CliRunner()
        result = runner.invoke(cli, ["add-companies", "--seed-file", "x.yaml"])
    assert result.exit_code == 0
    assert "No companies" in result.output


def _seed_db(path):
    conn = init_db(path)
    c = upsert_company(conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(conn, [Job(id="j1", company_id=c.id, title="Eng", url=None, location=None, description=None)])
    conn.close()
    return c


def test_apply_creates_application(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    assert result.exit_code == 0
    assert "applied" in result.output.lower()
    conn = init_db(path)
    assert len(get_applications(conn)) == 1
    conn.close()


def test_apply_unknown_job_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["apply", "missing", str(company.id)])
    assert result.exit_code != 0
    assert "No job" in result.output


def test_apply_duplicate_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    result = CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    assert result.exit_code != 0
    assert "Already tracking" in result.output


def test_set_status_updates(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["apply", "j1", str(company.id)])
    result = CliRunner().invoke(cli, ["set-status", "j1", str(company.id), "interviewing"])
    assert result.exit_code == 0
    assert "interviewing" in result.output


def test_set_status_invalid_status_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["set-status", "j1", str(company.id), "bogus"])
    assert result.exit_code != 0
    assert "Invalid status" in result.output


def test_set_status_without_application_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["set-status", "j1", str(company.id), "offer"])
    assert result.exit_code != 0
    assert "No tracked application" in result.output


def test_list_applications_marks_closed(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    conn = init_db(path)
    c = upsert_company(conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    conn.execute("INSERT INTO jobs (id, company_id, title, first_seen_at, job_state) VALUES ('j1', ?, 'Eng', '2026-01-01', 'closed')", (c.id,))
    conn.commit()
    conn.close()
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["apply", "j1", str(c.id)])
    result = CliRunner().invoke(cli, ["list-applications"])
    assert result.exit_code == 0
    assert "CLOSED" in result.output
