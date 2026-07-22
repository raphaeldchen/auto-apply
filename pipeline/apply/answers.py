"""Answer memory: user-confirmed answers to recurring application questions.

answers.yaml is written by the user, so every stored answer is consented by
construction. Matching is deterministic (case-insensitive substring, file
order wins) and an empty answer means "known question, answer pending" —
the planner never fills a blank. EEO/demographic questions are flagged
sensitive and left for the human unless the user explicitly stored an
answer for them.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

# Voluntary self-identification / EEO topics: never auto-answered by default.
_SENSITIVE = re.compile(
    r"gender|race|ethnic|veteran|disab|sexual orientation|transgender|"
    r"hispanic|latino|latinx|pronoun|accommodat",
    re.IGNORECASE,
)


@dataclass
class AnswerEntry:
    id: str
    patterns: list[str]
    answer: str


@dataclass
class AnswerBook:
    entries: list[AnswerEntry]


def load_answers(path) -> AnswerBook:
    path = Path(path)
    if not path.exists():
        return AnswerBook(entries=[])
    data = yaml.safe_load(path.read_text()) or {}
    entries = []
    seen_ids = set()
    for raw in data.get("answers") or []:
        for field in ("id", "patterns"):
            if not raw.get(field):
                raise ValueError(f"answer entry missing '{field}': {raw!r}")
        if "answer" not in raw:
            raise ValueError(f"answer entry missing 'answer': {raw!r}")
        if raw["id"] in seen_ids:
            raise ValueError(f"duplicate answer id '{raw['id']}'")
        seen_ids.add(raw["id"])
        entries.append(AnswerEntry(
            id=raw["id"],
            patterns=[str(p) for p in raw["patterns"]],
            answer=str(raw["answer"] or ""),
        ))
    return AnswerBook(entries=entries)


def match_answer(question_text: str, book: AnswerBook) -> AnswerEntry | None:
    haystack = question_text.lower()
    for entry in book.entries:
        if any(p.lower() in haystack for p in entry.patterns):
            return entry
    return None


def is_sensitive(question_text: str) -> bool:
    return bool(_SENSITIVE.search(question_text))
