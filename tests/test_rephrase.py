import json
from unittest.mock import MagicMock

import pytest

from pipeline.materials.jd_analyzer import analyze_jd
from pipeline.materials.profile import build_fact_base, load_profile
from pipeline.materials.rephrase import rephrase_bullets

PROFILE_YAML = """\
personal: {name: A}
skills: [Python, PyTorch]
experience:
  - id: acme
    company: Acme
    title: DS Intern
    bullets:
      - Built a churn model in PyTorch improving retention 12%
      - Wrote Airflow ETL jobs loading PostgreSQL
"""

GOOD = "Developed a churn model in PyTorch, improving retention by 12%"


@pytest.fixture
def fact_base(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return build_fact_base(load_profile(p))


@pytest.fixture
def analysis(fact_base):
    return analyze_jd("PyTorch and Airflow experience required.",
                      extra_terms=fact_base.skills)


def _client_returning(text):
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[MagicMock(text=text)])
    return client


def test_verified_rephrase_accepted(fact_base, analysis):
    client = _client_returning(json.dumps({"acme.0": GOOD}))
    results = rephrase_bullets(["acme.0"], fact_base, analysis,
                               model="claude-opus-4-8", client=client)
    assert results[0].rephrased is True
    assert results[0].text == GOOD
    assert results[0].reason is None


def test_fabricated_number_falls_back_to_verbatim(fact_base, analysis):
    client = _client_returning(json.dumps({"acme.0": GOOD.replace("12%", "15%")}))
    results = rephrase_bullets(["acme.0"], fact_base, analysis,
                               model="claude-opus-4-8", client=client)
    assert results[0].rephrased is False
    assert results[0].text == "Built a churn model in PyTorch improving retention 12%"
    assert "number" in results[0].reason.lower()


def test_missing_id_falls_back(fact_base, analysis):
    client = _client_returning(json.dumps({"acme.0": GOOD}))
    results = rephrase_bullets(["acme.0", "acme.1"], fact_base, analysis,
                               model="claude-opus-4-8", client=client)
    assert results[1].bullet_id == "acme.1"
    assert results[1].rephrased is False
    assert results[1].text == "Wrote Airflow ETL jobs loading PostgreSQL"


def test_unparseable_response_falls_back_for_all(fact_base, analysis):
    client = _client_returning("I'd be happy to help rephrase those bullets!")
    results = rephrase_bullets(["acme.0", "acme.1"], fact_base, analysis,
                               model="claude-opus-4-8", client=client)
    assert all(r.rephrased is False for r in results)
    assert all(r.text == fact_base.bullets[r.bullet_id].text for r in results)


def test_api_error_falls_back_for_all(fact_base, analysis):
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("connection refused")
    results = rephrase_bullets(["acme.0"], fact_base, analysis,
                               model="claude-opus-4-8", client=client)
    assert results[0].rephrased is False
    assert results[0].text == "Built a churn model in PyTorch improving retention 12%"


def test_client_construction_failure_falls_back(fact_base, analysis, monkeypatch):
    # No API key → Anthropic() raises at construction; must still fail closed.
    import anthropic

    def boom(*args, **kwargs):
        raise anthropic.AnthropicError("could not resolve authentication")

    monkeypatch.setattr(anthropic, "Anthropic", boom)
    results = rephrase_bullets(["acme.0"], fact_base, analysis,
                               model="claude-opus-4-8")
    assert results[0].rephrased is False
    assert results[0].text == "Built a churn model in PyTorch improving retention 12%"
    assert "generation failed" in results[0].reason


def test_fenced_json_is_parsed(fact_base, analysis):
    client = _client_returning(f"```json\n{json.dumps({'acme.0': GOOD})}\n```")
    results = rephrase_bullets(["acme.0"], fact_base, analysis,
                               model="claude-opus-4-8", client=client)
    assert results[0].rephrased is True


def test_prompt_carries_bullets_keywords_and_model(fact_base, analysis):
    client = _client_returning("{}")
    rephrase_bullets(["acme.0"], fact_base, analysis,
                     model="claude-sonnet-5", client=client)
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    prompt = kwargs["messages"][0]["content"]
    assert "Built a churn model in PyTorch improving retention 12%" in prompt
    assert "PyTorch" in prompt
    assert "Airflow" in prompt
