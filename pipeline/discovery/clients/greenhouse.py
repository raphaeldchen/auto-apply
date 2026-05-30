import httpx
from models.job import RawJob

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"

def fetch_jobs(board_token: str) -> list[RawJob]:
    url = GREENHOUSE_URL.format(token=board_token)
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    return [
        RawJob(id=str(job["id"]), title=job["title"], url=job.get("absolute_url"),
               location=job.get("location", {}).get("name"), description=job.get("content"))
        for job in data.get("jobs", [])
    ]
