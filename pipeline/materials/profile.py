"""Load profile.yaml and compile it into an ID-addressable FactBase."""
from pathlib import Path

import yaml

from models.profile import Bullet, Education, Experience, FactBase, Profile, Project
from pipeline.materials.aliases import normalize_term


def load_profile(path: str | Path) -> Profile:
    with open(path) as f:
        data = yaml.safe_load(f)

    experience = [
        Experience(
            id=_require(entry, "id", "experience"),
            company=_require(entry, "company", "experience"),
            title=_require(entry, "title", "experience"),
            bullets=[str(b) for b in entry.get("bullets", [])],
            start=_opt_str(entry.get("start")),
            end=_opt_str(entry.get("end")),
        )
        for entry in data.get("experience") or []
    ]
    projects = [
        Project(
            id=_require(entry, "id", "projects"),
            name=_require(entry, "name", "projects"),
            bullets=[str(b) for b in entry.get("bullets", [])],
        )
        for entry in data.get("projects") or []
    ]
    education = [
        Education(
            school=_require(entry, "school", "education"),
            degree=_require(entry, "degree", "education"),
            grad=_opt_str(entry.get("grad")),
        )
        for entry in data.get("education") or []
    ]

    seen_ids: set[str] = set()
    for section_id in [e.id for e in experience] + [p.id for p in projects]:
        if section_id in seen_ids:
            raise ValueError(f"duplicate section id '{section_id}' in profile")
        seen_ids.add(section_id)

    return Profile(
        personal=data.get("personal") or {},
        skills=[str(s) for s in data.get("skills") or []],
        experience=experience,
        projects=projects,
        education=education,
    )


def build_fact_base(profile: Profile) -> FactBase:
    bullets: dict[str, Bullet] = {}
    for section in [*profile.experience, *profile.projects]:
        for i, text in enumerate(section.bullets):
            bullet_id = f"{section.id}.{i}"
            bullets[bullet_id] = Bullet(id=bullet_id, text=text, section_id=section.id)

    skills: list[str] = []
    for raw in profile.skills:
        canonical = normalize_term(raw)
        if canonical not in skills:
            skills.append(canonical)

    return FactBase(
        bullets=bullets,
        skills=skills,
        degrees=[e.degree for e in profile.education],
        profile=profile,
    )


def _require(entry: dict, key: str, section: str) -> str:
    if not entry.get(key):
        raise ValueError(f"every {section} entry needs a '{key}' field (got: {entry})")
    return str(entry[key])


def _opt_str(value) -> str | None:
    return None if value is None else str(value)
