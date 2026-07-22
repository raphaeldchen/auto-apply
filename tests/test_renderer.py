from unittest.mock import MagicMock, patch

import pytest

from pipeline.materials.jd_analyzer import analyze_jd
from pipeline.materials.profile import build_fact_base, load_profile
from pipeline.materials.renderer import render_pdf, render_resume_html
from pipeline.materials.selector import SectionPlan, SelectionPlan, select_bullets

PROFILE_YAML = """\
personal:
  name: Ada Example
  email: ada@example.com
  phone: "555-0100"
  location: Berkeley, CA
  links:
    github: https://github.com/ada
skills: [Python, SQL, PyTorch]
experience:
  - id: acme
    company: Acme Corp
    title: DS Intern
    start: 2025-06
    end: 2025-09
    bullets:
      - Built a churn model in PyTorch and Python
      - Organized the intern book club
projects:
  - id: rec
    name: Recommender
    bullets:
      - Built a recommender in Python with pandas
education:
  - {school: Cal, degree: BS Computer Science, grad: 2026-05}
"""


@pytest.fixture
def fact_base(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return build_fact_base(load_profile(p))


@pytest.fixture
def plan(fact_base):
    analysis = analyze_jd("PyTorch and Python.", extra_terms=fact_base.skills)
    return select_bullets(analysis, fact_base)


def test_html_contains_identity_and_contact(fact_base, plan):
    html = render_resume_html(fact_base, plan)
    assert "Ada Example" in html
    assert "ada@example.com" in html
    assert "555-0100" in html
    assert "https://github.com/ada" in html


def test_html_renders_bullets_verbatim(fact_base, plan):
    html = render_resume_html(fact_base, plan)
    assert "Built a churn model in PyTorch and Python" in html
    assert "Built a recommender in Python with pandas" in html


def test_html_omits_unselected_bullets(fact_base, plan):
    trimmed = SelectionPlan(
        sections=[SectionPlan("acme", ["acme.0"]), SectionPlan("rec", ["rec.0"])],
        skills_order=plan.skills_order,
        bullet_hits=plan.bullet_hits,
        covered=plan.covered,
    )
    html = render_resume_html(fact_base, trimmed)
    assert "book club" not in html


def test_html_omits_sections_with_no_selected_bullets(fact_base, plan):
    trimmed = SelectionPlan(
        sections=[SectionPlan("acme", ["acme.0"]), SectionPlan("rec", [])],
        skills_order=plan.skills_order,
        bullet_hits=plan.bullet_hits,
        covered=plan.covered,
    )
    html = render_resume_html(fact_base, trimmed)
    assert "Recommender" not in html


def test_html_lists_skills_in_plan_order(fact_base, plan):
    # JD weights PyTorch/Python equally; plan puts matched skills first.
    html = render_resume_html(fact_base, plan)
    assert html.index("PyTorch") < html.index("SQL")


def test_html_includes_experience_meta_and_education(fact_base, plan):
    html = render_resume_html(fact_base, plan)
    assert "Acme Corp" in html
    assert "DS Intern" in html
    assert "Cal" in html
    assert "BS Computer Science" in html


def test_html_escapes_markup_in_profile_text(tmp_path):
    yaml_text = PROFILE_YAML.replace(
        "Organized the intern book club",
        "Improved <script>alert(1)</script> throughput",
    )
    p = tmp_path / "profile.yaml"
    p.write_text(yaml_text)
    fb = build_fact_base(load_profile(p))
    analysis = analyze_jd("Python.", extra_terms=fb.skills)
    html = render_resume_html(fb, select_bullets(analysis, fb))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_text_overrides_replace_bullet_text(fact_base, plan):
    html = render_resume_html(
        fact_base, plan,
        text_overrides={"acme.0": "Engineered a churn model in PyTorch and Python"})
    assert "Engineered a churn model in PyTorch and Python" in html
    assert "Built a churn model in PyTorch and Python" not in html
    # untouched bullets still render verbatim
    assert "Built a recommender in Python with pandas" in html


def test_render_pdf_drives_chromium_with_html(tmp_path):
    out = tmp_path / "resume.pdf"
    with patch("pipeline.materials.renderer.sync_playwright") as sp:
        page = MagicMock()
        browser = MagicMock()
        browser.new_page.return_value = page
        sp.return_value.__enter__.return_value.chromium.launch.return_value = browser
        render_pdf("<p>hi</p>", str(out))
    page.set_content.assert_called_once()
    assert page.set_content.call_args.args[0] == "<p>hi</p>"
    assert page.pdf.call_args.kwargs["path"] == str(out)
    browser.close.assert_called_once()


@pytest.mark.integration
def test_render_pdf_produces_real_pdf(fact_base, plan, tmp_path):
    out = tmp_path / "resume.pdf"
    render_pdf(render_resume_html(fact_base, plan), str(out))
    assert out.read_bytes()[:5] == b"%PDF-"
