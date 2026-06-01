import asyncio
import click
from urllib.parse import urlparse
from pipeline.config import load_config
from pipeline.db import init_db, upsert_company, get_all_companies, get_matched_jobs
from pipeline.discovery.detector import detect_ats
from pipeline.discovery.poller import _CLIENT_MAP
from pipeline.runner import run_pipeline
from pipeline.notifier import print_digest
from pipeline.scheduler import start_scheduler
from models.company import Company

DB_PATH = "auto_apply.db"
CONFIG_PATH = "config.yaml"

@click.group()
def cli():
    pass

@cli.command()
@click.option("--name", default=None, help="Company name (derived from URL if omitted)")
@click.option("--slug", default=None, help="ATS board token or full Workday URL")
@click.option("--ats-type", "ats_type", default=None, help="Skip detection and use this ATS type (e.g. workday)")
def add_company(name, slug, ats_type):
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
            )
            upsert_company(conn, company)
    finally:
        conn.close()

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
            click.echo(f"  {c.name:<30} {ats:<12} {token}")
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

if __name__ == "__main__":
    cli()
