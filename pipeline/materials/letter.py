"""Cover-letter generation with fact citations.

The model must return JSON paragraphs where every claim cites bullet ids or
declared skills from the fact base. verify_letter checks the result
deterministically; one retry feeds the exact violations back. If the retry
also fails, no letter is produced — a missing letter is recoverable, an
unverified claim in a submitted letter is not.
"""
import json
import re
from dataclasses import dataclass

from models.profile import FactBase
from pipeline.materials.jd_analyzer import JDAnalysis
from pipeline.materials.verify import verify_letter

_SYSTEM = (
    "You write short, specific cover letters. 3-5 paragraphs, 150-300 words "
    "total, plain confident prose — no flattery boilerplate. Mention the exact "
    "job title and company name. Every skill, tool, or number you mention must "
    "come from a fact you cite: list the supporting bullet ids or skill names "
    "in that paragraph's citations. Never mention experience, technologies, or "
    "numbers that are not in the cited facts. Reply with ONLY a JSON object: "
    '{"paragraphs": [{"text": "...", "citations": ["id-or-skill", ...]}, ...]}.'
)

_FENCE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


@dataclass
class LetterResult:
    ok: bool
    paragraphs: list | None
    text: str | None
    violations: list[str]
    attempts: int


def _build_prompt(fact_base: FactBase, analysis: JDAnalysis,
                  company_name: str, job_title: str) -> str:
    bullets = {bid: b.text for bid, b in fact_base.bullets.items()}
    keywords = ", ".join(k.canonical for k in analysis.keywords) or "(none)"
    return (
        f"Write a cover letter for the role '{job_title}' at {company_name}.\n\n"
        f"Job-description keywords, most frequent first: {keywords}\n\n"
        f"Facts you may cite (bullet id -> text):\n{json.dumps(bullets, indent=2)}\n\n"
        f"Declared skills (citable by exact name): {', '.join(fact_base.skills)}\n"
        f"Degrees: {', '.join(fact_base.degrees) or '(none)'}\n\n"
        "Return only the JSON object."
    )


def generate_letter(
    fact_base: FactBase,
    analysis: JDAnalysis,
    *,
    company_name: str,
    job_title: str,
    model: str,
    client=None,
    other_companies: tuple | list = (),
    max_attempts: int = 2,
) -> LetterResult:
    attempt = 0
    violations: list[str] = []
    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        messages = [{"role": "user", "content": _build_prompt(
            fact_base, analysis, company_name, job_title)}]
        for attempt in range(1, max_attempts + 1):
            response = client.messages.create(
                model=model, max_tokens=2000, system=_SYSTEM, messages=messages)
            raw = response.content[0].text
            try:
                data = json.loads(_FENCE.sub("", raw.strip()))
                paragraphs = data.get("paragraphs") if isinstance(data, dict) else None
                if paragraphs is None:
                    violations = ["response missing 'paragraphs'"]
                else:
                    violations = verify_letter(
                        paragraphs, fact_base,
                        company_name=company_name, job_title=job_title,
                        other_companies=other_companies)
            except (ValueError, json.JSONDecodeError):
                paragraphs = None
                violations = ["unparseable model response"]
            if not violations:
                text = "\n\n".join(p["text"] for p in paragraphs)
                return LetterResult(ok=True, paragraphs=paragraphs, text=text,
                                    violations=[], attempts=attempt)
            messages = messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content":
                    "Your letter failed deterministic verification:\n- "
                    + "\n- ".join(violations)
                    + "\nRegenerate the complete JSON object, fixing every "
                      "violation. Cite only the provided bullet ids and skill "
                      "names, and use only numbers present in cited facts."},
            ]
        return LetterResult(ok=False, paragraphs=None, text=None,
                            violations=violations, attempts=attempt)
    except Exception as exc:  # fail-closed: no letter beats an unverified one
        return LetterResult(ok=False, paragraphs=None, text=None,
                            violations=[f"generation failed: {exc}"],
                            attempts=attempt)
