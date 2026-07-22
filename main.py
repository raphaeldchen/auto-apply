import asyncio
import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import click
from urllib.parse import urlparse
from pipeline.apply.answers import load_answers
from pipeline.apply.executor import run_application
from pipeline.apply.planner import plan_application
from pipeline.apply.questions import fetch_greenhouse_questions
from pipeline.config import load_config
from pipeline.db import init_db, upsert_company, get_all_companies, get_matched_jobs, set_company_tier, get_job, get_company
from pipeline.materials.coverage import build_coverage
from pipeline.materials.jd_analyzer import analyze_jd
from pipeline.materials.profile import build_fact_base, load_profile
from pipeline.materials.letter import generate_letter
from pipeline.materials.renderer import render_letter_html, render_pdf, render_resume_html
from pipeline.materials.rephrase import rephrase_bullets
from pipeline.materials.selector import select_bullets
from pipeline.discovery.detector import detect_ats
from pipeline.discovery.poller import _CLIENT_MAP
from pipeline.discovery.seed import load_seed_companies, register_seed_companies
from pipeline.runner import run_pipeline
from pipeline.notifier import print_digest
from pipeline.scheduler import start_scheduler
from models.company import Company, TIERS

DB_PATH = "auto_apply.db"
CONFIG_PATH = "config.yaml"

@click.group()
def cli():
    pass

@cli.command()
@click.option("--name", default=None, help="Company name (derived from URL if omitted)")
@click.option("--slug", default=None, help="ATS board token or full Workday URL")
@click.option("--ats-type", "ats_type", default=None, help="Skip detection and use this ATS type (e.g. workday)")
@click.option("--tier", type=click.Choice(TIERS), default="standard", show_default=True,
              help="Desirability tier — drives generation model and care budget")
def add_company(name, slug, ats_type, tier):
    """Detect and register a company's ATS."""
    if slug and slug.startswith("https://") and "myworkdayjobs.com" in slug:
        parsed = urlparse(slug)
        subdomain = parsed.hostname.replace(".myworkdayjobs.com", "")
        board = parsed.path.strip("/")
        slug = f"{subdomain}/{board}"
        if not ats_type:
            ats_type = "workday"
        if not name:
            name = subdomain.split(".")[0].capitalize()
    if not name and not slug:
        raise click.UsageError("--name is required when --slug is not a Workday URL")
    if not name:
        raise click.UsageError("--name is required")
    if ats_type and not slug:
        raise click.UsageError("--slug is required when --ats-type is set")
    if ats_type and ats_type not in _CLIENT_MAP:
        raise click.UsageError(f"Unknown ATS type '{ats_type}'. Known types: {', '.join(sorted(_CLIENT_MAP))}")
    conn = init_db(DB_PATH)
    try:
        if ats_type and slug:
            click.echo(f"✓ {name} → {ats_type} (token: {slug})")
            company = Company(
                name=name,
                slug=slug,
                ats_type=ats_type,
                board_token=slug,
                status="active",
                tier=tier,
            )
            upsert_company(conn, company)
        else:
            detected = asyncio.run(detect_ats(name, slug))
            if detected is None:
                click.echo(f"Could not detect ATS for '{name}'. Try --slug <slug> to specify.")
                return
            detected_ats, board_token = detected
            click.echo(f"✓ {name} → {detected_ats} (token: {board_token})")
            company = Company(
                name=name,
                slug=board_token,
                ats_type=detected_ats,
                board_token=board_token,
                status="active",
                tier=tier,
            )
            upsert_company(conn, company)
    finally:
        conn.close()

@cli.command()
@click.option("--seed-file", default="companies_seed.yaml", show_default=True,
              help="YAML file with a 'companies' list")
