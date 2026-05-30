from unittest.mock import patch, MagicMock
from models.job import RawJob

def _mock_get(status_code, json_data):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock(side_effect=None if status_code == 200 else Exception("HTTP Error"))
    return response

def test_greenhouse_parses_jobs():
    json_data = {"jobs": [{"id": 12345, "title": "Senior Software Engineer", "location": {"name": "San Francisco"}, "absolute_url": "https://boards.greenhouse.io/stripe/jobs/12345", "content": "<p>Description here</p>"}]}
    with patch("pipeline.discovery.clients.greenhouse.httpx.get", return_value=_mock_get(200, json_data)):
        from pipeline.discovery.clients.greenhouse import fetch_jobs
        jobs = fetch_jobs("stripe")
    assert len(jobs) == 1
    assert jobs[0].id == "12345"
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].location == "San Francisco"
    assert jobs[0].url == "https://boards.greenhouse.io/stripe/jobs/12345"
    assert "<p>" in jobs[0].description
