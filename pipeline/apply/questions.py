"""Structured application-form questions from ATS APIs.

Greenhouse's public job-board API returns the actual form schema with
?questions=true — no scraping, fully deterministic. Each question carries
its field name, type, and (for selects) the allowed option labels, which
the planner uses to validate stored answers before anything is filled.
"""
from dataclasses import dataclass, field

import httpx

GREENHOUSE_QUESTIONS_URL = (
    "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?questions=true"
)


@dataclass
class FormQuestion:
    label: str
    name: str  # form field name, e.g. "first_name" or "question_9001"
    type: str  # input_text, input_file, textarea, multi_value_single_select, ...
    required: bool
    options: list[str] = field(default_factory=list)  # select option labels


def fetch_greenhouse_questions(board_token: str, job_id: str) -> list[FormQuestion]:
    url = GREENHOUSE_QUESTIONS_URL.format(token=board_token, job_id=job_id)
    response = httpx.get(url, timeout=15)
    response.raise_for_status()
    data = response.json()
    questions = []
    for q in data.get("questions") or []:
        fields = q.get("fields") or [{}]
        first = fields[0]
        questions.append(FormQuestion(
            label=q.get("label", ""),
            name=first.get("name", ""),
            type=first.get("type", ""),
            required=bool(q.get("required")),
            options=[v.get("label", "") for v in first.get("values") or []],
        ))
    return questions
