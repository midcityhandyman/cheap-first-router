"""Plain data types shared by the router, providers and report."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

KINDS = ("extract", "classify", "summarise")


def normalise_tags(tags) -> frozenset:
    """Lower cased, stripped tag set. A bare string is one tag, not a sequence of letters."""
    if tags is None:
        return frozenset()
    if isinstance(tags, str):
        tags = tags.split(",")
    return frozenset(t for t in (str(tag).strip().lower() for tag in tags) if t)


@dataclass(frozen=True)
class Task:
    """One unit of bulk work.

    kind:      extract, classify or summarise
    tags:      free form labels; any tag in the router's sensitive set pins the
               task to the strong model
    fields:    for extract, the fields that must come back
    labels:    for classify, the allowed labels
    max_words: for summarise, the length limit
    """

    id: str
    kind: str
    text: str
    tags: frozenset = frozenset()
    fields: tuple = ()
    labels: tuple = ()
    max_words: int = 30

    def __post_init__(self):
        # Normalise here so a task built with tags="sensitive" cannot dodge the sensitive route.
        object.__setattr__(self, "tags", normalise_tags(self.tags))

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        """Build a task from untrusted input (a JSONL line). Rejects what cannot be routed."""
        if not isinstance(raw, dict):
            raise ValueError("a task must be a JSON object")
        for key in ("id", "kind", "text"):
            if key not in raw:
                raise ValueError(f"task is missing '{key}'")
        task = cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            text=str(raw["text"]),
            tags=normalise_tags(raw.get("tags")),
            fields=_names(raw.get("fields")),
            labels=_names(raw.get("labels")),
            max_words=int(raw.get("max_words", 30)),
        )
        if task.kind not in KINDS:
            raise ValueError(f"task {task.id}: unknown kind '{task.kind}', expected one of {', '.join(KINDS)}")
        if task.kind == "extract" and not task.fields:
            raise ValueError(f"task {task.id}: extract needs a non empty 'fields' list")
        if task.kind == "classify" and not task.labels:
            raise ValueError(f"task {task.id}: classify needs a non empty 'labels' list")
        if task.kind == "summarise" and task.max_words < 1:
            raise ValueError(f"task {task.id}: max_words must be at least 1")
        return task

    def prompt(self) -> str:
        """The text a provider would be sent. Used for token accounting."""
        spec = {"extract": self.fields, "classify": self.labels, "summarise": self.max_words}
        return f"{self.kind} {json.dumps(spec.get(self.kind, ''))}\n{self.text}"


def _names(value) -> tuple:
    """A list of field or label names. A bare string is one name."""
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class Completion:
    output: dict
    usage: Usage


@dataclass(frozen=True)
class Verification:
    """A strong model's verdict on a cheap draft. output is the answer to keep."""

    agrees: bool
    output: dict
    usage: Usage


@dataclass(frozen=True)
class CallRecord:
    """One provider call, as written to the cost ledger."""

    task_id: str
    provider: str
    tier: str
    purpose: str
    input_tokens: int
    output_tokens: int
    cost: float


@dataclass
class Outcome:
    """What happened to one task."""

    task_id: str
    kind: str
    route: str
    final_tier: str
    output: dict
    sensitive: bool = False
    sampled: bool = False
    check_failures: list = field(default_factory=list)
    needs_review: bool = False


def estimate_tokens(text: str) -> int:
    """Rough token count (about four characters per token). Good enough for mocks."""
    return max(1, math.ceil(len(text) / 4))


def stable_fraction(*parts: object) -> float:
    """Deterministic value in [0, 1) from the given parts. Stable across runs and machines."""
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64
