import pytest

from pipeline.materials.profile import build_fact_base, load_profile
from pipeline.materials.verify import verify_rephrase

PROFILE_YAML = """\
personal: {name: A}
skills: [Python, PyTorch]
experience:
  - id: acme
    company: Acme
    title: DS Intern
    bullets:
      - Built a churn model in PyTorch improving retention 12%
"""

ORIGINAL = "Built a churn model in PyTorch improving retention 12%"


@pytest.fixture
def fact_base(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return build_fact_base(load_profile(p))


def test_identical_text_passes(fact_base):
    ok, reason = verify_rephrase(ORIGINAL, ORIGINAL, fact_base)
    assert ok
    assert reason is None


def test_benign_rewording_passes(fact_base):
    candidate = "Developed a churn model in PyTorch, improving retention by 12%"
    ok, reason = verify_rephrase(ORIGINAL, candidate, fact_base)
    assert ok, reason


def test_changed_number_fails(fact_base):
    ok, reason = verify_rephrase(
        ORIGINAL, ORIGINAL.replace("12%", "15%"), fact_base)
    assert not ok
    assert "number" in reason.lower()


def test_added_number_fails(fact_base):
    ok, _ = verify_rephrase(
        ORIGINAL, ORIGINAL + " across 3 teams", fact_base)
    assert not ok


def test_dropped_number_fails(fact_base):
    ok, _ = verify_rephrase(
        ORIGINAL, ORIGINAL.replace(" 12%", ""), fact_base)
    assert not ok


def test_percent_stripped_fails(fact_base):
    ok, _ = verify_rephrase(
        ORIGINAL, ORIGINAL.replace("12%", "12x"), fact_base)
    assert not ok


def test_new_lexicon_entity_fails(fact_base):
    ok, reason = verify_rephrase(
        ORIGINAL, ORIGINAL + " and TensorFlow", fact_base)
    assert not ok
    assert "TensorFlow" in reason


def test_declared_skill_absent_from_original_fails(fact_base):
    # Python is a real skill, but this bullet never mentioned it — injecting
    # it into the bullet would fabricate evidence placement.
    ok, _ = verify_rephrase(
        ORIGINAL, ORIGINAL.replace("in PyTorch", "in Python and PyTorch"),
        fact_base)
    assert not ok


def test_new_capitalized_word_fails(fact_base):
    ok, reason = verify_rephrase(
        ORIGINAL, ORIGINAL + " at Snowflake scale", fact_base)
    assert not ok
    assert "Snowflake" in reason


def test_excessive_length_fails(fact_base):
    candidate = ORIGINAL + " while collaborating closely with wonderful" \
        " cross functional partners to deliver amazing impactful outcomes" \
        " every single sprint without fail and beyond expectations always"
    ok, reason = verify_rephrase(ORIGINAL, candidate, fact_base)
    assert not ok
    assert "long" in reason.lower()


def test_multiline_fails(fact_base):
    ok, _ = verify_rephrase(ORIGINAL, "Built a model\nin PyTorch 12%", fact_base)
    assert not ok


def test_empty_candidate_fails(fact_base):
    ok, _ = verify_rephrase(ORIGINAL, "   ", fact_base)
    assert not ok
