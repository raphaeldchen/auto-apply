from unittest.mock import patch, AsyncMock

import pytest
from click.testing import CliRunner

from main import cli
from pipeline.db import (
    init_db, upsert_company, upsert_jobs, get_applications, update_job_filter_status,
)
from models.company import Company
from models.job import Job
from pipeline.config import Config, UserConfig, FilterConfig, LLMConfig, NotificationsConfig

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
    answers = tmp_path / "answers.yaml"
    answers.write_text(
        'answers:\n'
        '  - {id: work-auth, patterns: ["authorized to work"], answer: "Yes"}\n')
    return Config(
        user=UserConfig(desired_role="DS Intern", desired_level="Intern",
                        resume_path="./resume.pdf", profile_path=str(profile),
                        answers_path=str(answers)),
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


def _seed_db(path):
    conn = init_db(path)
    c = upsert_company(conn, Company(name="Stripe", slug="stripe", ats_type="greenhouse", board_token="stripe", status="active"))
    upsert_jobs(conn, [Job(id="j1", company_id=c.id, title="Eng", url=None, location=None, description=None)])
    conn.close()
    return c


def test_mark_applied_creates_application(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["mark-applied", "j1", str(company.id)])
    assert result.exit_code == 0
    assert "applied" in result.output.lower()
    conn = init_db(path)
    assert len(get_applications(conn)) == 1
    conn.close()


def test_mark_applied_unknown_job_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    result = CliRunner().invoke(cli, ["mark-applied", "missing", str(company.id)])
    assert result.exit_code != 0
    assert "No job" in result.output


def test_mark_applied_duplicate_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["mark-applied", "j1", str(company.id)])
    result = CliRunner().invoke(cli, ["mark-applied", "j1", str(company.id)])
    assert result.exit_code != 0
    assert "Already tracking" in result.output


def test_set_status_updates(tmp_path, monkeypatch):
    path = str(tmp_path / "t.db")
    company = _seed_db(path)
    monkeypatch.setattr("main.DB_PATH", path)
    CliRunner().invoke(cli, ["mark-applied", "j1", str(company.id)])
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
    CliRunner().invoke(cli, ["mark-applied", "j1", str(c.id)])
    result = CliRunner().invoke(cli, ["list-applications"])
    assert result.exit_code == 0
    assert "CLOSED" in result.output


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


def test_tailor_writes_html_and_manifest(cli_db, db_conn, analyze_config, tmp_path):
    import json

    c = _seed_job(db_conn, "Python and Airflow required. Rust a plus.")
    out = tmp_path / "resume.html"
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(out)])
    assert result.exit_code == 0, result.output
    html = out.read_text()
    assert "Wrote Airflow ETL jobs loading PostgreSQL" in html
    manifest = json.loads((tmp_path / "resume.html.manifest.json").read_text())
    assert manifest["job_id"] == "j1"
    assert manifest["selected_bullets"] == ["acme.0"]
    assert "Airflow" in manifest["covered_keywords"]
    assert "Python" in manifest["covered_keywords"]
    assert "Rust" not in manifest["covered_keywords"]
    assert manifest["verbatim"] is True


def test_tailor_pdf_output_calls_renderer(cli_db, db_conn, analyze_config, tmp_path):
    c = _seed_job(db_conn, "Python required.")
    out = tmp_path / "resume.pdf"
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.render_pdf") as mock_pdf:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(out)])
    assert result.exit_code == 0, result.output
    mock_pdf.assert_called_once()
    assert mock_pdf.call_args.args[1] == str(out)


def test_tailor_prints_selection_summary(cli_db, db_conn, analyze_config, tmp_path):
    c = _seed_job(db_conn, "Python and Airflow required. Rust a plus.")
    out = tmp_path / "resume.html"
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(out)])
    assert "verbatim" in result.output.lower()
    assert "2/3" in result.output  # Python + Airflow covered, Rust not


def test_tailor_polish_uses_tier_model_and_applies_rephrases(
        cli_db, db_conn, analyze_config, tmp_path):
    import json
    from pipeline.db import set_company_tier
    from pipeline.materials.rephrase import RephraseResult

    c = _seed_job(db_conn, "Python and Airflow required. Rust a plus.")
    set_company_tier(db_conn, "Stripe", "reach")
    out = tmp_path / "resume.html"
    polished = RephraseResult(
        bullet_id="acme.0",
        original="Wrote Airflow ETL jobs loading PostgreSQL",
        text="Delivered Airflow ETL jobs loading PostgreSQL",
        rephrased=True, reason=None)
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.rephrase_bullets", return_value=[polished]) as mock_rp:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(out), "--polish"])
    assert result.exit_code == 0, result.output
    assert mock_rp.call_args.kwargs["model"] == "claude-opus-4-8"
    assert "Delivered Airflow ETL jobs loading PostgreSQL" in out.read_text()
    manifest = json.loads((tmp_path / "resume.html.manifest.json").read_text())
    assert manifest["verbatim"] is False
    assert manifest["polish"]["model"] == "claude-opus-4-8"
    assert manifest["polish"]["tier"] == "reach"
    assert manifest["polish"]["rephrases"][0]["bullet_id"] == "acme.0"


