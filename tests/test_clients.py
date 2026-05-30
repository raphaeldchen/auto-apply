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

def test_lever_parses_jobs():
    json_data = [{"id": "abc123-def456", "text": "Senior Software Engineer", "categories": {"location": "Remote"}, "hostedUrl": "https://jobs.lever.co/stripe/abc123-def456", "descriptionPlain": "We are looking for a senior engineer..."}]
    with patch("pipeline.discovery.clients.lever.httpx.get", return_value=_mock_get(200, json_data)):
        from pipeline.discovery.clients.lever import fetch_jobs
        jobs = fetch_jobs("stripe")
    assert len(jobs) == 1
    assert jobs[0].id == "abc123-def456"
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "https://jobs.lever.co/stripe/abc123-def456"
    assert "senior engineer" in jobs[0].description

def test_ashby_parses_jobs():
    json_data = {"jobs": [{"id": "xyz-789", "title": "Senior Software Engineer", "locationName": "New York", "jobUrl": "https://jobs.ashbyhq.com/stripe/xyz-789", "descriptionHtml": "<p>We are looking for talent.</p>"}]}
    with patch("pipeline.discovery.clients.ashby.httpx.get", return_value=_mock_get(200, json_data)):
        from pipeline.discovery.clients.ashby import fetch_jobs
        jobs = fetch_jobs("stripe")
    assert len(jobs) == 1
    assert jobs[0].id == "xyz-789"
    assert jobs[0].title == "Senior Software Engineer"
    assert jobs[0].location == "New York"
    assert jobs[0].url == "https://jobs.ashbyhq.com/stripe/xyz-789"
    assert "<p>" in jobs[0].description