def add_companies(seed_file):
    """Bulk-register companies from a seed list as Workday boards."""
    names = load_seed_companies(seed_file)
    if not names:
        click.echo(f"No companies found in {seed_file}.")
        return
    conn = init_db(DB_PATH)
    try:
        result = asyncio.run(register_seed_companies(conn, names))
    finally:
        conn.close()
    for name in result["registered"]:
        click.echo(f"✓ {name}")
    for name in result["skipped"]:
        click.echo(f"– {name} (already registered)")
    for name in result["missed"]:
        click.echo(f"✗ {name} — not found on Workday")
    for name in result["errored"]:
        click.echo(f"⚠ {name} — probe failed, could not verify")
    click.echo(
        f"\n{len(result['registered'])} added, "
        f"{len(result['skipped'])} skipped, "
        f"{len(result['missed'])} not found, "
        f"{len(result['errored'])} errored."
    )

@cli.command()
def list_companies():
    """List all registered companies."""
    conn = init_db(DB_PATH)
    try:
        companies = get_all_companies(conn)
        if not companies:
            click.echo("No companies registered. Use `add-company` to add one.")
            return
        for c in companies:
            ats = c.ats_type or "unsupported"
            token = c.board_token or "-"
            click.echo(f"  {c.name:<30} {ats:<12} {c.tier:<10} {token}")
    finally:
        conn.close()

@cli.command()
@click.option("--name", required=True, help="Company name")
@click.option("--tier", type=click.Choice(TIERS), required=True,
              help="Desirability tier — drives generation model and care budget")
def set_tier(name, tier):
    """Set a company's desirability tier."""
    conn = init_db(DB_PATH)
    try:
        if set_company_tier(conn, name, tier):
            click.echo(f"✓ {name} → {tier}")
        else:
            click.echo(f"No company named '{name}'. Use `list-companies` to see registered companies.")
    finally:
        conn.close()

@cli.command()
@click.option("--schedule", is_flag=True, default=False, help="Run on daily schedule instead of once")
def run(schedule):
    """Run the discovery + filter pipeline."""
    config = load_config(CONFIG_PATH)
    if schedule:
        start_scheduler(config, DB_PATH)
    else:
        conn = init_db(DB_PATH)
        try:
            result = run_pipeline(config, conn)
            print_digest(result)
        finally:
            conn.close()

@cli.command()
@click.option("--days", default=7, show_default=True, help="Look back N days")
def show_matches(days):
    """Show matched jobs from the last N days."""
    conn = init_db(DB_PATH)
    try:
        results = get_matched_jobs(conn, days)
        if not results:
            click.echo(f"No matched jobs in the last {days} days.")
            return
        for job, company in results:
            score = f"{job.llm_score:.1f}" if job.llm_score is not None else "N/A"
            click.echo(f"  [{company.name}] {job.title} — score {score}")
            if job.llm_reason:
                click.echo(f"    {job.llm_reason}")
            if job.url:
                click.echo(f"    {job.url}")
    finally:
        conn.close()

_STATUS_MARKS = {"have": "✓", "partial": "~", "lack": "✗"}

@cli.command()
@click.option("--job-id", default=None, help="Analyze one job (requires --company-id)")
@click.option("--company-id", type=int, default=None, help="Company id for --job-id")
@click.option("--days", default=7, show_default=True, help="Summary mode: look back N days")
def analyze(job_id, company_id, days):
    """Coverage report: what each matched JD wants vs. what your profile has."""
    if (job_id is None) != (company_id is None):
        raise click.UsageError("--job-id and --company-id must be used together")
    config = load_config(CONFIG_PATH)
    fact_base = build_fact_base(load_profile(config.user.profile_path))
    conn = init_db(DB_PATH)
    try:
        if job_id is not None:
            job = get_job(conn, job_id, company_id)
            if job is None:
                click.echo(f"No job '{job_id}' for company {company_id}.")
                return
            _print_coverage_detail(job.title, job.description, fact_base)
        else:
            results = get_matched_jobs(conn, days)
            if not results:
                click.echo(f"No matched jobs in the last {days} days.")
                return
            for job, company in results:
                if not job.description:
                    click.echo(f"  [{company.name}] {job.title} — no description stored")
                    continue
                analysis = analyze_jd(job.description, extra_terms=fact_base.skills)
                report = build_coverage(analysis, fact_base)
                have = sum(1 for r in report.rows if r.status == "have")
                click.echo(
                    f"  [{company.name}] {job.title} — coverage {report.score:.0%} "
                    f"(have {have}/{len(report.rows)} keywords)"
                )
    finally:
        conn.close()


