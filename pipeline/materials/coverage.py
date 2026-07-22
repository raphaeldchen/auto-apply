"""Coverage matrix: JD requirements × fact base → have / partial / lack.

Pure set operations over the JD analysis and the profile fact base. "have"
means the skill is declared in the profile; "partial" means it only appears
inside experience bullets; "lack" means the profile offers no support for it —
and generation is never allowed to pretend otherwise.
"""
from dataclasses import dataclass, field

from models.profile import FactBase
from pipeline.materials.aliases import find_terms
from pipeline.materials.jd_analyzer import JDAnalysis

_CREDIT = {"have": 1.0, "partial": 0.5, "lack": 0.0}


@dataclass
class CoverageRow:
    canonical: str
    jd_count: int
    status: str  # "have" | "partial" | "lack"
    evidence: list[str] = field(default_factory=list)  # "skills" and/or bullet ids


@dataclass
class CoverageReport:
    rows: list[CoverageRow]
    score: float  # weighted 0..1


def build_coverage(analysis: JDAnalysis, fact_base: FactBase) -> CoverageReport:
    extra = tuple(fact_base.skills)
    bullet_hits: dict[str, list[str]] = {}
    for bullet_id, bullet in fact_base.bullets.items():
        for canonical in find_terms(bullet.text, extra_terms=extra):
            bullet_hits.setdefault(canonical, []).append(bullet_id)

    declared = set(fact_base.skills)
    rows = []
    for hit in analysis.keywords:
        in_skills = hit.canonical in declared
        bullets = bullet_hits.get(hit.canonical, [])
        if in_skills:
            status = "have"
        elif bullets:
            status = "partial"
        else:
            status = "lack"
        evidence = (["skills"] if in_skills else []) + bullets
        rows.append(CoverageRow(canonical=hit.canonical, jd_count=hit.count,
                                status=status, evidence=evidence))

    total_weight = sum(r.jd_count for r in rows)
    if total_weight == 0:
        score = 1.0
    else:
        score = sum(r.jd_count * _CREDIT[r.status] for r in rows) / total_weight
    return CoverageReport(rows=rows, score=score)
