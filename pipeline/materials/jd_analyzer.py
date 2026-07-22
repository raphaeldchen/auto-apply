"""Deterministic job-description analysis — no LLM involved.

Extracts lexicon keywords (via the alias table), an experience floor, degree
mentions, seniority level, and clearance/sponsorship flags. Everything here is
regex and set operations so results are reproducible and testable.
"""
import re
from dataclasses import dataclass, field

from pipeline.materials.aliases import find_terms


@dataclass
class KeywordHit:
    canonical: str
    count: int


@dataclass
class JDAnalysis:
    keywords: list[KeywordHit] = field(default_factory=list)
    years_experience: int | None = None
    degrees: list[str] = field(default_factory=list)
    level: str | None = None
    clearance_required: bool = False
    sponsorship_mentioned: bool = False


_YEARS = re.compile(r"(\d{1,2})\s*(?:\+|-\s*\d{1,2})?\s*(?:years?|yrs?)\b", re.IGNORECASE)

_DEGREES = [
    ("bachelor", re.compile(r"\b(?:bachelor(?:'?s)?|b\.?s\.?c?|b\.?a\.?)\b", re.IGNORECASE)),
    ("master", re.compile(r"\b(?:master(?:'?s)?|m\.?s\.?c?|m\.?eng)\b", re.IGNORECASE)),
    ("phd", re.compile(r"\b(?:ph\.?\s?d\.?|doctorate|doctoral)\b", re.IGNORECASE)),
]

# Checked in order; first hit wins. Word boundaries keep "internal" from
# matching "intern".
_LEVELS = [
    ("intern", re.compile(r"\b(?:intern(?:ship)?s?|co-?op)\b", re.IGNORECASE)),
    ("new_grad", re.compile(r"\b(?:new\s+grad(?:uate)?|entry[\s-]level|university\s+grad(?:uate)?)\b", re.IGNORECASE)),
    ("senior", re.compile(r"\bsenior\b", re.IGNORECASE)),
    ("staff", re.compile(r"\bstaff\b", re.IGNORECASE)),
    ("principal", re.compile(r"\bprincipal\b", re.IGNORECASE)),
]

_CLEARANCE = re.compile(
    r"security\s+clearance|ts/sci|top\s+secret|polygraph", re.IGNORECASE
)
_SPONSORSHIP = re.compile(r"\bsponsor(?:ship)?\b", re.IGNORECASE)


def analyze_jd(text: str, extra_terms: tuple[str, ...] | list[str] = ()) -> JDAnalysis:
    counts = find_terms(text, extra_terms=extra_terms)
    keywords = [
        KeywordHit(canonical=c, count=n)
        for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    year_hits = [int(m.group(1)) for m in _YEARS.finditer(text)]
    years = min(year_hits) if year_hits else None

    degrees = [name for name, pattern in _DEGREES if pattern.search(text)]
    level = next((name for name, pattern in _LEVELS if pattern.search(text)), None)

    return JDAnalysis(
        keywords=keywords,
        years_experience=years,
        degrees=degrees,
        level=level,
        clearance_required=bool(_CLEARANCE.search(text)),
        sponsorship_mentioned=bool(_SPONSORSHIP.search(text)),
    )