@cli.command()
@click.option("--job-id", required=True, help="ATS job id")
@click.option("--company-id", type=int, required=True, help="Company id for --job-id")
@click.option("--out", default="resume.html", show_default=True,
              help="Output path (.html or .pdf); a provenance manifest is written alongside")
@click.option("--polish", is_flag=True, default=False,
              help="Rephrase selected bullets with the company tier's Claude model "
                   "(every rephrase verified against the fact base; fails closed to verbatim)")
def tailor(job_id, company_id, out, polish):
    """Build a tailored resume for one job; all content verified against the profile."""
    config = load_config(CONFIG_PATH)
    fact_base = build_fact_base(load_profile(config.user.profile_path))
    conn = init_db(DB_PATH)
    try:
        job = get_job(conn, job_id, company_id)
        company = get_company(conn, company_id)
    finally:
        conn.close()
    if job is None:
        click.echo(f"No job '{job_id}' for company {company_id}.")
        return
    if not job.description:
        click.echo(f"{job.title}: no description stored — run the pipeline to fetch it.")
        return

    analysis = analyze_jd(job.description, extra_terms=fact_base.skills)
    plan = select_bullets(analysis, fact_base)
    selected = [bid for s in plan.sections for bid in s.bullet_ids]

    overrides = None
    polish_info = None
    if polish:
        tier = company.tier if company else "standard"
        model = config.generation.model_for(tier)
        results = rephrase_bullets(selected, fact_base, analysis, model=model)
        overrides = {r.bullet_id: r.text for r in results if r.rephrased} or None
        polish_info = {"model": model, "tier": tier,
                       "rephrases": [asdict(r) for r in results]}

    html = render_resume_html(fact_base, plan, overrides)
    if out.endswith(".pdf"):
        render_pdf(html, out)
    else:
        Path(out).write_text(html)

    manifest_path = f"{out}.manifest.json"
    Path(manifest_path).write_text(json.dumps({
        "job_id": job_id,
        "company_id": company_id,
        "job_title": job.title,
        "generated_at": datetime.now().isoformat(),
        "selected_bullets": selected,
        "skills_order": plan.skills_order,
        "covered_keywords": plan.covered,
        "jd_keywords": [k.canonical for k in analysis.keywords],
        "verbatim": overrides is None,
        "polish": polish_info,
    }, indent=2))

    click.echo(f"✓ {out} — {len(selected)}/{len(fact_base.bullets)} bullets")
    if polish_info:
        n = sum(1 for r in polish_info["rephrases"] if r["rephrased"])
        click.echo(f"  polish: {n}/{len(selected)} bullets rephrased "
                   f"({polish_info['model']}, {polish_info['tier']} tier)")
        for r in polish_info["rephrases"]:
            if not r["rephrased"]:
                click.echo(f"  ~ {r['bullet_id']} kept verbatim: {r['reason']}")
    else:
        click.echo("  all text verbatim from profile")
    click.echo(f"  covers {len(plan.covered)}/{len(analysis.keywords)} JD keywords: {', '.join(plan.covered) or '—'}")
    click.echo(f"  manifest: {manifest_path}")


@cli.command()
@click.option("--job-id", required=True, help="ATS job id")
@click.option("--company-id", type=int, required=True, help="Company id for --job-id")
@click.option("--out", default="letter.html", show_default=True,
              help="Output path (.html or .pdf); a provenance manifest is written alongside")
