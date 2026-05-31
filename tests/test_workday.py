from unittest.mock import patch, MagicMock


def _mock_post(json_data):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = json_data
    return response


def test_workday_parses_jobs():
    page = {
        "total": 1,
        "jobPostings": [
            {
                "externalPath": "/en-US/ExternalCareerSite/job/Remote/Senior-ML-Engineer_JR-001",
                "title": "Senior ML Engineer",
                "locationsText": "Remote",
            }
        ],
    }
    with patch("pipeline.discovery.clients.workday.httpx.post", return_value=_mock_post(page)):
        from pipeline.discovery.clients.workday import fetch_jobs
        jobs = fetch_jobs("stripe.wd5/ExternalCareerSite")

    assert len(jobs) == 1
    assert jobs[0].id == "/en-US/ExternalCareerSite/job/Remote/Senior-ML-Engineer_JR-001"
    assert jobs[0].title == "Senior ML Engineer"
    assert jobs[0].location == "Remote"
    assert jobs[0].url == "https://stripe.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/Remote/Senior-ML-Engineer_JR-001"
    assert jobs[0].description is None
