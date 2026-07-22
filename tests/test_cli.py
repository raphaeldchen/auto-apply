from unittest.mock import patch, AsyncMock

import pytest
from click.testing import CliRunner

from main import cli
from models.company import Company
from models.job import Job
from pipeline.config import Config, UserConfig, FilterConfig, LLMConfig, NotificationsConfig
from pipeline.db import upsert_company, upsert_jobs, update_job_filter_status

PROFILE_YAML = """\
personal: {name: A}
skills: [Python, PyTorch]
experience:
  - id: acme
    company: Acme
    title: DS Intern
    bullets:
      - Wrote Airflow ETL jobs loading PostgreSQL
"""


@pytest.fixture
def analyze_config(tmp_path):
    profile = tmp_path / "profile.yaml"
    profile.write_text(PROFILE_YAML)
    return Config(
        user=UserConfig(desired_role="DS Intern", desired_level="Intern",
                        resume_path="./resume.pdf", profile_path=str(profile)),
        filter=FilterConfig(include_patterns=[], exclude_patterns=[],
                            level_patterns=[], llm_score_threshold=7.0),
        llm=LLMConfig(model="llama3.2"),
        notifications=NotificationsConfig(type="terminal"),
    )


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


def test_add_company_with_tier_stores_tier(cli_db, db_conn):
    with patch("main.init_db", return_value=cli_db):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add-company", "--name", "OpenAI", "--ats-type", "workday",
             "--slug", "openai.wd1/External", "--tier", "reach"],
        )
    assert result.exit_code == 0
    row = db_conn.execute("SELECT tier FROM companies WHERE name = 'OpenAI'").fetchone()
    assert row["tier"] == "reach"


def test_add_company_rejects_invalid_tier():
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["add-company", "--name", "OpenAI", "--ats-type", "workday",
         "--slug", "openai.wd1/External", "--tier", "platinum"],
    )
    assert result.exit_code != 0


def test_set_tier_updates_company(cli_db, db_conn):
    with patch("main.init_db", return_value=cli_db):
        runner = CliRunner()
        runner.invoke(
            cli,
            ["add-company", "--name", "Stripe", "--ats-type", "workday", "--slug", "stripe.wd5/Ext"],
        )
        result = runner.invoke(cli, ["set-tier", "--name", "Stripe", "--tier", "reach"])
    assert result.exit_code == 0
    assert "reach" in result.output
    row = db_conn.execute("SELECT tier FROM companies WHERE name = 'Stripe'").fetchone()
    assert row["tier"] == "reach"


def test_set_tier_unknown_company_reports_error(cli_db, db_conn):
    with patch("main.init_db", return_value=cli_db):
        runner = CliRunner()
        result = runner.invoke(cli, ["set-tier", "--name", "Nope Inc", "--tier", "reach"])
    assert "No company named" in result.output


def _seed_job(db_conn, description, status="matched"):
    c = upsert_company(db_conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse",
                                        board_token="stripe", status="active"))
    upsert_jobs(db_conn, [Job(id="j1", company_id=c.id, title="ML Intern",
                              url=None, location=None, description=description)])
    update_job_filter_status(db_conn, "j1", c.id, status, 8.0, "good")
    return c


def test_analyze_specific_job_prints_coverage(cli_db, db_conn, analyze_config):
    c = _seed_job(db_conn, "Python and Airflow required. Rust a plus.")
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--job-id", "j1", "--company-id", str(c.id)])
    assert result.exit_code == 0
    assert "coverage" in result.output.lower()
    assert "Python" in result.output
    assert "Rust" in result.output


def test_analyze_unknown_job_reports_error(cli_db, db_conn, analyze_config):
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--job-id", "nope", "--company-id", "1"])
    assert "No job" in result.output


def test_analyze_job_without_description_warns(cli_db, db_conn, analyze_config):
    c = _seed_job(db_conn, None)
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze", "--job-id", "j1", "--company-id", str(c.id)])
    assert "no description" in result.output.lower()


def test_analyze_summary_lists_matched_jobs(cli_db, db_conn, analyze_config):
    _seed_job(db_conn, "Python required.")
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(cli, ["analyze"])
    assert result.exit_code == 0
    assert "Stripe" in result.output
    assert "coverage" in result.output.lower()


def test_list_companies_shows_tier(cli_db, db_conn):
    with patch("main.init_db", return_value=cli_db):
        runner = CliRunner()
        runner.invoke(
            cli,
            ["add-company", "--name", "OpenAI", "--ats-type", "workday",
             "--slug", "openai.wd1/External", "--tier", "reach"],
        )
        result = runner.invoke(cli, ["list-companies"])
    assert result.exit_code == 0
    assert "reach" in result.output
