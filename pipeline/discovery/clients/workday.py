import httpx
from models.job import RawJob

WORKDAY_URL = "https://{subdomain}.myworkdayjobs.com/wday/cxs/{subdomain}/{board}/jobs"
_LIMIT = 20


def fetch_jobs(board_token: str) -> list[RawJob]:
    subdomain, board = board_token.split("/", 1)
    url = WORKDAY_URL.format(subdomain=subdomain, board=board)
    base_url = f"https://{subdomain}.myworkdayjobs.com"
    jobs = []
    offset = 0
    while True:
        response = httpx.post(
            url,
            json={"appliedFacets": {}, "limit": _LIMIT, "offset": offset, "searchText": ""},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        total = data.get("total", 0)
        for posting in data.get("jobPostings", []):
            path = posting["externalPath"]
            jobs.append(
                RawJob(
                    id=path,
                    title=posting["title"],
                    url=base_url + path,
                    location=posting.get("locationsText"),
                    description=None,
                )
            )
        offset += _LIMIT
        if offset >= total:
            break
    return jobs
