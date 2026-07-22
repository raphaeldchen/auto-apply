from dataclasses import dataclass, field


@dataclass
class Bullet:
    id: str
    text: str
    section_id: str


@dataclass
class Experience:
    id: str
    company: str
    title: str
    bullets: list[str]
    start: str | None = None
    end: str | None = None


@dataclass
class Project:
    id: str
    name: str
    bullets: list[str]


@dataclass
class Education:
    school: str
    degree: str
    grad: str | None = None


@dataclass
class Profile:
    personal: dict
    skills: list[str]
    experience: list[Experience] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)


@dataclass
class FactBase:
    """Compiled, ID-addressable view of a Profile.

    Every bullet is addressable as {section_id}.{index}; skills are canonical
    forms (alias-normalized, deduped, order-preserving). This is the only
    source of truth generation may draw from.
    """
    bullets: dict[str, Bullet]
    skills: list[str]
    degrees: list[str]
    profile: Profile