def letter(job_id, company_id, out):
    """Generate a fact-cited cover letter (verified; fails closed to no letter)."""
    config = load_config(CONFIG_PATH)
    fact_base = build_fact_base(load_profile(config.user.profile_path))
    conn = init_db(DB_PATH)
    try:
        job = get_job(conn, job_id, company_id)
        company = get_company(conn, company_id)
        all_names = [c.name for c in get_all_companies(conn)]
    finally:
        conn.close()
    if job is None:
        click.echo(f"No job '{job_id}' for company {company_id}.")
        return
    if not job.description:
        click.echo(f"{job.title}: no description stored — run the pipeline to fetch it.")
        return

    tier = company.tier if company else "standard"
    model = config.generation.model_for(tier)
    company_name = company.name if company else ""
    analysis = analyze_jd(job.description, extra_terms=fact_base.skills)
    result = generate_letter(fact_base, analysis,
                             company_name=company_name, job_title=job.title,
                             model=model, other_companies=all_names)
    if not result.ok:
        click.echo(f"✗ No letter produced — verification failed after "
                   f"{result.attempts} attempt(s):")
        for v in result.violations:
            click.echo(f"  - {v}")
        return

    html = render_letter_html(fact_base, result.paragraphs, company_name, job.title)
    if out.endswith(".pdf"):
        render_pdf(html, out)
    else:
        Path(out).write_text(html)

    manifest_path = f"{out}.manifest.json"
    Path(manifest_path).write_text(json.dumps({
        "job_id": job_id,
        "company_id": company_id,
        "job_title": job.title,
        "company_name": company_name,
        "generated_at": datetime.now().isoformat(),
        "model": model,
        "tier": tier,
        "attempts": result.attempts,
        "paragraphs": result.paragraphs,
        "verified": True,
    }, indent=2))

    click.echo(f"✓ {out} — {len(result.paragraphs)} paragraphs, every claim cited "
               f"({model}, {tier} tier, {result.attempts} attempt(s))")
    click.echo(f"  manifest: {manifest_path}")


_PLAN_MARKS = {"auto": "✓", "answered": "✓", "attachment": "•",
               "sensitive": "⚠", "needs_input": "✗"}


@cli.command()
@click.option("--job-id", required=True, help="ATS job id")
@click.option("--company-id", type=int, required=True, help="Company id for --job-id")
def questions(job_id, company_id):
    """Fetch a job's application-form questions and plan answers from memory."""
    config = load_config(CONFIG_PATH)
    profile = load_profile(config.user.profile_path)
    book = load_answers(config.user.answers_path)
    conn = init_db(DB_PATH)
    try:
        job = get_job(conn, job_id, company_id)
        company = get_company(conn, company_id)
    finally:
        conn.close()
    if job is None:
        click.echo(f"No job '{job_id}' for company {company_id}.")
        return
    ats = company.ats_type if company else None
    if ats != "greenhouse":
        click.echo(f"Question fetch not supported for '{ats}' yet (greenhouse only).")
        return

    qs = fetch_greenhouse_questions(company.board_token, job_id)
    if not qs:
        click.echo("No questions returned for this job.")
        return
    plan = plan_application(qs, book, profile)

    click.echo(f"{job.title} @ {company.name} — {len(plan.rows)} questions")
    for row in plan.rows:
        detail = ""
        if row.answer is not None:
            detail = row.answer + (f"  ({row.source})" if row.source else "")
        elif row.note:
            detail = row.note
        req = "" if row.required else "  [optional]"
        click.echo(f"  {_PLAN_MARKS[row.status]} {row.label:<44} {detail}{req}")

    stubs = [r for r in plan.rows if r.status == "needs_input" and r.note is None]
    if stubs:
        click.echo("\nTeach the bot — paste into answers.yaml under `answers:` "
                   "and fill in:")
        for row in stubs:
            slug = re.sub(r"[^a-z0-9]+", "-", row.label.lower()).strip("-")[:40]
            pattern = row.label.lower().rstrip("?.! ").replace('"', "")
            click.echo(f'  - id: {slug}\n    patterns: ["{pattern}"]\n    answer: ""')