def test_tailor_polish_fail_closed_keeps_verbatim(
        cli_db, db_conn, analyze_config, tmp_path):
    import json
    from pipeline.materials.rephrase import RephraseResult

    c = _seed_job(db_conn, "Python and Airflow required.")
    out = tmp_path / "resume.html"
    rejected = RephraseResult(
        bullet_id="acme.0",
        original="Wrote Airflow ETL jobs loading PostgreSQL",
        text="Wrote Airflow ETL jobs loading PostgreSQL",
        rephrased=False, reason="numbers must match the original exactly")
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.rephrase_bullets", return_value=[rejected]):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(out), "--polish"])
    assert result.exit_code == 0, result.output
    assert "Wrote Airflow ETL jobs loading PostgreSQL" in out.read_text()
    manifest = json.loads((tmp_path / "resume.html.manifest.json").read_text())
    assert manifest["verbatim"] is True
    assert "numbers must match" in result.output


def test_tailor_without_polish_never_calls_llm(
        cli_db, db_conn, analyze_config, tmp_path):
    c = _seed_job(db_conn, "Python required.")
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.rephrase_bullets") as mock_rp:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(tmp_path / "r.html")])
    assert result.exit_code == 0, result.output
    mock_rp.assert_not_called()


def test_letter_writes_html_and_manifest(cli_db, db_conn, analyze_config, tmp_path):
    import json
    from pipeline.materials.letter import LetterResult

    c = _seed_job(db_conn, "Python and Airflow required.")
    out = tmp_path / "letter.html"
    paragraphs = [
        {"text": "I am excited to apply for the ML Intern role at Stripe.",
         "citations": []},
        {"text": "I wrote Airflow ETL jobs loading PostgreSQL.",
         "citations": ["acme.0"]},
    ]
    ok = LetterResult(ok=True, paragraphs=paragraphs,
                      text="\n\n".join(p["text"] for p in paragraphs),
                      violations=[], attempts=1)
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.generate_letter", return_value=ok) as mock_gl:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["letter", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert mock_gl.call_args.kwargs["model"] == "claude-haiku-4-5"  # standard tier
    assert mock_gl.call_args.kwargs["company_name"] == "Stripe"
    assert mock_gl.call_args.kwargs["job_title"] == "ML Intern"
    assert "Stripe" in mock_gl.call_args.kwargs["other_companies"]
    assert "I wrote Airflow ETL jobs loading PostgreSQL." in out.read_text()
    manifest = json.loads((tmp_path / "letter.html.manifest.json").read_text())
    assert manifest["verified"] is True
    assert manifest["model"] == "claude-haiku-4-5"
    assert manifest["tier"] == "standard"
    assert manifest["attempts"] == 1
    assert manifest["paragraphs"][1]["citations"] == ["acme.0"]


def test_letter_failure_writes_nothing_and_prints_violations(
        cli_db, db_conn, analyze_config, tmp_path):
    from pipeline.materials.letter import LetterResult

    c = _seed_job(db_conn, "Python required.")
    out = tmp_path / "letter.html"
    failed = LetterResult(ok=False, paragraphs=None, text=None,
                          violations=["paragraph 2: number '15%' not in cited facts"],
                          attempts=2)
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.generate_letter", return_value=failed):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["letter", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(out)])
    assert result.exit_code == 0
    assert not out.exists()
    assert not (tmp_path / "letter.html.manifest.json").exists()
    assert "No letter" in result.output
    assert "15%" in result.output


def test_letter_job_without_description_errors(
        cli_db, db_conn, analyze_config, tmp_path):
    c = _seed_job(db_conn, None)
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["letter", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(tmp_path / "l.html")])
    assert "no description" in result.output.lower()


