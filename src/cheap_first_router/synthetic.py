"""Synthetic task generator. Every name, phone and email here is invented."""

from __future__ import annotations

from .models import Task

NAMES = ("Alex Sample", "Jordan Example", "Casey Placeholder", "Riley Testcase",
         "Morgan Demo", "Taylor Fixture")
REQUESTS = ("Wants a quote for gutter cleaning", "Asked for a callback about a leaking tap",
            "Needs a fence panel replaced", "Looking for a spring tidy of the garden")
MESSAGES = (
    "The invoice total looks wrong and I think I was charged twice for one visit.",
    "Can we move the appointment to Thursday morning instead of Tuesday?",
    "The crew left a mess in the hallway and I am unhappy with the finish.",
    "Do you have a newsletter I can sign up for?",
    "Please send a refund for the cancelled visit.",
    "I would like to book a slot next week for the follow up.",
)
NOTES = (
    "Visit note for job {n}. Replaced the kitchen tap washer and tested the joint for leaks "
    "over ten minutes. The customer asked about a separate quote for the bathroom extractor fan.",
    "Visit note for job {n}. Cleared the blocked downpipe at the rear and flushed the gutter run "
    "with a hose. A cracked bracket near the corner should be replaced on the next visit.",
    "Visit note for job {n}. Rehung the sticking bedroom door and planed the leading edge by two "
    "millimetres. Paint touch up on the planed edge is still to be done by the decorator.",
)
LABELS = ("billing", "scheduling", "complaint", "other")
KIND_CYCLE = ("extract", "classify", "summarise")


def make_tasks(count: int = 40, sensitive_every: int = 7) -> list:
    """Build a repeatable mixed batch. Every sensitive_every-th task is tagged sensitive."""
    tasks = []
    for i in range(count):
        kind = KIND_CYCLE[i % 3]
        tags = frozenset({"sensitive"}) if sensitive_every and i % sensitive_every == 3 else frozenset()
        task_id = f"T{i + 1:03d}"
        if kind == "extract":
            name = NAMES[i % len(NAMES)]
            email = name.lower().replace(" ", ".") + "@example.com"
            phone = f"555-01{i % 100:02d}"
            text = f"Contact: {name}. Email {email}, phone {phone}. {REQUESTS[i % len(REQUESTS)]}."
            tasks.append(Task(task_id, kind, text, tags, fields=("name", "email", "phone")))
        elif kind == "classify":
            tasks.append(Task(task_id, kind, MESSAGES[i % len(MESSAGES)], tags, labels=LABELS))
        else:
            tasks.append(Task(task_id, kind, NOTES[i % len(NOTES)].format(n=1000 + i), tags, max_words=30))
    return tasks
