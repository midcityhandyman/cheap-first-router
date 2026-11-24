"""The routing policy.

1. A task carrying a sensitive tag goes straight to the strong provider. The
   cheap provider is never called for it, and a guard raises if anything tries.
2. Every other task is drafted by the cheap provider and run through checks.
3. A draft that fails checks is redone by the strong provider.
4. A deterministic sample of passing drafts is reviewed by the strong provider.
   If the reviewer disagrees, its answer replaces the draft.
Every provider call is written to a ledger so the report can price the run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .checks import run_checks
from .models import (CallRecord, Outcome, Task, Usage, estimate_tokens, normalise_tags,
                     stable_fraction)
from .providers import Provider

import json

ROUTES = (
    "sensitive_strong_only",
    "cheap_accepted",
    "cheap_verified",
    "escalated_checks",
    "escalated_sample",
)


class SensitiveLeakError(RuntimeError):
    """Raised if a sensitive task is about to be sent to a non strong provider."""


@dataclass
class RunResult:
    outcomes: list = field(default_factory=list)
    ledger: list = field(default_factory=list)
    baseline_cost: float = 0.0


class Router:
    def __init__(
        self,
        cheap: Provider,
        strong: Provider,
        sample_rate: float = 0.2,
        seed: int = 0,
        sensitive_tags: Iterable = ("sensitive",),
    ):
        if not 0.0 <= sample_rate <= 1.0:
            raise ValueError("sample_rate must be between 0 and 1")
        if strong.tier != "strong":
            raise ValueError("the strong provider must declare tier 'strong'")
        self.cheap = cheap
        self.strong = strong
        self.sample_rate = sample_rate
        self.seed = seed
        self.sensitive_tags = normalise_tags(sensitive_tags)
        if not self.sensitive_tags:
            raise ValueError("sensitive_tags must name at least one tag")
        self.ledger: list = []

    # public API

    def is_sensitive(self, task: Task) -> bool:
        return bool(normalise_tags(task.tags) & self.sensitive_tags)

    def is_sampled(self, task: Task) -> bool:
        return stable_fraction("sample", self.seed, task.id) < self.sample_rate

    def run(self, tasks: Iterable) -> RunResult:
        """Route a batch. The result carries only this run's calls; self.ledger keeps them all."""
        tasks = list(tasks)
        seen: set = set()
        for task in tasks:
            # Sampling, fault injection and the sensitive audit are all keyed by task id.
            if task.id in seen:
                raise ValueError(f"duplicate task id: {task.id}")
            seen.add(task.id)
        start = len(self.ledger)
        result = RunResult()
        for task in tasks:
            outcome = self.route(task)
            result.outcomes.append(outcome)
            result.baseline_cost += self._baseline(task, outcome)
        result.ledger = self.ledger[start:]
        return result

    def route(self, task: Task) -> Outcome:
        if self.is_sensitive(task):
            done = self._call(self.strong, task, "sensitive_direct", lambda: self.strong.complete(task))
            failures = run_checks(task, done.output)
            return Outcome(task.id, task.kind, "sensitive_strong_only", "strong", done.output,
                           sensitive=True, check_failures=failures, needs_review=bool(failures))

        draft = self._call(self.cheap, task, "draft", lambda: self.cheap.complete(task))
        failures = run_checks(task, draft.output)
        if failures:
            redo = self._call(self.strong, task, "redo_after_checks", lambda: self.strong.complete(task))
            return Outcome(task.id, task.kind, "escalated_checks", "strong", redo.output,
                           check_failures=failures, needs_review=bool(run_checks(task, redo.output)))

        if not self.is_sampled(task):
            return Outcome(task.id, task.kind, "cheap_accepted", "cheap", draft.output)

        verdict = self._call(self.strong, task, "sample_verify",
                             lambda: self.strong.verify(task, draft.output))
        if verdict.agrees:
            return Outcome(task.id, task.kind, "cheap_verified", "cheap", draft.output, sampled=True)
        return Outcome(task.id, task.kind, "escalated_sample", "strong", verdict.output, sampled=True,
                       needs_review=bool(run_checks(task, verdict.output)))

    # internals

    def _call(self, provider: Provider, task: Task, purpose: str, fn):
        """Single choke point for provider calls: guard first, then record the cost."""
        if provider.tier != "strong" and self.is_sensitive(task):
            raise SensitiveLeakError(f"task {task.id} is sensitive and may not go to {provider.name}")
        reply = fn()
        usage: Usage = reply.usage
        self.ledger.append(CallRecord(task.id, provider.name, provider.tier, purpose,
                                      usage.input_tokens, usage.output_tokens, provider.cost(usage)))
        return reply

    def _baseline(self, task: Task, outcome: Outcome) -> float:
        """Estimated cost had the strong provider answered this task directly."""
        usage = Usage(estimate_tokens(task.prompt()), estimate_tokens(json.dumps(outcome.output)))
        return self.strong.cost(usage)
