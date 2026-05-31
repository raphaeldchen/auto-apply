import pytest


def test_parse_jobs_maps_fields():
    from pipeline.discovery.clients.workday import _parse_jobs
    data = {
        "total": 1,
        "jobPostings": [{
            "externalPath": "/en-US/ExternalCareerSite/job/Remote/ML-Engineer_JR-001",
            "title": "ML Engineer",
            "locationsText": "Remote",
        }],
    }
    jobs = _parse_jobs(data, "https://stripe.wd5.myworkdayjobs.com")
    assert len(jobs) == 1
    assert jobs[0].id == "/en-US/ExternalCareerSite/job/Remote/ML-Engineer_JR-001"
    assert jobs[0].title == "ML Engineer"
    assert jobs[0].url == "https://stripe.wd5.myworkdayjobs.com/en-US/ExternalCareerSite/job/Remote/ML-Engineer_JR-001"
    assert jobs[0].location == "Remote"
    assert jobs[0].description is None


def test_parse_jobs_handles_missing_location():
    from pipeline.discovery.clients.workday import _parse_jobs
    data = {"total": 1, "jobPostings": [{"externalPath": "/path/Job_JR-1", "title": "Engineer"}]}
    jobs = _parse_jobs(data, "https://co.wd5.myworkdayjobs.com")
    assert len(jobs) == 1
    assert jobs[0].location is None


def test_parse_jobs_returns_empty_for_no_postings():
    from pipeline.discovery.clients.workday import _parse_jobs
    jobs = _parse_jobs({"total": 0, "jobPostings": []}, "https://co.wd5.myworkdayjobs.com")
    assert jobs == []


def test_workday_registered_in_client_map():
    from pipeline.discovery.poller import _CLIENT_MAP
    assert "workday" in _CLIENT_MAP


@pytest.mark.integration
def test_fetch_jobs_returns_jobs_from_real_board():
    """Requires: playwright install chromium, live network."""
    from pipeline.discovery.clients.workday import fetch_jobs
    jobs = fetch_jobs("workday.wd5/Workday")
    assert isinstance(jobs, list)
    if jobs:
        assert jobs[0].title
        assert jobs[0].url
        assert jobs[0].id


@pytest.mark.integration
async def test_probe_workday_finds_workday_inc():
    """Requires: playwright install chromium, live network."""
    from pipeline.discovery.clients.workday import probe_workday
    result = await probe_workday("workday")
    assert result is not None
    assert result[0] == "workday"
    assert "workday.wd" in result[1]
