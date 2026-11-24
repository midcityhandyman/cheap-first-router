"""Plain data types shared by the router, providers and report."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

KINDS = ("extract", "classify", "summarise")


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

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        return cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            text=str(raw["text"]),
            tags=frozenset(str(t).lower() for t in raw.get("tags", ())),
            fields=tuple(raw.get("fields", ())),
            labels=tuple(raw.get("labels", ())),
            max_words=int(raw.get("max_words", 30)),
        )

    def prompt(self) -> str:
        """The text a provider would be sent. Used for token accounting."""
        spec = {"extract": self.fields, "classify": self.labels, "summarise": self.max_words}
        return f"{self.kind} {json.dumps(spec.get(self.kind, ''))}\n{self.text}"


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
