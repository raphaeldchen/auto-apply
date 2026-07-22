import pytest

from pipeline.apply.answers import load_answers
from pipeline.apply.planner import plan_application
from pipeline.apply.questions import FormQuestion
from pipeline.materials.profile import load_profile

PROFILE_YAML = """\
personal:
  name: Ada Example
  email: ada@example.com
  phone: "555-0100"
skills: [Python]
experience:
  - id: acme
    company: Acme
    title: DS Intern
    bullets: [Did things]
"""

ANSWERS_YAML = """\
answers:
  - id: work-auth
    patterns: ["authorized to work"]
    answer: "Yes"
  - id: salary
    patterns: ["salary expectation"]
    answer: ""
"""


@pytest.fixture
def profile(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(PROFILE_YAML)
    return load_profile(p)


@pytest.fixture
def book(tmp_path):
    p = tmp_path / "answers.yaml"
    p.write_text(ANSWERS_YAML)
    return load_answers(p)


def _q(label, name="question_1", type="input_text", required=True, options=None):
    return FormQuestion(label=label, name=name, type=type,
                        required=required, options=options or [])


def _row(plan, label):
    return next(r for r in plan.rows if r.label == label)


def test_profile_fields_filled_automatically(profile, book):
    plan = plan_application(
        [_q("First Name", name="first_name"), _q("Last Name", name="last_name"),
         _q("Email", name="email"), _q("Phone", name="phone")],
        book, profile)
    assert [(r.status, r.answer) for r in plan.rows] == [
        ("auto", "Ada"), ("auto", "Example"),
        ("auto", "ada@example.com"), ("auto", "555-0100")]


def test_file_uploads_marked_attachment(profile, book):
    plan = plan_application(
        [_q("Resume", name="resume", type="input_file")], book, profile)
    assert plan.rows[0].status == "attachment"


def test_memory_answer_applied_when_valid_option(profile, book):
    plan = plan_application(
        [_q("Are you authorized to work in the US?",
            type="multi_value_single_select", options=["Yes", "No"])],
        book, profile)
    row = plan.rows[0]
    assert row.status == "answered"
    assert row.answer == "Yes"
    assert "work-auth" in row.source


def test_memory_answer_not_in_select_options_sent_back(profile, book):
    plan = plan_application(
        [_q("Are you authorized to work in the US?",
            type="multi_value_single_select",
            options=["Definitely", "Absolutely not"])],
        book, profile)
    row = plan.rows[0]
    assert row.status == "needs_input"
    assert "Definitely" in row.note


def test_empty_stored_answer_stays_needs_input(profile, book):
    plan = plan_application([_q("Salary expectations?")], book, profile)
    row = plan.rows[0]
    assert row.status == "needs_input"
    assert "pending" in row.note


def test_sensitive_question_left_for_human(profile, book):
    plan = plan_application([_q("What is your gender?")], book, profile)
    assert plan.rows[0].status == "sensitive"


def test_explicit_answer_overrides_sensitive_default(profile, tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text('answers:\n  - {id: gender, patterns: [gender], '
                 'answer: "Prefer not to say"}\n')
    plan = plan_application([_q("What is your gender?")],
                            load_answers(p), profile)
    row = plan.rows[0]
    assert row.status == "answered"
    assert row.answer == "Prefer not to say"


def test_unknown_question_needs_input(profile, book):
    plan = plan_application([_q("Why do you want to work here?")],
                            book, profile)
    assert plan.rows[0].status == "needs_input"
