from unittest.mock import MagicMock, patch
from models.job import Job
from pipeline.config import UserConfig, LLMConfig
from pipeline.filter.llm_scorer import score_job

def _user_config():
    return UserConfig(desired_role="Software Engineer", desired_level="Senior", resume_path="./resume.pdf")

def _llm_config():
    return LLMConfig(model="llama3.2", base_url="http://localhost:11434")

def _job():
    return Job(id="1", company_id=1, title="Senior SWE", url=None, location=None, description="We need a senior engineer.")

def _mock_response(content: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": {"content": content}}
    return mock_resp

def test_score_job_returns_score_and_reason():
    with patch("pipeline.filter.llm_scorer.httpx.post", return_value=_mock_response('{"score": 8.5, "reason": "strong match"}')):
        score, reason = score_job(_job(), _user_config(), _llm_config())
    assert score == 8.5
    assert reason == "strong match"

def test_score_job_sends_desired_role_in_system_prompt():
    with patch("pipeline.filter.llm_scorer.httpx.post", return_value=_mock_response('{"score": 6.0, "reason": "ok match"}')) as mock_post:
        score_job(_job(), _user_config(), _llm_config())
    payload = mock_post.call_args.kwargs["json"]
    system_content = payload["messages"][0]["content"]
    assert "Software Engineer" in system_content
    assert "Senior" in system_content

def test_score_job_returns_zero_on_invalid_json():
    with patch("pipeline.filter.llm_scorer.httpx.post", return_value=_mock_response("not valid json")):
        score, reason = score_job(_job(), _user_config(), _llm_config())
    assert score == 0.0
    assert "parse" in reason.lower()
