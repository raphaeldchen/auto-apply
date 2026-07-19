import json
import httpx
from models.job import Job
from pipeline.config import UserConfig, LLMConfig

def score_job(job: Job, user_config: UserConfig, llm_config: LLMConfig) -> tuple[float, str]:
    try:
        response = httpx.post(
            f"{llm_config.base_url}/api/chat",
            json={
                "model": llm_config.model,
                "stream": False,
                "format": "json",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"You are evaluating job postings for a candidate. "
                            f"Desired role: {user_config.desired_role}. "
                            f"Desired level: {user_config.desired_level}."
                        ),
                    },
                    {
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
                    },
                ],
            },
            timeout=60,
        )
        response.raise_for_status()
        data = json.loads(response.json()["message"]["content"])
        return float(data["score"]), str(data["reason"])
    except httpx.HTTPError as e:
        return 0.0, f"API error: {e}"
    except (json.JSONDecodeError, KeyError):
        return 0.0, "failed to parse LLM response"
