from pipeline.materials.jd_analyzer import analyze_jd

JD = """\
About the role: our Data Science team ships ML models to production.

Requirements:
- 3+ years of experience with Python (5 years preferred)
- Experience with PyTorch or TensorFlow; Python used daily
- BS or MS in Computer Science or related field
- Familiarity with AWS and Docker
"""


def test_analyze_jd_counts_keywords_sorted_desc():
    analysis = analyze_jd(JD)
    canonicals = [k.canonical for k in analysis.keywords]
    assert canonicals[0] == "Python"  # mentioned twice, everything else once
    assert dict((k.canonical, k.count) for k in analysis.keywords)["Python"] == 2
    assert "PyTorch" in canonicals
    assert "Machine Learning" in canonicals  # via "ML"


def test_analyze_jd_years_experience_takes_floor():
    assert analyze_jd(JD).years_experience == 3


def test_analyze_jd_years_absent_is_none():
    assert analyze_jd("We value curiosity.").years_experience is None


def test_analyze_jd_years_ignores_unrelated_numbers():
    assert analyze_jd("401k matching. 2 years of SQL required.").years_experience == 2


def test_analyze_jd_detects_degrees():
    assert analyze_jd(JD).degrees == ["bachelor", "master"]
    assert analyze_jd("PhD in ML preferred").degrees == ["phd"]
    assert analyze_jd("no formal requirements").degrees == []


def test_analyze_jd_detects_intern_level():
    assert analyze_jd("Machine Learning Intern, Summer 2027 internship").level == "intern"
    assert analyze_jd("Maintain internal tools").level is None


def test_analyze_jd_detects_senior_level():
    assert analyze_jd("Senior Data Scientist role").level == "senior"


def test_analyze_jd_flags_clearance():
    assert analyze_jd("Active TS/SCI security clearance required").clearance_required is True
    assert analyze_jd(JD).clearance_required is False


def test_analyze_jd_flags_sponsorship_mentions():
    assert analyze_jd("We are unable to sponsor visas for this role.").sponsorship_mentioned is True
    assert analyze_jd(JD).sponsorship_mentioned is False


def test_analyze_jd_includes_extra_terms():
    analysis = analyze_jd("Experience with LangGraph a plus.", extra_terms=["LangGraph"])
    assert "LangGraph" in [k.canonical for k in analysis.keywords]
