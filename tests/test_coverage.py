import pytest

from pipeline.materials.coverage import build_coverage
from pipeline.materials.jd_analyzer import analyze_jd
from pipeline.materials.profile import build_fact_base, load_profile

PROFILE_YAML = """\
personal: {name: A}
skills: [Python, PyTorch, SQL]
experience:
  - id: acme
    company: Acme
    title: DS Intern
    bullets:
      - Built a churn model in PyTorch improving retention 12%
      - Wrote Airflow ETL jobs loading PostgreSQL
education:
  - {school: Cal, degree: BS Computer Science}
"""


@pytest.fixture
def fact_base(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return build_fact_base(load_profile(p))


def _report(fact_base, jd_text):
    analysis = analyze_jd(jd_text, extra_terms=fact_base.skills)
    return build_coverage(analysis, fact_base)


def _row(report, canonical):
    return next(r for r in report.rows if r.canonical == canonical)


def test_skill_in_profile_is_have_with_skills_evidence(fact_base):
    report = _report(fact_base, "Must know Python.")
    row = _row(report, "Python")
    assert row.status == "have"
    assert "skills" in row.evidence


def test_bullet_only_keyword_is_partial_with_bullet_evidence(fact_base):
    report = _report(fact_base, "Experience with Airflow required.")
    row = _row(report, "Airflow")
    assert row.status == "partial"
    assert row.evidence == ["acme.1"]


def test_unknown_keyword_is_lack_with_no_evidence(fact_base):
    report = _report(fact_base, "Rust expertise essential.")
    row = _row(report, "Rust")
    assert row.status == "lack"
    assert row.evidence == []


def test_have_rows_also_collect_bullet_evidence(fact_base):
    report = _report(fact_base, "PyTorch daily.")
    row = _row(report, "PyTorch")
    assert row.status == "have"
    assert row.evidence == ["skills", "acme.0"]


def test_score_weights_by_jd_count(fact_base):
    # Python x2 (have, credit 1), Airflow x1 (partial, 0.5), Rust x1 (lack, 0)
    jd = "Python and python. Airflow pipelines. Rust services."
    report = _report(fact_base, jd)
    assert report.score == pytest.approx((2 * 1.0 + 1 * 0.5 + 1 * 0.0) / 4)


def test_no_keywords_scores_full(fact_base):
    report = _report(fact_base, "We value curiosity and grit.")
    assert report.rows == []
    assert report.score == 1.0
