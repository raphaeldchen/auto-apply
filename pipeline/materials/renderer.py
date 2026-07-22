"""Resume rendering: SelectionPlan + FactBase → HTML → PDF.

Fully deterministic. Bullet text comes verbatim from the fact base by ID;
the template autoescapes everything, so profile content can never inject
markup. PDF generation reuses the Playwright Chromium already required by
the Workday client.
"""
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from models.profile import FactBase
from pipeline.materials.selector import SelectionPlan

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_resume_html(
    fact_base: FactBase,
    plan: SelectionPlan,
    text_overrides: dict[str, str] | None = None,
) -> str:
    """text_overrides maps bullet id → verified rephrase; callers must only
    pass text that has passed verify_rephrase."""
    overrides = text_overrides or {}
    profile = fact_base.profile
    exp_meta = {e.id: e for e in profile.experience}
    proj_meta = {p.id: p for p in profile.projects}

    experience, projects = [], []
    for section in plan.sections:
        if not section.bullet_ids:
            continue
        bullets = [overrides.get(bid, fact_base.bullets[bid].text)
                   for bid in section.bullet_ids]
        if section.section_id in exp_meta:
            e = exp_meta[section.section_id]
            experience.append({
                "company": e.company, "title": e.title,
                "start": e.start, "end": e.end, "bullets": bullets,
            })
        else:
            p = proj_meta[section.section_id]
            projects.append({"name": p.name, "bullets": bullets})

    personal = profile.personal
    return _env.get_template("resume.html.j2").render(
        name=personal.get("name", ""),
        contact=_contact(personal),
        links=_links(personal),
        skills=plan.skills_order,
        experience=experience,
        projects=projects,
        education=profile.education,
    )


def render_letter_html(
    fact_base: FactBase,
    paragraphs: list[dict],
    company_name: str,
    job_title: str,
) -> str:
    """paragraphs are verified letter paragraphs ({"text", "citations"});
    callers must only pass output that verify_letter accepted."""
    personal = fact_base.profile.personal
    return _env.get_template("letter.html.j2").render(
        name=personal.get("name", ""),
        contact=_contact(personal),
        links=_links(personal),
        company_name=company_name,
        job_title=job_title,
        paragraphs=[p["text"] for p in paragraphs],
        date_line=datetime.now().strftime("%B %d, %Y"),
    )


def _contact(personal: dict) -> list[str]:
    return [v for v in (personal.get("email"), personal.get("phone"),
                        personal.get("location")) if v]


def _links(personal: dict) -> list[str]:
    return list((personal.get("links") or {}).values())


def render_pdf(html: str, out_path: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=out_path, format="Letter", print_background=True)
        finally:
            browser.close()
