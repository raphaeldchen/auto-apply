from unittest.mock import patch, MagicMock, AsyncMock


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


def test_workday_paginates():
    def _posting(n):
        return {
            "externalPath": f"/en-US/Board/job/Remote/Job-{n}_JR-{n:03d}",
            "title": f"Job {n}",
            "locationsText": "Remote",
        }

    page1 = {"total": 22, "jobPostings": [_posting(i) for i in range(20)]}
    page2 = {"total": 22, "jobPostings": [_posting(i) for i in range(20, 22)]}

    with patch(
        "pipeline.discovery.clients.workday.httpx.post",
        side_effect=[_mock_post(page1), _mock_post(page2)],
    ):
        from pipeline.discovery.clients.workday import fetch_jobs
        jobs = fetch_jobs("company.wd5/Board")

    assert len(jobs) == 22
    assert jobs[0].id == "/en-US/Board/job/Remote/Job-0_JR-000"
    assert jobs[21].id == "/en-US/Board/job/Remote/Job-21_JR-021"


def test_workday_registered_in_client_map():
    from pipeline.discovery.poller import _CLIENT_MAP
    assert "workday" in _CLIENT_MAP


async def test_probe_workday_finds_board():
    async def mock_post(url, **kwargs):
        r = MagicMock()
        r.status_code = 200 if "stripe.wd5" in url and "ExternalCareerSite" in url else 404
        return r

    mock_client = AsyncMock()
    mock_client.post = mock_post

    from pipeline.discovery.clients.workday import probe_workday
    result = await probe_workday(mock_client, "stripe")

    assert result is not None
    assert result[0] == "workday"
    assert result[1] == "stripe.wd5/ExternalCareerSite"


async def test_probe_workday_returns_none_when_no_match():
    async def mock_post(url, **kwargs):
        r = MagicMock()
        r.status_code = 404
        return r

    mock_client = AsyncMock()
    mock_client.post = mock_post

    from pipeline.discovery.clients.workday import probe_workday
    result = await probe_workday(mock_client, "unknowncorp")

    assert result is None
