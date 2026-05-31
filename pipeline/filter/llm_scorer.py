import json
import anthropic
from models.job import Job
from pipeline.config import UserConfig

def score_job(job: Job, user_config: UserConfig) -> tuple[float, str]:
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=(
                f"You are evaluating job postings for a candidate. "
                f"Desired role: {user_config.desired_role}. "
                f"Desired level: {user_config.desired_level}."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Title: {job.title}\n"
                    f"Description: {job.description or '(no description)'}\n\n"
                    "Rate relevance 0-10. Criteria:\n"
                    "- Is this the right role type?\n"
                    "- Is this the right seniority level?\n"
                    "- Is this full-time (not contract/intern)?\n\n"
                    'Reply ONLY as JSON: {"score": 8.0, "reason": "one sentence"}'
                ),
            }],
        )
        data = json.loads(response.content[0].text)
        return float(data["score"]), str(data["reason"])
    except anthropic.APIError as e:
        return 0.0, f"API error: {e}"
    except (json.JSONDecodeError, KeyError):
        return 0.0, "failed to parse LLM response"
