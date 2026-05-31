import re
import asyncio
import httpx
from pipeline.discovery.clients.greenhouse import GREENHOUSE_URL
from pipeline.discovery.clients.lever import LEVER_URL
from pipeline.discovery.clients.ashby import ASHBY_URL
from pipeline.discovery.clients.workday import probe_workday

_ATS_PROBE_URLS = {
    "greenhouse": GREENHOUSE_URL,
    "lever": LEVER_URL,
    "ashby": ASHBY_URL,
}

def generate_slug_variants(name: str) -> list[str]:
    base = name.lower()
    base = re.sub(r"[,\.&]+", "", base)
    base = re.sub(r"\b(inc|corp|llc|ltd|co)\b", "", base).strip()
    base = re.sub(r"\s+", " ", base).strip()
    variants = {
        base.replace(" ", "-"),
        base.replace(" ", ""),
        base.replace(" ", "_"),
    }
    return list(variants)

async def _probe(client: httpx.AsyncClient, ats_type: str, slug: str) -> tuple[str, str] | None:
    url = _ATS_PROBE_URLS[ats_type].format(token=slug)
    try:
        response = await client.get(url, timeout=10)
        if response.status_code == 200:
            return (ats_type, slug)
    except httpx.RequestError:
        pass
    return None

async def detect_ats(name: str, slug_override: str | None = None) -> tuple[str, str] | None:
    slugs = [slug_override] if slug_override else generate_slug_variants(name)
    async with httpx.AsyncClient() as client:
        tasks = [
            _probe(client, ats_type, slug)
            for slug in slugs
            for ats_type in _ATS_PROBE_URLS
        ]
        results = await asyncio.gather(*tasks)
        for result in results:
            if result is not None:
                return result
        for slug in slugs:
            result = await probe_workday(slug)
            if result is not None:
                return result
    return None
