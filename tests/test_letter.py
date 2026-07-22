import json
from unittest.mock import MagicMock

import pytest

from pipeline.materials.jd_analyzer import analyze_jd
from pipeline.materials.profile import build_fact_base, load_profile
from pipeline.materials.verify import verify_letter

PROFILE_YAML = """\
personal: {name: Ada Example}
skills: [Python, PyTorch]
experience:
  - id: acme
    company: Acme Corp
    title: DS Intern
    bullets:
      - Built a churn model in PyTorch improving retention 12%
      - Wrote Airflow ETL jobs loading PostgreSQL
education:
  - {school: Cal, degree: BS Computer Science}
"""

COMPANY = "Stripe"
TITLE = "ML Intern"

INTRO = {"text": "I am excited to apply for the ML Intern role at Stripe.",
         "citations": []}
BODY = {"text": "At Acme Corp I built a churn model in PyTorch improving retention 12%.",
        "citations": ["acme.0"]}
CLOSE = {"text": "Thank you for your consideration.", "citations": []}


@pytest.fixture
def fact_base(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return build_fact_base(load_profile(p))


def _verify(fact_base, paragraphs, **kwargs):
    kwargs.setdefault("company_name", COMPANY)
    kwargs.setdefault("job_title", TITLE)
    return verify_letter(paragraphs, fact_base, **kwargs)


def test_valid_cited_letter_passes(fact_base):
    assert _verify(fact_base, [INTRO, BODY, CLOSE]) == []


def test_unknown_citation_flagged(fact_base):
    bad = {"text": "I did great things.", "citations": ["ghost.9"]}
    violations = _verify(fact_base, [INTRO, bad, CLOSE])
    assert any("ghost.9" in v for v in violations)


def test_number_not_in_cited_facts_flagged(fact_base):
    bad = {"text": "I built a churn model in PyTorch improving retention 15%.",
           "citations": ["acme.0"]}
    violations = _verify(fact_base, [INTRO, bad, CLOSE])
    assert any("15%" in v for v in violations)


def test_term_not_backed_by_citations_flagged(fact_base):
    bad = {"text": "I am deeply experienced with TensorFlow.", "citations": []}
    violations = _verify(fact_base, [INTRO, bad, CLOSE])
    assert any("TensorFlow" in v for v in violations)


def test_cited_skill_backs_its_mention(fact_base):
    p = {"text": "I write production Python every day.", "citations": ["Python"]}
    assert _verify(fact_base, [INTRO, p, CLOSE]) == []


def test_uncited_skill_mention_flagged(fact_base):
    p = {"text": "I write production Python every day.", "citations": []}
    violations = _verify(fact_base, [INTRO, p, CLOSE])
    assert any("Python" in v for v in violations)


def test_title_terms_allowed_without_citation(fact_base):
    # "ML Intern" title makes Machine Learning fair game to discuss.
    p = {"text": "Machine Learning at Stripe excites me.", "citations": []}
    assert _verify(fact_base, [INTRO, p, CLOSE]) == []


def test_missing_company_name_flagged(fact_base):
    intro = {"text": "I am excited to apply for the ML Intern role.",
             "citations": []}
    violations = _verify(fact_base, [intro, BODY, CLOSE])
    assert any("Stripe" in v for v in violations)


def test_missing_job_title_flagged(fact_base):
    intro = {"text": "I am excited to apply to Stripe.", "citations": []}
    violations = _verify(fact_base, [intro, BODY, CLOSE])
    assert any("ML Intern" in v for v in violations)


def test_other_company_contamination_flagged(fact_base):
    intro = {"text": "I am excited to apply for the ML Intern role at Stripe, "
                     "and I admire Google.", "citations": []}
    violations = _verify(fact_base, [intro, BODY, CLOSE],
                         other_companies=["Google", "Stripe"])
    assert any("Google" in v for v in violations)
    assert not any("Stripe" in v and "Google" not in v for v in violations)


def test_paragraph_count_bounds(fact_base):
    violations = _verify(fact_base, [INTRO])
    assert any("paragraph" in v.lower() for v in violations)


def test_word_cap_enforced(fact_base):
    long_close = {"text": "Thank you so very much indeed. " * 40, "citations": []}
    violations = _verify(fact_base, [INTRO, BODY, long_close], max_words=100)
    assert any("word" in v.lower() for v in violations)


# ---------------------------------------------------------------- generation

from pipeline.materials.letter import generate_letter  # noqa: E402

GOOD_JSON = json.dumps({"paragraphs": [INTRO, BODY, CLOSE]})
BAD_JSON = json.dumps({"paragraphs": [
    INTRO,
    {"text": "I built a churn model in PyTorch improving retention 15%.",
     "citations": ["acme.0"]},
    CLOSE,
]})


@pytest.fixture
def analysis(fact_base):
    return analyze_jd("PyTorch and Python required.", extra_terms=fact_base.skills)


def _resp(text):
    return MagicMock(content=[MagicMock(text=text)])


def _generate(fact_base, analysis, client, **kwargs):
    kwargs.setdefault("company_name", COMPANY)
    kwargs.setdefault("job_title", TITLE)
    kwargs.setdefault("model", "claude-opus-4-8")
    return generate_letter(fact_base, analysis, client=client, **kwargs)


def test_first_attempt_verified_letter(fact_base, analysis):
    client = MagicMock()
    client.messages.create.side_effect = [_resp(GOOD_JSON)]
    result = _generate(fact_base, analysis, client)
    assert result.ok is True
    assert result.attempts == 1
    assert result.violations == []
    assert BODY["text"] in result.text
    assert result.text.count("\n\n") == 2


def test_retry_feeds_violations_back(fact_base, analysis):
    client = MagicMock()
    client.messages.create.side_effect = [_resp(BAD_JSON), _resp(GOOD_JSON)]
    result = _generate(fact_base, analysis, client)
    assert result.ok is True
    assert result.attempts == 2
    retry_messages = client.messages.create.call_args_list[1].kwargs["messages"]
    assert len(retry_messages) >= 3  # prompt, first reply, feedback
    assert "15%" in retry_messages[-1]["content"]


def test_fails_closed_when_retry_also_bad(fact_base, analysis):
    client = MagicMock()
    client.messages.create.side_effect = [_resp(BAD_JSON), _resp(BAD_JSON)]
    result = _generate(fact_base, analysis, client)
    assert result.ok is False
    assert result.text is None
    assert any("15%" in v for v in result.violations)


def test_unparseable_first_response_retried(fact_base, analysis):
    client = MagicMock()
    client.messages.create.side_effect = [
        _resp("Happy to help with that letter!"), _resp(GOOD_JSON)]
    result = _generate(fact_base, analysis, client)
    assert result.ok is True
    assert result.attempts == 2


def test_api_error_fails_closed(fact_base, analysis):
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    result = _generate(fact_base, analysis, client)
    assert result.ok is False
    assert result.text is None
    assert any("generation failed" in v for v in result.violations)


def test_prompt_carries_facts_title_company_and_model(fact_base, analysis):
    client = MagicMock()
    client.messages.create.side_effect = [_resp(GOOD_JSON)]
    _generate(fact_base, analysis, client, model="claude-sonnet-5")
    kwargs = client.messages.create.call_args_list[0].kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    prompt = kwargs["messages"][0]["content"]
    assert "acme.0" in prompt
    assert "Built a churn model in PyTorch improving retention 12%" in prompt
    assert "Python" in prompt
    assert COMPANY in prompt
    assert TITLE in prompt
