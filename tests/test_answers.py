import pytest

from pipeline.apply.answers import is_sensitive, load_answers, match_answer

ANSWERS_YAML = """\
answers:
  - id: work-auth
    patterns: ["authorized to work", "legally authorized"]
    answer: "Yes"
  - id: sponsorship
    patterns: ["require sponsorship", "visa sponsorship"]
    answer: "No"
  - id: github
    patterns: ["github"]
    answer: "https://github.com/ada"
  - id: pending-one
    patterns: ["salary expectation"]
    answer: ""
"""


@pytest.fixture
def book(tmp_path):
    p = tmp_path / "answers.yaml"
    p.write_text(ANSWERS_YAML)
    return load_answers(p)


def test_load_answers_parses_entries(book):
    assert [e.id for e in book.entries] == [
        "work-auth", "sponsorship", "github", "pending-one"]
    assert book.entries[0].answer == "Yes"


def test_match_is_case_insensitive_substring(book):
    entry = match_answer("Are you LEGALLY AUTHORIZED to work in the US?", book)
    assert entry.id == "work-auth"


def test_match_first_entry_in_file_order_wins(book):
    # "github" appears in both a github question and nothing else — but a
    # question matching two entries takes the earlier one.
    entry = match_answer(
        "Do you require sponsorship? Also share your GitHub.", book)
    assert entry.id == "sponsorship"


def test_no_match_returns_none(book):
    assert match_answer("Why do you want to work here?", book) is None


def test_missing_file_returns_empty_book(tmp_path):
    book = load_answers(tmp_path / "nope.yaml")
    assert book.entries == []


def test_entry_missing_fields_raises(tmp_path):
    p = tmp_path / "answers.yaml"
    p.write_text("answers:\n  - id: x\n    answer: hi\n")
    with pytest.raises(ValueError, match="patterns"):
        load_answers(p)


def test_duplicate_ids_raise(tmp_path):
    p = tmp_path / "answers.yaml"
    p.write_text(
        "answers:\n"
        "  - {id: a, patterns: [one], answer: '1'}\n"
        "  - {id: a, patterns: [two], answer: '2'}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_answers(p)


@pytest.mark.parametrize("question", [
    "What is your gender?",
    "Please select your race/ethnicity",
    "Veteran status",
    "Do you have a disability?",
    "Sexual orientation (voluntary)",
    "Are you Hispanic or Latino?",
    "Do you need any accommodations during the interview process?",
])
def test_eeo_questions_are_sensitive(question):
    assert is_sensitive(question) is True


@pytest.mark.parametrize("question", [
    "Are you authorized to work in the US?",
    "Why do you want this role?",
    "GitHub profile",
])
def test_normal_questions_are_not_sensitive(question):
    assert is_sensitive(question) is False