@cli.command()
@click.option("--job-id", required=True, help="ATS job id")
@click.option("--company-id", type=int, required=True, help="Company id for --job-id")
@click.option("--resume", "resume_path", default=None,
              help="Resume PDF to upload (default: user.resume_path from config)")
@click.option("--letter", "letter_path", default=None,
              help="Cover letter PDF to upload")
@click.option("--headless", is_flag=True, default=False,
              help="Fill without a visible browser (no review possible; still never submits)")
def apply(job_id, company_id, resume_path, letter_path, headless):
    """Fill a job's application form in a browser. You review and click submit."""
    config = load_config(CONFIG_PATH)
    profile = load_profile(config.user.profile_path)
    book = load_answers(config.user.answers_path)
    conn = init_db(DB_PATH)
    try:
        job = get_job(conn, job_id, company_id)
        company = get_company(conn, company_id)
    finally:
        conn.close()
    if job is None:
        click.echo(f"No job '{job_id}' for company {company_id}.")
        return
    ats = company.ats_type if company else None
    if ats != "greenhouse":
        click.echo(f"Apply not supported for '{ats}' yet (greenhouse only).")
        return

    questions = fetch_greenhouse_questions(company.board_token, job_id)
    plan = plan_application(questions, book, profile)

    gaps = [r for r in plan.rows if r.status in ("needs_input", "sensitive")]
    if gaps:
        click.echo("You'll need to complete these in the browser yourself:")
        for row in gaps:
            click.echo(f"  {_PLAN_MARKS[row.status]} {row.label}"
                       + (f" — {row.note}" if row.note else ""))

    attachments = {}
    resume = resume_path or config.user.resume_path
    if resume:
        if Path(resume).exists():
            attachments["resume"] = str(resume)
        else:
            click.echo(f"⚠ resume file not found: {resume} — skipping upload")
    if letter_path:
        if Path(letter_path).exists():
            attachments["cover_letter"] = str(letter_path)
        else:
            click.echo(f"⚠ letter file not found: {letter_path} — skipping upload")

    url = job.url or f"https://boards.greenhouse.io/{company.board_token}/jobs/{job_id}"
    click.echo(f"Opening {url} …")
    pause = None
    if not headless:
        pause = lambda: click.pause(  # noqa: E731
            "Review the form, complete anything skipped, and click submit "
            "yourself. Press any key here to close the browser...")
    report = run_application(url, plan.rows, attachments,
                             headless=headless, pause=pause)

    click.echo(f"✓ {len(report.filled)} filled, {len(report.skipped)} skipped, "
               f"{len(report.failed)} failed, {len(report.missing)} not found on page")
    for item in report.failed:
        click.echo(f"  ! {item}")
    for label in report.missing:
        click.echo(f"  ? not found on page: {label}")
    click.echo("Nothing was submitted — submission stays in your hands.")


def _print_coverage_detail(title, description, fact_base):
    if not description:
        click.echo(f"{title}: no description stored — run the pipeline to fetch it.")
        return
    analysis = analyze_jd(description, extra_terms=fact_base.skills)
    report = build_coverage(analysis, fact_base)
    click.echo(f"{title} — coverage {report.score:.0%}")
    meta = []
    if analysis.level:
        meta.append(f"level: {analysis.level}")
    if analysis.years_experience is not None:
        meta.append(f"years: {analysis.years_experience}+")
    if analysis.degrees:
        meta.append(f"degrees: {', '.join(analysis.degrees)}")
    if meta:
        click.echo("  " + "   ".join(meta))
    if analysis.clearance_required:
        click.echo("  ⚠ security clearance required")
    if analysis.sponsorship_mentioned:
        click.echo("  ⚠ mentions sponsorship — read the JD before applying")
    for row in report.rows:
        evidence = f"   ({', '.join(row.evidence)})" if row.evidence else ""
        click.echo(f"  {_STATUS_MARKS[row.status]} {row.canonical:<28} ×{row.jd_count}{evidence}")


if __name__ == "__main__":
    cli()
