from unittest.mock import patch, AsyncMock
from click.testing import CliRunner
from main import cli


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
    fake = {"registered": ["Foo"], "skipped": ["Bar"], "missed": ["Baz"]}
    with patch("main.init_db", return_value=db_conn), \
         patch("main.load_seed_companies", return_value=["Foo", "Bar", "Baz"]), \
         patch("main.register_seed_companies", new=AsyncMock(return_value=fake)):
        runner = CliRunner()
        result = runner.invoke(cli, ["add-companies", "--seed-file", "x.yaml"])
    assert result.exit_code == 0
    assert "Foo" in result.output
    assert "Bar" in result.output
    assert "Baz" in result.output


def test_add_companies_empty_seed(db_conn):
    with patch("main.init_db", return_value=db_conn), \
         patch("main.load_seed_companies", return_value=[]):
        runner = CliRunner()
        result = runner.invoke(cli, ["add-companies", "--seed-file", "x.yaml"])
    assert result.exit_code == 0
    assert "No companies" in result.output
