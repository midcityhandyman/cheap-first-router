"""Provider interface and offline mocks.

A real provider is a subclass of Provider that calls a hosted model inside
complete() and verify(). The mocks here are rule based, deterministic and need
no network or keys. The cheap mock injects faults at a configurable rate so
the router has something to catch.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod

from .models import Completion, Task, Usage, Verification, estimate_tokens, stable_fraction

NAME_RE = re.compile(r"Contact: ([A-Z][a-z]+ [A-Z][a-z]+)")
EMAIL_FIND_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_FIND_RE = re.compile(r"\b\d{3}-\d{4}\b")
KEYWORDS = {
    "billing": ("invoice", "charged", "refund", "payment"),
    "scheduling": ("appointment", "reschedule", "book", "slot"),
    "complaint": ("unhappy", "mess", "damaged", "disappointed"),
}


class Provider(ABC):
    """Anything that can answer a task and review a draft.

    Prices are per million tokens. The numbers on the mocks are illustrative,
    not a quote from any vendor.
    """

    name: str = "provider"
    tier: str = "cheap"
    input_price: float = 0.0
    output_price: float = 0.0

    @abstractmethod
    def complete(self, task: Task) -> Completion:
        """Produce an answer for the task."""

    @abstractmethod
    def verify(self, task: Task, candidate: dict) -> Verification:
        """Review a draft. Return the draft if it holds up, or a corrected answer."""

    def cost(self, usage: Usage) -> float:
        return (usage.input_tokens * self.input_price + usage.output_tokens * self.output_price) / 1e6


def _sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def _first(pattern: re.Pattern, text: str, group: int = 0) -> str:
    match = pattern.search(text)
    return match.group(group) if match else ""


def reference_answer(task: Task) -> dict:
    """The rule based answer both mocks start from."""
    if task.kind == "extract":
        found = {
            "name": _first(NAME_RE, task.text, 1),
            "email": _first(EMAIL_FIND_RE, task.text),
            "phone": _first(PHONE_FIND_RE, task.text),
        }
        return {name: found.get(name, "") for name in task.fields}
    if task.kind == "classify":
        lowered = task.text.lower()
        for label, words in KEYWORDS.items():
            if label in task.labels and any(word in lowered for word in words):
                return {"label": label}
        return {"label": "other" if "other" in task.labels else task.labels[-1]}
    if task.kind == "summarise":
        words = " ".join(_sentences(task.text)[:2]).split()
        return {"summary": " ".join(words[: task.max_words])}
    raise ValueError(f"unknown task kind: {task.kind}")


def _usage(prompt: str, output: dict) -> Usage:
    return Usage(estimate_tokens(prompt), estimate_tokens(json.dumps(output)))


class MockStrongProvider(Provider):
    """Stands in for an expensive, careful model. Treated as ground truth by the demo."""

    name = "mock-strong"
    tier = "strong"
    input_price = 5.00
    output_price = 25.00

    def complete(self, task: Task) -> Completion:
        output = reference_answer(task)
        return Completion(output, _usage(task.prompt(), output))

    def verify(self, task: Task, candidate: dict) -> Verification:
        own = reference_answer(task)
        prompt = task.prompt() + "\nDRAFT " + json.dumps(candidate)
        if self._agrees(task, own, candidate):
            return Verification(True, candidate, Usage(estimate_tokens(prompt), 2))
        return Verification(False, own, _usage(prompt, own))

    @staticmethod
    def _agrees(task: Task, own: dict, candidate: dict) -> bool:
        if task.kind != "summarise":
            return own == candidate
        mine = set(own["summary"].lower().split())
        theirs = set(str(candidate.get("summary", "")).lower().split())
        if not mine or not theirs:
            return False
        return len(mine & theirs) / len(mine | theirs) >= 0.5


class MockCheapProvider(Provider):
    """Stands in for a low cost model: usually right, sometimes wrong.

    hard_fault_rate: share of answers that are broken in a way checks can see
    soft_fault_rate: share that look fine but are wrong (only a review finds these)
    Faults are picked by a hash of the task id and seed, so runs repeat exactly.
    """

    name = "mock-cheap"
    tier = "cheap"
    input_price = 0.25
    output_price = 1.00

    def __init__(self, hard_fault_rate: float = 0.15, soft_fault_rate: float = 0.10, seed: int = 0):
        self.hard_fault_rate = hard_fault_rate
        self.soft_fault_rate = soft_fault_rate
        self.seed = seed

    def complete(self, task: Task) -> Completion:
        output = reference_answer(task)
        roll = stable_fraction("cheap-fault", self.seed, task.id)
        if roll < self.hard_fault_rate:
            output = self._hard_fault(task, output)
        elif roll < self.hard_fault_rate + self.soft_fault_rate:
            output = self._soft_fault(task, output)
        return Completion(output, _usage(task.prompt(), output))

    def verify(self, task: Task, candidate: dict) -> Verification:
        raise NotImplementedError("the cheap tier never reviews work")

    @staticmethod
    def _hard_fault(task: Task, output: dict) -> dict:
        if task.kind == "extract":
            broken = dict(output)
            broken[task.fields[-1]] = ""
            return broken
        if task.kind == "classify":
            return {"label": "unsure"}
        return {"summary": f"{task.text} {task.text}"}

    @staticmethod
    def _soft_fault(task: Task, output: dict) -> dict:
        if task.kind == "extract" and output.get("name"):
            wrong = dict(output)
            wrong["name"] = output["name"].split()[0]
            return wrong
        if task.kind == "classify":
            labels = list(task.labels)
            return {"label": labels[(labels.index(output["label"]) + 1) % len(labels)]}
        if task.kind == "summarise":
            return {"summary": " ".join(_sentences(task.text)[-1].split()[: task.max_words])}
        return output
