"""Deterministic bullet selection: greedy weighted coverage of JD keywords.

Purely extractive — the plan only references bullet IDs from the fact base;
text is never modified. Selection maximizes JD-keyword coverage under length
constraints, with stable tie-breaks so the same inputs always produce the
same resume.
"""
from dataclasses import dataclass

from models.profile import FactBase
from pipeline.materials.aliases import find_terms
from pipeline.materials.jd_analyzer import JDAnalysis


@dataclass
class SectionPlan:
    section_id: str
    bullet_ids: list[str]  # original narrative order within the section


@dataclass
class SelectionPlan:
    sections: list[SectionPlan]  # profile order: experience, then projects
    skills_order: list[str]  # declared skills, JD-matched first
    bullet_hits: dict[str, list[str]]  # bullet_id -> JD canonicals it evidences
    covered: list[str]  # JD canonicals evidenced by declared skills or selected bullets


def select_bullets(
    analysis: JDAnalysis,
    fact_base: FactBase,
    *,
    max_total: int = 12,
    max_per_section: int = 4,
    min_per_section: int = 1,
) -> SelectionPlan:
    weights = {k.canonical: k.count for k in analysis.keywords}
    extra = tuple(fact_base.skills)

    section_ids = [e.id for e in fact_base.profile.experience] + [
        p.id for p in fact_base.profile.projects
    ]
    by_section: dict[str, list[str]] = {sid: [] for sid in section_ids}
    position: dict[str, int] = {}
    hits: dict[str, list[str]] = {}
    for pos, (bid, bullet) in enumerate(fact_base.bullets.items()):
        by_section[bullet.section_id].append(bid)
        position[bid] = pos
        found = find_terms(bullet.text, extra_terms=extra)
        hits[bid] = sorted(
            (c for c in found if c in weights), key=lambda c: (-weights[c], c)
        )

    selected: set[str] = set()
    covered: set[str] = set()
    count: dict[str, int] = {sid: 0 for sid in section_ids}

    def absolute(bid: str) -> int:
        return sum(weights[c] for c in hits[bid])

    def take(bid: str) -> None:
        selected.add(bid)
        count[fact_base.bullets[bid].section_id] += 1
        covered.update(hits[bid])

    # Phase A: minimum representation — every section keeps its strongest
    # bullet(s) so no experience vanishes from the resume entirely.
    for sid in section_ids:
        ranked = sorted(by_section[sid], key=lambda b: (-absolute(b), position[b]))
        for bid in ranked[:min_per_section]:
            if len(selected) >= max_total:
                break
            take(bid)

    # Phase B: greedy marginal coverage — each pick is the bullet adding the
    # most not-yet-covered JD weight; earliest profile position wins ties.
    while len(selected) < max_total:
        best, best_gain = None, 0
        for bid, bullet in fact_base.bullets.items():
            if bid in selected or count[bullet.section_id] >= max_per_section:
                continue
            gain = sum(weights[c] for c in hits[bid] if c not in covered)
            if gain > best_gain:
                best, best_gain = bid, gain
        if best is None:
            break
        take(best)

    # Phase C: fill remaining budget by absolute score — redundant-but-relevant
    # bullets beat noise, and a small profile stays fully included.
    if len(selected) < max_total:
        remaining = sorted(
            (b for b in fact_base.bullets if b not in selected),
            key=lambda b: (-absolute(b), position[b]),
        )
        for bid in remaining:
            if len(selected) >= max_total:
                break
            if count[fact_base.bullets[bid].section_id] < max_per_section:
                take(bid)

    sections = [
        SectionPlan(sid, [b for b in by_section[sid] if b in selected])
        for sid in section_ids
    ]

    skill_pos = {s: i for i, s in enumerate(fact_base.skills)}
    matched = sorted(
        (s for s in fact_base.skills if s in weights),
        key=lambda s: (-weights[s], skill_pos[s]),
    )
    skills_order = matched + [s for s in fact_base.skills if s not in weights]

    doc_covered = covered | {s for s in fact_base.skills if s in weights}
    covered_list = sorted(doc_covered, key=lambda c: (-weights[c], c))

    return SelectionPlan(
        sections=sections,
        skills_order=skills_order,
        bullet_hits=hits,
        covered=covered_list,
    )
