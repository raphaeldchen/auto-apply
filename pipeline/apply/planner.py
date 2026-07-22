"""Application planner: form questions × answer memory × profile → a typed
fill plan.

Deterministic resolution order per question:
  1. standard profile fields (name/email/phone) → auto
  2. file uploads → attachment (resume/letter supplied at apply time)
  3. answer memory → answered, but only if the stored answer is non-empty
     and, for selects, exactly matches one of the form's options
  4. EEO/self-identification → sensitive (left for the human)
  5. otherwise → needs_input

Nothing is ever guessed: an unmatched question is surfaced, not filled.
"""
from dataclasses import dataclass, field

from models.profile import Profile
from pipeline.apply.answers import AnswerBook, is_sensitive, match_answer
from pipeline.apply.questions import FormQuestion


@dataclass
class PlanRow:
    label: str
    name: str
    required: bool
    status: str  # auto | attachment | answered | sensitive | needs_input
    type: str = ""  # form field type, for the executor (fill vs select)
    options: list[str] = field(default_factory=list)
    answer: str | None = None
    source: str | None = None
    note: str | None = None


@dataclass
class ApplicationPlan:
    rows: list[PlanRow] = field(default_factory=list)


def _profile_values(profile: Profile) -> dict[str, str]:
    personal = profile.personal
    name = str(personal.get("name") or "").strip()
    first, _, last = name.rpartition(" ")
    if not first:  # single-word name
        first, last = last, ""
    return {
        "first_name": first,
        "last_name": last,
        "email": str(personal.get("email") or ""),
        "phone": str(personal.get("phone") or ""),
    }


def plan_application(
    questions: list[FormQuestion],
    book: AnswerBook,
    profile: Profile,
) -> ApplicationPlan:
    values = _profile_values(profile)
    rows = []
    for q in questions:
        rows.append(_plan_question(q, book, values))
    return ApplicationPlan(rows=rows)


def _plan_question(q: FormQuestion, book: AnswerBook,
                   values: dict[str, str]) -> PlanRow:
    base = dict(label=q.label, name=q.name, required=q.required,
                type=q.type, options=q.options)

    if q.name in values and values[q.name]:
        return PlanRow(**base, status="auto", answer=values[q.name],
                       source="profile")

    if q.type == "input_file" or q.name in ("resume", "cover_letter"):
        return PlanRow(**base, status="attachment",
                       note="supplied at apply time (tailor/letter output)")

    entry = match_answer(q.label, book)
    if entry is not None:
        if not entry.answer:
            return PlanRow(**base, status="needs_input",
                           note=f"answer pending in answers.yaml ('{entry.id}')")
        if q.options and entry.answer.lower() not in (o.lower() for o in q.options):
            return PlanRow(
                **base, status="needs_input",
                note=f"stored answer '{entry.answer}' ('{entry.id}') not in "
                     f"options: {', '.join(q.options)}")
        return PlanRow(**base, status="answered", answer=entry.answer,
                       source=f"answers:{entry.id}")

    if is_sensitive(q.label):
        return PlanRow(**base, status="sensitive",
                       note="self-identification — left for manual review")

    return PlanRow(**base, status="needs_input")
