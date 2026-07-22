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


def verify_letter(
    paragraphs,
    fact_base: FactBase,
    *,
    company_name: str,
    job_title: str,
    other_companies: tuple | list = (),
    max_words: int = 400,
) -> list[str]:
    """Deterministic cover-letter checks. Returns a list of violations
    (empty = verified).

    Every skill/lexicon term and every number in a paragraph must be backed
    by that paragraph's citations (bullet ids or declared skill names), or
    come from the company name / job title / degrees — the only honest
    uncited context. The letter must name the company and title, and must
    not name any other registered company (the mail-merge disaster guard).
    """
    if not isinstance(paragraphs, list):
        return ["response is not a list of paragraphs"]

    violations: list[str] = []
    if not (2 <= len(paragraphs) <= 6):
        violations.append(f"expected 2-6 paragraphs, got {len(paragraphs)}")

    extra = tuple(fact_base.skills)
    skills_set = set(fact_base.skills)
    context = f"{company_name} {job_title}"
    base_terms = set(find_terms(context, extra_terms=extra))
    for degree in fact_base.degrees:
        base_terms |= set(find_terms(degree, extra_terms=extra))
    base_numbers = set(_NUM.findall(context))

    texts: list[str] = []
    for i, para in enumerate(paragraphs, 1):
        if not isinstance(para, dict) or not isinstance(para.get("text"), str) \
                or not para["text"].strip():
            violations.append(f"paragraph {i}: missing text")
            continue
        text = para["text"]
        texts.append(text)
        citations = para.get("citations") or []
        if not isinstance(citations, list):
            violations.append(f"paragraph {i}: citations must be a list")
            citations = []

        allowed_terms = set(base_terms)
        allowed_numbers = set(base_numbers)
        for c in citations:
            if c in fact_base.bullets:
                cited_text = fact_base.bullets[c].text
                allowed_terms |= set(find_terms(cited_text, extra_terms=extra))
                allowed_numbers |= set(_NUM.findall(cited_text))
            elif c in skills_set:
                allowed_terms.add(c)
            else:
                violations.append(f"paragraph {i}: unknown citation '{c}'")

        for term in find_terms(text, extra_terms=extra):
            if term not in allowed_terms:
                violations.append(
                    f"paragraph {i}: term '{term}' not backed by citations")
        for num in set(_NUM.findall(text)):
            if num not in allowed_numbers:
                violations.append(
                    f"paragraph {i}: number '{num}' not in cited facts")

    full_text = "\n\n".join(texts)
    if company_name not in full_text:
        violations.append(f"letter never mentions {company_name}")
    title_core = re.sub(r"\s*\(.*?\)", "", job_title).strip()
    if title_core and title_core.lower() not in full_text.lower():
        violations.append(f"letter never mentions the job title '{title_core}'")
    for other in other_companies:
        if other == company_name or len(other) < 3:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(other)}(?![A-Za-z0-9])",
                     full_text):
            violations.append(f"mentions another registered company: {other}")
    word_count = len(full_text.split())
    if word_count > max_words:
        violations.append(f"too many words: {word_count} > {max_words}")
    return violations
