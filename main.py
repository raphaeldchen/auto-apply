import asyncio
import click
from pipeline.config import load_config
from pipeline.db import init_db, upsert_company, get_all_companies, get_matched_jobs
from pipeline.discovery.detector import detect_ats
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
@click.option("--name", required=True, help="Company name")
@click.option("--slug", default=None, help="ATS board slug (optional override)")
def add_company(name, slug):
    """Detect and register a company's ATS."""
    conn = init_db(DB_PATH)
    try:
        result = asyncio.run(detect_ats(name, slug))
        if result is None:
            ats_type, board_token, status = None, None, "unsupported"
            click.echo(f"Could not detect ATS for '{name}'. Try --slug <slug> to specify.")
        else:
            ats_type, board_token = result
            status = "active"
            click.echo(f"✓ {name} → {ats_type} (token: {board_token})")
        company = Company(
            name=name,
            slug=board_token or name.lower().replace(" ", "-"),
            ats_type=ats_type,
            board_token=board_token,
            status=status,
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
