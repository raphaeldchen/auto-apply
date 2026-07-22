"""Constrained bullet rephrasing — the LLM half of "LLM proposes, harness
disposes".

One Messages API call proposes rephrases for the selected bullets as JSON;
every candidate must pass verify_rephrase or that bullet falls back to its
verbatim fact-base text. Any transport/parse failure degrades the whole
batch to verbatim — the pipeline can never produce a resume worse than the
extractive stage-2 output, and never an unverified claim.
"""
import json
import re
from dataclasses import dataclass

from models.profile import FactBase
from pipeline.materials.jd_analyzer import JDAnalysis
from pipeline.materials.verify import verify_rephrase

_SYSTEM = (
    "You polish resume bullet points. Rephrase each bullet to read crisply and, "
    "where honest, foreground terms relevant to the job description. Hard rules: "
    "never add, remove, or change any number; never mention a tool, technology, "
    "company, or skill the original bullet does not mention; keep each bullet a "
    "single line of similar length; start with a strong verb. Reply with ONLY a "
    "JSON object mapping each bullet id to its rephrased text."
)

_FENCE = re.compile(r"^```[a-zA-Z]*\n?|\n?```$")


@dataclass
class RephraseResult:
    bullet_id: str
    original: str
    text: str  # verified rephrase, or the verbatim original on any failure
    rephrased: bool
    reason: str | None  # why the fallback happened; None when rephrased


def _verbatim(bullet_id: str, original: str, reason: str) -> RephraseResult:
    return RephraseResult(bullet_id=bullet_id, original=original,
                          text=original, rephrased=False, reason=reason)


def _build_prompt(bullet_ids: list[str], fact_base: FactBase,
                  analysis: JDAnalysis) -> str:
    keywords = ", ".join(k.canonical for k in analysis.keywords) or "(none)"
    payload = {bid: fact_base.bullets[bid].text for bid in bullet_ids}
    return (
        f"Job-description keywords, most frequent first: {keywords}\n\n"
        f"Bullets to polish (id -> text):\n{json.dumps(payload, indent=2)}\n\n"
        "Return only the JSON object of rephrased bullets."
    )


def rephrase_bullets(
    bullet_ids: list[str],
    fact_base: FactBase,
    analysis: JDAnalysis,
    *,
    model: str,
    client=None,
) -> list[RephraseResult]:
    originals = {bid: fact_base.bullets[bid].text for bid in bullet_ids}

    try:
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            system=_SYSTEM,
            messages=[{"role": "user",
                       "content": _build_prompt(bullet_ids, fact_base, analysis)}],
        )
        raw = response.content[0].text
    except Exception as exc:  # fail-closed: transport errors never break tailoring
        reason = f"generation failed: {exc}"
        return [_verbatim(bid, originals[bid], reason) for bid in bullet_ids]

    try:
        proposals = json.loads(_FENCE.sub("", raw.strip()))
        if not isinstance(proposals, dict):
            raise ValueError("expected a JSON object")
    except (ValueError, json.JSONDecodeError):
        reason = "unparseable model response"
        return [_verbatim(bid, originals[bid], reason) for bid in bullet_ids]

    results = []
    for bid in bullet_ids:
        original = originals[bid]
        candidate = proposals.get(bid)
        if not isinstance(candidate, str):
            results.append(_verbatim(bid, original, "no rephrase returned"))
            continue
        ok, reason = verify_rephrase(original, candidate, fact_base)
        if ok:
            results.append(RephraseResult(bullet_id=bid, original=original,
                                          text=candidate.strip(),
                                          rephrased=True, reason=None))
        else:
            results.append(_verbatim(bid, original, reason))
    return results
