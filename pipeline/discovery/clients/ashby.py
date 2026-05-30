import httpx
from models.job import RawJob

ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"

def fetch_jobs(board_token: str) -> list[RawJob]:
    url = ASHBY_URL.format(token=board_token)
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    return [
        RawJob(id=job["id"], title=job["title"], url=job.get("jobUrl"),
               location=job.get("locationName"), description=job.get("descriptionHtml"))
        for job in data.get("jobs", [])
    ]