def test_questions_prints_plan_and_stubs(cli_db, db_conn, analyze_config):
    from pipeline.apply.questions import FormQuestion

    c = _seed_job(db_conn, "Python required.")
    qs = [
        FormQuestion(label="First Name", name="first_name",
                     type="input_text", required=True, options=[]),
        FormQuestion(label="Are you authorized to work in the US?", name="q1",
                     type="multi_value_single_select", required=True,
                     options=["Yes", "No"]),
        FormQuestion(label="What is your gender?", name="q2",
                     type="input_text", required=False, options=[]),
        FormQuestion(label="Why do you want to work here?", name="q3",
                     type="textarea", required=True, options=[]),
    ]
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.fetch_greenhouse_questions", return_value=qs) as mock_fq:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["questions", "--job-id", "j1", "--company-id", str(c.id)])
    assert result.exit_code == 0, result.output
    mock_fq.assert_called_once_with("stripe", "j1")
    out = result.output
    assert "4 questions" in out
    assert "First Name" in out
    assert "Yes" in out  # answered from memory
    assert "sensitive" in out.lower() or "⚠" in out
    # exactly one stub — for the unknown question only
    assert out.count("- id:") == 1
    assert "why-do-you-want-to-work-here" in out
    assert "answers.yaml" in out


def test_questions_unsupported_ats_reports(cli_db, db_conn, analyze_config):
    c = upsert_company(db_conn, Company(
        name="Workday Co", slug="wd/Ext", ats_type="workday",
        board_token="wd/Ext", status="active"))
    upsert_jobs(db_conn, [Job(id="w1", company_id=c.id, title="ML Intern",
                              url=None, location=None, description="x")])
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["questions", "--job-id", "w1", "--company-id", str(c.id)])
    assert "not supported" in result.output.lower()
    assert "workday" in result.output.lower()


def test_questions_unknown_job_errors(cli_db, db_conn, analyze_config):
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["questions", "--job-id", "nope", "--company-id", "1"])
    assert "No job" in result.output


def test_apply_fills_form_and_reports(cli_db, db_conn, analyze_config, tmp_path):
    from pipeline.apply.executor import FillReport
    from pipeline.apply.questions import FormQuestion

    c = _seed_job(db_conn, "Python required.")
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-fake")
    qs = [
        FormQuestion(label="First Name", name="first_name",
                     type="input_text", required=True, options=[]),
        FormQuestion(label="Resume", name="resume",
                     type="input_file", required=True, options=[]),
        FormQuestion(label="Why us?", name="q9", type="textarea",
                     required=True, options=[]),
    ]
    report = FillReport(filled=["First Name", "Resume"],
                        skipped=["Why us? — needs_input"], missing=[])
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.fetch_greenhouse_questions", return_value=qs), \
         patch("main.run_application", return_value=report) as mock_run:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["apply", "--job-id", "j1", "--company-id", str(c.id),
                  "--resume", str(resume)])
    assert result.exit_code == 0, result.output
    url = mock_run.call_args.args[0]
    assert "stripe" in url and "j1" in url
    assert mock_run.call_args.args[2] == {"resume": str(resume)}
    out = result.output
    assert "Why us?" in out          # pre-launch warning about the gap
    assert "2 filled" in out
    assert "submit" in out.lower()   # never auto-submitted; user guidance
    mock_run.assert_called_once()


def test_apply_missing_resume_file_warns_and_skips_upload(
        cli_db, db_conn, analyze_config, tmp_path):
    from pipeline.apply.executor import FillReport

    c = _seed_job(db_conn, "Python required.")
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config), \
         patch("main.fetch_greenhouse_questions", return_value=[]), \
         patch("main.run_application", return_value=FillReport()) as mock_run:
        runner = CliRunner()
        result = runner.invoke(
            cli, ["apply", "--job-id", "j1", "--company-id", str(c.id),
                  "--resume", str(tmp_path / "nope.pdf")])
    assert "not found" in result.output.lower()
    assert mock_run.call_args.args[2] == {}


def test_apply_unsupported_ats_reports(cli_db, db_conn, analyze_config):
    c = upsert_company(db_conn, Company(
        name="Lever Co", slug="lv", ats_type="lever",
        board_token="lv", status="active"))
    upsert_jobs(db_conn, [Job(id="l1", company_id=c.id, title="ML Intern",
                              url=None, location=None, description="x")])
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["apply", "--job-id", "l1", "--company-id", str(c.id)])
    assert "not supported" in result.output.lower()


def test_tailor_unknown_job_errors(cli_db, db_conn, analyze_config, tmp_path):
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "nope", "--company-id", "1",
                  "--out", str(tmp_path / "r.html")])
    assert "No job" in result.output


def test_tailor_job_without_description_errors(cli_db, db_conn, analyze_config, tmp_path):
    c = _seed_job(db_conn, None)
    with patch("main.init_db", return_value=cli_db), \
         patch("main.load_config", return_value=analyze_config):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["tailor", "--job-id", "j1", "--company-id", str(c.id),
                  "--out", str(tmp_path / "r.html")])
    assert "no description" in result.output.lower()
