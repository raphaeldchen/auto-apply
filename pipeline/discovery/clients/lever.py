import httpx
from models.job import RawJob

LEVER_URL = "https://api.lever.co/v0/postings/{token}"

def fetch_jobs(board_token: str) -> list[RawJob]:
    url = LEVER_URL.format(token=board_token)
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    return [
        RawJob(id=job["id"], title=job["text"], url=job.get("hostedUrl"),
               location=job.get("categories", {}).get("location"), description=job.get("descriptionPlain"))
        for job in data
    ]
