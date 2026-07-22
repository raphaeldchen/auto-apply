"""Deterministic rephrase verifier — the harness half of "LLM proposes,
harness disposes".

A rephrased bullet is only accepted if it is provably no stronger a claim
than the original: identical numbers (multiset equality, % included), no
skill/lexicon terms the original bullet didn't contain, no new proper
nouns, bounded length, single line. Any failure is reported so the caller
can fall back to the verbatim bullet.
"""
import re
from collections import Counter

from models.profile import FactBase
from pipeline.materials.aliases import find_terms

# 12, 12%, 0.91, 2,000 — the unit of numeric truth on a resume.
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
# Words including internal ./-/' so Node.js and scikit-learn stay one token
# and trailing sentence punctuation is excluded.
_WORD = re.compile(r"[A-Za-z0-9+#]+(?:[.\-'][A-Za-z0-9+#]+)*")


def verify_rephrase(
    original: str, candidate: str, fact_base: FactBase
) -> tuple[bool, str | None]:
    """Return (ok, reason). reason is None iff ok."""
    cand = candidate.strip()
    if not cand:
        return False, "empty rephrase"
    if "\n" in cand:
        return False, "must be a single line"
    if len(cand) > int(len(original) * 1.6) + 20:
        return False, "too long relative to the original"

    if Counter(_NUM.findall(cand)) != Counter(_NUM.findall(original)):
        return False, "numbers must match the original exactly"

    skills = tuple(fact_base.skills)
    original_terms = set(find_terms(original, extra_terms=skills))
    new_terms = sorted(
        t for t in find_terms(cand, extra_terms=skills) if t not in original_terms
    )
    if new_terms:
        return False, f"terms not in the original bullet: {', '.join(new_terms)}"

    allowed = {w.lower() for w in _WORD.findall(original)}
    for m in _WORD.finditer(cand):
        word = m.group()
        if m.start() == 0:
            continue  # bullets start capitalized; the first word may change
        if word[0].isupper() and word.lower() not in allowed:
            return False, f"new proper noun: {word}"

    return True, None
