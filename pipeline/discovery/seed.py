import yaml

from pipeline.discovery.detector import generate_slug_variants
from pipeline.discovery.clients.workday import probe_workday
from pipeline.db import get_all_companies, upsert_company
from models.company import Company


def load_seed_companies(path: str) -> list[str]:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not data:
        return []
    return data.get("companies", [])


async def resolve_workday_company(name: str) -> tuple[str, str] | None:
    for slug in generate_slug_variants(name):
        result = await probe_workday(slug)
        if result is not None:
            return result
    return None


async def register_seed_companies(conn, names: list[str]) -> dict[str, list[str]]:
    existing = {c.name for c in get_all_companies(conn)}
    registered: list[str] = []
    skipped: list[str] = []
    missed: list[str] = []
    for name in names:
        if name in existing:
            skipped.append(name)
            continue
        result = await resolve_workday_company(name)
        if result is None:
            missed.append(name)
            continue
        _, board_token = result
        upsert_company(conn, Company(
            name=name, slug=board_token, ats_type="workday",
            board_token=board_token, status="active"))
        registered.append(name)
    return {"registered": registered, "skipped": skipped, "missed": missed}
