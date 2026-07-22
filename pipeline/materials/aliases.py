"""Canonical skill ontology: deterministic term normalization and matching.

The lexicon lives in aliases.yaml (canonical form -> aliases). All matching is
case-insensitive except surfaces listed under `case_sensitive`, which must
appear exactly as written — this keeps short tokens like "R", "Go", and "C"
from matching ordinary prose.
"""
import re
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_ALIASES_PATH = Path(__file__).parent / "aliases.yaml"

# A term match may not butt up against these characters, so "ml" never matches
# inside "html" and "Java" never matches inside "JavaScript". "." is excluded
# from the trailing set so a term at the end of a sentence still matches.
_BOUND_BEFORE = r"(?<![A-Za-z0-9_+#.\-])"
_BOUND_AFTER = r"(?![A-Za-z0-9_+#\-])"


def _term_pattern(surface: str) -> str:
    # Spaces in multi-word terms also match hyphens/newlines ("machine-learning").
    parts = [re.escape(p) for p in surface.split(" ")]
    return _BOUND_BEFORE + r"[\s\-]+".join(parts) + _BOUND_AFTER


@lru_cache(maxsize=4)
def _load(path_str: str) -> tuple[dict[str, list[str]], frozenset[str]]:
    with open(path_str) as f:
        data = yaml.safe_load(f)
    return data["terms"], frozenset(data.get("case_sensitive", []))


def _surfaces(terms: dict[str, list[str]]) -> dict[str, str]:
    """Every matchable surface form -> its canonical."""
    out: dict[str, str] = {}
    for canonical, aliases in terms.items():
        out[canonical] = canonical
        for alias in aliases:
            out[alias] = canonical
    return out


@lru_cache(maxsize=8)
def _matchers(path_str: str, extra_terms: tuple[str, ...]) -> list[tuple[re.Pattern, dict[int, str]]]:
    """Compiled alternation regexes paired with group-index -> canonical maps."""
    terms, case_sensitive = _load(path_str)
    surfaces = _surfaces(terms)
    for term in extra_terms:
        surfaces.setdefault(term, term)

    ci = {s: c for s, c in surfaces.items() if s not in case_sensitive}
    cs = {s: c for s, c in surfaces.items() if s in case_sensitive}

    matchers = []
    for surface_map, flags in ((ci, re.IGNORECASE), (cs, 0)):
        if not surface_map:
            continue
        ordered = sorted(surface_map, key=len, reverse=True)
        pattern = re.compile("|".join(f"({_term_pattern(s)})" for s in ordered), flags)
        group_to_canonical = {i + 1: surface_map[s] for i, s in enumerate(ordered)}
        matchers.append((pattern, group_to_canonical))
    return matchers


def normalize_term(term: str, path: Path | str = DEFAULT_ALIASES_PATH) -> str:
    """Map a term to its canonical form; unknown terms pass through stripped."""
    term = term.strip()
    terms, case_sensitive = _load(str(path))
    surfaces = _surfaces(terms)
    if term in surfaces:
        return surfaces[term]
    lowered = {s.lower(): c for s, c in surfaces.items() if s not in case_sensitive}
    return lowered.get(term.lower(), term)


def find_terms(
    text: str,
    path: Path | str = DEFAULT_ALIASES_PATH,
    extra_terms: tuple[str, ...] | list[str] = (),
) -> dict[str, int]:
    """Count lexicon-term occurrences in text, keyed by canonical form."""
    counts: dict[str, int] = {}
    for pattern, group_to_canonical in _matchers(str(path), tuple(extra_terms)):
        for m in pattern.finditer(text):
            canonical = group_to_canonical[m.lastindex]
            counts[canonical] = counts.get(canonical, 0) + 1
    return counts
