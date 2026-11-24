"""Deterministic checks run on every cheap draft. No model involved.

A draft that fails any check is escalated to the strong model. The checks are
deliberately cheap and mechanical: shape, allowed values, and grounding.
"""

from __future__ import annotations

import re

from .models import Task

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\d{3}-\d{4}$")


def run_checks(task: Task, output: dict) -> list:
    """Return a list of failure codes. An empty list means the draft passed."""
    if not isinstance(output, dict):
        return ["not_a_mapping"]
    if task.kind == "extract":
        return _check_extract(task, output)
    if task.kind == "classify":
        return _check_classify(task, output)
    if task.kind == "summarise":
        return _check_summarise(task, output)
    return ["unknown_kind"]


def _check_extract(task: Task, output: dict) -> list:
    failures = []
    for name in task.fields:
        value = output.get(name)
        if not isinstance(value, str) or not value.strip():
            failures.append(f"missing_field:{name}")
            continue
        if value not in task.text:
            # Grounding: an extracted value must appear verbatim in the source.
            failures.append(f"ungrounded:{name}")
        if name == "email" and not EMAIL_RE.match(value):
            failures.append("bad_email")
        if name == "phone" and not PHONE_RE.match(value):
            failures.append("bad_phone")
    return failures


def _check_classify(task: Task, output: dict) -> list:
    label = output.get("label")
    if not isinstance(label, str) or not label:
        return ["missing_label"]
    if label not in task.labels:
        return ["label_not_allowed"]
    return []


def _check_summarise(task: Task, output: dict) -> list:
    summary = output.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return ["empty_summary"]
    failures = []
    if len(summary.split()) > task.max_words:
        failures.append("summary_too_long")
    if len(summary) >= len(task.text):
        failures.append("summary_not_shorter")
    return failures
