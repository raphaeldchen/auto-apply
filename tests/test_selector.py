import pytest

from pipeline.materials.jd_analyzer import analyze_jd
from pipeline.materials.profile import build_fact_base, load_profile
from pipeline.materials.selector import select_bullets

PROFILE_YAML = """\
personal: {name: A}
skills: [Python, SQL, PyTorch]
experience:
  - id: acme
    company: Acme
    title: DS Intern
    bullets:
      - Built a churn model in PyTorch and Python
      - Wrote Airflow ETL jobs loading PostgreSQL
      - Organized the intern book club
  - id: beta
    company: Beta
    title: ML Intern
    bullets:
      - Deployed models with Docker on AWS
      - Tuned models in Python
projects:
  - id: rec
    name: Recommender
    bullets:
      - Built a recommender in Python with pandas
education:
  - {school: Cal, degree: BS Computer Science}
"""


@pytest.fixture
def fact_base(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return build_fact_base(load_profile(p))


def _select(fact_base, jd_text, **kwargs):
    analysis = analyze_jd(jd_text, extra_terms=fact_base.skills)
    return select_bullets(analysis, fact_base, **kwargs)


def _selected_ids(plan):
    return [bid for section in plan.sections for bid in section.bullet_ids]


def test_all_bullets_kept_when_under_budget(fact_base):
    plan = _select(fact_base, "Python and PyTorch.")
    assert _selected_ids(plan) == [
        "acme.0", "acme.1", "acme.2", "beta.0", "beta.1", "rec.0",
    ]
    assert [s.section_id for s in plan.sections] == ["acme", "beta", "rec"]


def test_selection_respects_total_budget(fact_base):
    plan = _select(fact_base, "Python everywhere.", max_total=2, min_per_section=0)
    assert len(_selected_ids(plan)) == 2


def test_zero_hit_bullet_dropped_first(fact_base):
    # Budget of 5 forces dropping exactly one bullet: the book-club one.
    plan = _select(fact_base, "Python, PyTorch, Airflow, Docker, pandas.",
                   max_total=5)
    ids = _selected_ids(plan)
    assert len(ids) == 5
    assert "acme.2" not in ids


def test_min_per_section_guarantees_representation(fact_base):
    # JD only rewards acme's bullets, but every section keeps one bullet.
    plan = _select(fact_base, "Airflow and PostgreSQL and PyTorch.",
                   max_total=3, min_per_section=1)
    sections = {s.section_id for s in plan.sections if s.bullet_ids}
    assert sections == {"acme", "beta", "rec"}


def test_max_per_section_cap(fact_base):
    plan = _select(fact_base, "Python, PyTorch, Airflow, PostgreSQL.",
                   max_per_section=2, min_per_section=0)
    acme = next(s for s in plan.sections if s.section_id == "acme")
    assert len(acme.bullet_ids) == 2


def test_marginal_gain_beats_redundant_absolute(fact_base):
    # Python x3, Airflow x1. beta.1 (Python only) is redundant once acme.0
    # covers Python, so the second slot goes to acme.1 for Airflow.
    jd = "Python. Python. Python. Airflow."
    plan = _select(fact_base, jd, max_total=2, min_per_section=0)
    assert set(_selected_ids(plan)) == {"acme.0", "acme.1"}


def test_within_section_order_preserved(fact_base):
    # Airflow (weight 2) makes acme.1 the greedy first pick, but the plan
    # must still list acme.0 before acme.1 (original narrative order).
    plan = _select(fact_base, "Airflow. Airflow. Python.",
                   max_total=2, min_per_section=0)
    acme = next(s for s in plan.sections if s.section_id == "acme")
    assert acme.bullet_ids == ["acme.0", "acme.1"]


def test_skills_order_jd_matched_first(fact_base):
    plan = _select(fact_base, "PyTorch and PyTorch, plus SQL.")
    assert plan.skills_order == ["PyTorch", "SQL", "Python"]


def test_skills_order_unmatched_keeps_profile_order(fact_base):
    plan = _select(fact_base, "We value curiosity.")
    assert plan.skills_order == ["Python", "SQL", "PyTorch"]


def test_covered_lists_document_evidence_only(fact_base):
    # Rust is in the JD but nowhere in the profile: never claimed as covered.
    plan = _select(fact_base, "Python, Airflow, Rust.")
    assert set(plan.covered) == {"Python", "Airflow"}


def test_bullet_hits_limited_to_jd_keywords(fact_base):
    # acme.1 contains Airflow and PostgreSQL, but only Airflow is in this JD.
    plan = _select(fact_base, "Airflow required.")
    assert plan.bullet_hits["acme.1"] == ["Airflow"]


def test_selection_is_deterministic(fact_base):
    jd = "Python, PyTorch, Airflow, Docker, pandas."
    assert _select(fact_base, jd, max_total=4) == _select(fact_base, jd, max_total=4)
