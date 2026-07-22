import asyncio
import click
from urllib.parse import urlparse
from pipeline.config import load_config
from pipeline.db import init_db, upsert_company, get_all_companies, get_matched_jobs, set_company_tier, get_job
from pipeline.materials.coverage import build_coverage
from pipeline.materials.jd_analyzer import analyze_jd
from pipeline.materials.profile import build_fact_base, load_profile
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
