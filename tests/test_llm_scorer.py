from unittest.mock import MagicMock, patch
from models.job import Job
from pipeline.config import UserConfig
from pipeline.filter.llm_scorer import score_job

def _user_config():
    return UserConfig(desired_role="Software Engineer", desired_level="Senior", resume_path="./resume.pdf")

def _job():
    return Job(id="1", company_id=1, title="Senior SWE", url=None, location=None, description="We need a senior engineer.")

def _mock_anthropic(response_text: str):
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=response_text)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_message
    return mock_client

def test_score_job_returns_score_and_reason():
    mock_client = _mock_anthropic('{"score": 8.5, "reason": "strong match"}')
    with patch("pipeline.filter.llm_scorer.anthropic.Anthropic", return_value=mock_client):
        score, reason = score_job(_job(), _user_config())
    assert score == 8.5
    assert reason == "strong match"

def test_score_job_sends_desired_role_in_system_prompt():
    mock_client = _mock_anthropic('{"score": 6.0, "reason": "ok match"}')
    with patch("pipeline.filter.llm_scorer.anthropic.Anthropic", return_value=mock_client):
        score_job(_job(), _user_config())
    call_kwargs = mock_client.messages.create.call_args
    system_prompt = call_kwargs.kwargs["system"]
    assert "Software Engineer" in system_prompt
    assert "Senior" in system_prompt

def test_score_job_returns_zero_on_invalid_json():
    mock_client = _mock_anthropic("not valid json")
    with patch("pipeline.filter.llm_scorer.anthropic.Anthropic", return_value=mock_client):
        score, reason = score_job(_job(), _user_config())
    assert score == 0.0
    assert "parse" in reason.lower()
