from unittest.mock import MagicMock, patch

from pipeline.apply.questions import fetch_greenhouse_questions

GH_JOB_JSON = {
    "id": 123,
    "title": "ML Intern",
    "questions": [
        {
            "label": "First Name",
            "required": True,
            "fields": [{"name": "first_name", "type": "input_text", "values": []}],
        },
        {
            "label": "Resume",
            "required": True,
            "fields": [{"name": "resume", "type": "input_file", "values": []}],
        },
        {
            "label": "Are you authorized to work in the US?",
            "required": True,
            "fields": [{
                "name": "question_9001",
                "type": "multi_value_single_select",
                "values": [{"label": "Yes", "value": 0},
                           {"label": "No", "value": 1}],
            }],
        },
        {
            "label": "Anything else?",
            "required": False,
            "fields": [{"name": "question_9002", "type": "textarea", "values": []}],
        },
    ],
}


def _mock_get(payload):
    response = MagicMock()
    response.json.return_value = payload
    return patch("pipeline.apply.questions.httpx.get", return_value=response)


def test_fetch_parses_questions():
    with _mock_get(GH_JOB_JSON) as mock_get:
        questions = fetch_greenhouse_questions("stripe", "123")
    assert "stripe" in mock_get.call_args.args[0]
    assert "123" in mock_get.call_args.args[0]
    assert "questions=true" in mock_get.call_args.args[0]
    assert [q.label for q in questions] == [
        "First Name", "Resume", "Are you authorized to work in the US?",
        "Anything else?"]
    assert questions[0].name == "first_name"
    assert questions[0].required is True
    assert questions[3].required is False


def test_fetch_extracts_select_options():
    with _mock_get(GH_JOB_JSON):
        questions = fetch_greenhouse_questions("stripe", "123")
    auth = questions[2]
    assert auth.type == "multi_value_single_select"
    assert auth.options == ["Yes", "No"]
    assert questions[0].options == []


def test_fetch_without_questions_key_returns_empty():
    with _mock_get({"id": 123, "title": "ML Intern"}):
        assert fetch_greenhouse_questions("stripe", "123") == []
