import pytest

from pipeline.materials.profile import load_profile, build_fact_base

PROFILE_YAML = """\
personal:
  name: Raphael Chen
  email: raphael@example.com
  location: San Francisco, CA
skills:
  - Python
  - postgres
  - PyTorch
  - python
experience:
  - id: acme-ds-intern
    company: Acme Corp
    title: Data Science Intern
    start: 2025-06
    end: 2025-09
    bullets:
      - Built a churn model in PyTorch that improved retention by 12%
      - Wrote ETL jobs in Airflow processing 2M rows daily
projects:
  - id: rec-sys
    name: Movie Recommender
    bullets:
      - Trained a collaborative filtering model on 25M ratings
education:
  - school: UC Berkeley
    degree: BS Computer Science
    grad: 2026-05
"""


@pytest.fixture
def profile_path(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return p


def test_load_profile_parses_sections(profile_path):
    profile = load_profile(profile_path)
    assert profile.personal["name"] == "Raphael Chen"
    assert profile.experience[0].company == "Acme Corp"
    assert profile.projects[0].name == "Movie Recommender"
    assert profile.education[0].degree == "BS Computer Science"


def test_load_profile_missing_sections_default_empty(tmp_path):
    p = tmp_path / "min.yaml"
    p.write_text("personal:\n  name: A\nskills: [Python]\n")
    profile = load_profile(p)
    assert profile.experience == []
    assert profile.projects == []
    assert profile.education == []


def test_load_profile_duplicate_section_ids_raise(tmp_path):
    p = tmp_path / "dup.yaml"
    p.write_text(
        "personal: {name: A}\nskills: []\n"
        "experience:\n"
        "  - {id: x, company: A, title: T, bullets: [one]}\n"
        "projects:\n"
        "  - {id: x, name: P, bullets: [two]}\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_profile(p)


def test_load_profile_experience_missing_id_raises(tmp_path):
    p = tmp_path / "noid.yaml"
    p.write_text(
        "personal: {name: A}\nskills: []\n"
        "experience:\n"
        "  - {company: A, title: T, bullets: [one]}\n"
    )
    with pytest.raises(ValueError, match="id"):
        load_profile(p)


def test_fact_base_assigns_stable_bullet_ids(profile_path):
    fb = build_fact_base(load_profile(profile_path))
    assert fb.bullets["acme-ds-intern.0"].text.startswith("Built a churn model")
    assert fb.bullets["acme-ds-intern.1"].text.startswith("Wrote ETL jobs")
    assert fb.bullets["rec-sys.0"].text.startswith("Trained a collaborative")


def test_fact_base_bullets_know_their_section(profile_path):
    fb = build_fact_base(load_profile(profile_path))
    assert fb.bullets["acme-ds-intern.0"].section_id == "acme-ds-intern"


def test_fact_base_normalizes_and_dedupes_skills(profile_path):
    fb = build_fact_base(load_profile(profile_path))
    assert fb.skills == ["Python", "PostgreSQL", "PyTorch"]


def test_fact_base_exposes_degrees(profile_path):
    fb = build_fact_base(load_profile(profile_path))
    assert fb.degrees == ["BS Computer Science"]
