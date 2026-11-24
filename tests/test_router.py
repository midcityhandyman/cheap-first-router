import pytest

from cheap_first_router import (MockCheapProvider, MockStrongProvider, Router, SensitiveLeakError,
                                Task, build_report, render_text)
from cheap_first_router.checks import run_checks
from cheap_first_router.config import Settings
from cheap_first_router.models import Completion, Usage, stable_fraction
from cheap_first_router.providers import Provider, reference_answer
from cheap_first_router.synthetic import make_tasks

LABELS = ("billing", "scheduling", "complaint", "other")


class SpyCheap(MockCheapProvider):
    """Cheap mock that records every task id it is shown."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.seen = []

    def complete(self, task):
        self.seen.append(task.id)
        return super().complete(task)


class FixedCheap(Provider):
    """Cheap provider that returns a canned output."""

    name, tier, input_price, output_price = "fixed-cheap", "cheap", 0.25, 1.0

    def __init__(self, output):
        self.output = output

    def complete(self, task):
        return Completion(self.output, Usage(10, 5))

    def verify(self, task, candidate):
        raise NotImplementedError


def classify_task(task_id="C1", tags=()):
    return Task(task_id, "classify", "Please send a refund for the cancelled visit.",
                frozenset(tags), labels=LABELS)


def clean_router(sample_rate=0.0, **kwargs):
    return Router(MockCheapProvider(hard_fault_rate=0, soft_fault_rate=0), MockStrongProvider(),
                  sample_rate=sample_rate, **kwargs)


# sensitive handling

def test_sensitive_tasks_never_reach_the_cheap_provider():
    cheap = SpyCheap(hard_fault_rate=0.3, soft_fault_rate=0.3)
    router = Router(cheap, MockStrongProvider(), sample_rate=0.5)
    tasks = make_tasks(60)
    result = router.run(tasks)
    sensitive = {t.id for t in tasks if "sensitive" in t.tags}
    assert sensitive, "the synthetic batch should contain sensitive tasks"
    assert sensitive.isdisjoint(cheap.seen)
    for call in result.ledger:
        if call.task_id in sensitive:
            assert call.tier == "strong" and call.purpose == "sensitive_direct"
    assert build_report(result)["sensitive_calls_off_strong"] == 0


def test_sensitive_tag_match_is_case_insensitive_and_configurable():
    router = clean_router(sensitive_tags=("PII",))
    assert router.route(classify_task(tags=("pii",))).route == "sensitive_strong_only"
    assert router.route(classify_task(tags=("sensitive",))).route == "cheap_accepted"


def test_guard_raises_if_a_sensitive_task_is_pushed_at_the_cheap_tier():
    router = clean_router()
    task = classify_task(tags=("sensitive",))
    with pytest.raises(SensitiveLeakError):
        router._call(router.cheap, task, "draft", lambda: router.cheap.complete(task))
    assert router.ledger == []


def test_strong_slot_must_be_a_strong_tier_provider():
    with pytest.raises(ValueError):
        Router(MockCheapProvider(), MockCheapProvider())


# cheap path, checks and escalation

def test_clean_draft_is_accepted_with_one_cheap_call():
    router = clean_router()
    outcome = router.route(classify_task())
    assert (outcome.route, outcome.final_tier, outcome.output) == ("cheap_accepted", "cheap",
                                                                    {"label": "billing"})
    assert [c.purpose for c in router.ledger] == ["draft"]


def test_draft_failing_checks_is_redone_by_strong():
    router = Router(FixedCheap({"label": "unsure"}), MockStrongProvider(), sample_rate=0.0)
    outcome = router.route(classify_task())
    assert outcome.route == "escalated_checks"
    assert outcome.check_failures == ["label_not_allowed"]
    assert outcome.output == {"label": "billing"} and outcome.final_tier == "strong"
    assert [c.purpose for c in router.ledger] == ["draft", "redo_after_checks"]


def test_sampled_draft_that_holds_up_keeps_the_cheap_answer():
    router = clean_router(sample_rate=1.0)
    outcome = router.route(classify_task())
    assert outcome.route == "cheap_verified" and outcome.sampled and outcome.final_tier == "cheap"
    assert [c.purpose for c in router.ledger] == ["draft", "sample_verify"]


def test_sampled_draft_that_is_wrong_is_overturned():
    router = Router(FixedCheap({"label": "complaint"}), MockStrongProvider(), sample_rate=1.0)
    outcome = router.route(classify_task())
    assert outcome.route == "escalated_sample"
    assert outcome.output == {"label": "billing"}


def test_plausible_wrong_draft_slips_through_when_not_sampled():
    # Honest limitation: checks cannot see a valid but wrong label.
    router = Router(FixedCheap({"label": "complaint"}), MockStrongProvider(), sample_rate=0.0)
    assert router.route(classify_task()).route == "cheap_accepted"


def test_sampling_is_deterministic_and_tracks_the_rate():
    tasks = make_tasks(300, sensitive_every=0)
    first = [clean_router(sample_rate=0.2, seed=3).is_sampled(t) for t in tasks]
    second = [clean_router(sample_rate=0.2, seed=3).is_sampled(t) for t in tasks]
    assert first == second
    assert 0.12 < sum(first) / len(first) < 0.28
    assert 0.0 <= stable_fraction("a", 1) < 1.0


def test_sample_rate_is_validated():
    with pytest.raises(ValueError):
        clean_router(sample_rate=1.5)


# checks

def test_extract_checks_cover_missing_ungrounded_and_malformed_values():
    task = Task("E1", "extract", "Contact: Alex Sample. Email alex.sample@example.com, phone 555-0101.",
                fields=("name", "email", "phone"))
    assert run_checks(task, reference_answer(task)) == []
    bad = {"name": "Jordan Example", "email": "alex.sample@example.com", "phone": ""}
    assert run_checks(task, bad) == ["ungrounded:name", "missing_field:phone"]
    assert "bad_phone" in run_checks(task, {"name": "Alex Sample", "email": "alex.sample@example.com",
                                            "phone": "Alex"})


def test_summary_checks_cover_length_and_emptiness():
    task = Task("S1", "summarise", "One two three four five six. Seven eight nine ten.", max_words=5)
    assert run_checks(task, {"summary": "One two three"}) == []
    assert run_checks(task, {"summary": ""}) == ["empty_summary"]
    assert "summary_too_long" in run_checks(task, {"summary": task.text})
    assert run_checks(Task("X", "translate", "hi"), {}) == ["unknown_kind"]


# report

def test_report_totals_reconcile_with_the_ledger():
    router = Router(MockCheapProvider(seed=7), MockStrongProvider(), sample_rate=0.25, seed=7)
    result = router.run(make_tasks(40))
    report = build_report(result)
    assert sum(report["routes"].values()) == report["tasks"] == 40
    assert report["bulk_tasks"] + report["sensitive_tasks"] == 40
    assert report["total_cost"] == pytest.approx(sum(c.cost for c in result.ledger))
    assert report["total_cost"] == pytest.approx(sum(p["cost"] for p in report["providers"].values()))
    assert report["providers"]["mock-cheap"]["calls"] == report["bulk_tasks"]
    strong_calls = (report["sensitive_tasks"] + report["sampled"] + report["routes"]["escalated_checks"])
    assert report["providers"]["mock-strong"]["calls"] == strong_calls
    assert report["escalations"] > 0 and report["sampled"] > 0
    assert 0 < report["total_cost"] < report["baseline_all_strong_cost"]
    assert report["needs_review"] == []
    text = render_text(report)
    assert "CHEAP-FIRST ROUTER REPORT" in text and "OK" in text
    assert chr(8212) not in text


def test_same_inputs_give_the_same_report():
    def run():
        router = Router(MockCheapProvider(seed=1), MockStrongProvider(), sample_rate=0.3, seed=1)
        return build_report(router.run(make_tasks(30)))
    assert run() == run()


def test_all_strong_routing_costs_about_the_baseline():
    tasks = [classify_task(f"C{i}", tags=("sensitive",)) for i in range(5)]
    report = build_report(clean_router().run(tasks))
    assert report["total_cost"] == pytest.approx(report["baseline_all_strong_cost"])
    assert report["escalation_rate"] == 0.0


# config and CLI

def test_settings_from_env():
    settings = Settings.from_env({"CFR_SAMPLE_RATE": "0.5", "CFR_SEED": "9", "CFR_SENSITIVE_TAGS": "PII, legal"})
    assert settings == Settings(0.5, 9, ("pii", "legal"))
    assert Settings.from_env({}) == Settings()


def test_cli_runs_a_jsonl_file_and_writes_json(tmp_path, capsys):
    import json
    from cheap_first_router.__main__ import main

    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        json.dumps({"id": "A", "kind": "classify", "text": "I was charged twice.", "labels": list(LABELS)})
        + "\n"
        + json.dumps({"id": "B", "kind": "classify", "text": "Refund please.", "labels": list(LABELS),
                      "tags": ["Sensitive"]})
        + "\n", encoding="utf-8")
    out = tmp_path / "report.json"
    assert main(["--tasks", str(tasks), "--json", str(out), "--trace"]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["tasks"] == 2 and report["sensitive_tasks"] == 1
    assert "sensitive_strong_only" in capsys.readouterr().out
