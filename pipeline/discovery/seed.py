import yaml

from pipeline.discovery.detector import generate_slug_variants
from pipeline.discovery.clients.workday import probe_workday


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
