"""Cost and escalation report built from outcomes and the call ledger."""

from __future__ import annotations

from collections import Counter

from .router import ROUTES, RunResult


def build_report(result: RunResult) -> dict:
    outcomes, ledger = result.outcomes, result.ledger
    sensitive_ids = {o.task_id for o in outcomes if o.sensitive}
    routes = Counter(o.route for o in outcomes)
    sensitive = sum(1 for o in outcomes if o.sensitive)
    bulk = len(outcomes) - sensitive
    escalated = routes["escalated_checks"] + routes["escalated_sample"]
    sampled = sum(1 for o in outcomes if o.sampled)
    overturned = routes["escalated_sample"]

    providers: dict = {}
    for call in ledger:
        row = providers.setdefault(call.provider, {"tier": call.tier, "calls": 0, "input_tokens": 0,
                                                   "output_tokens": 0, "cost": 0.0})
        row["calls"] += 1
        row["input_tokens"] += call.input_tokens
        row["output_tokens"] += call.output_tokens
        row["cost"] += call.cost

    total = sum(call.cost for call in ledger)
    reasons = Counter(code.split(":")[0] for o in outcomes if o.route == "escalated_checks"
                      for code in o.check_failures)
    by_kind: dict = {}
    for o in outcomes:
        row = by_kind.setdefault(o.kind, {"tasks": 0, "escalated": 0})
        row["tasks"] += 1
        row["escalated"] += o.route in ("escalated_checks", "escalated_sample")

    return {
        "tasks": len(outcomes),
        "bulk_tasks": bulk,
        "sensitive_tasks": sensitive,
        "routes": {route: routes.get(route, 0) for route in ROUTES},
        "escalations": escalated,
        "escalation_rate": _ratio(escalated, bulk),
        "check_failure_reasons": dict(sorted(reasons.items())),
        "sampled": sampled,
        "sample_overturned": overturned,
        "sample_disagreement_rate": _ratio(overturned, sampled),
        "unreviewed_accepted": routes["cheap_accepted"],
        "needs_review": sorted(o.task_id for o in outcomes if o.needs_review),
        "by_kind": by_kind,
        "providers": providers,
        "purposes": dict(sorted(Counter(call.purpose for call in ledger).items())),
        "total_cost": total,
        "baseline_all_strong_cost": result.baseline_cost,
        "savings": result.baseline_cost - total,
        "savings_rate": _ratio(result.baseline_cost - total, result.baseline_cost),
        # Audit line: counts non strong calls made for sensitive tasks. Must be zero.
        "sensitive_calls_off_strong": sum(1 for c in ledger
                                          if c.task_id in sensitive_ids and c.tier != "strong"),
    }


def _ratio(part: float, whole: float) -> float:
    return part / whole if whole else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_text(report: dict) -> str:
    r = report
    lines = [
        "CHEAP-FIRST ROUTER REPORT",
        "=" * 58,
        f"Tasks: {r['tasks']}  (bulk {r['bulk_tasks']}, sensitive {r['sensitive_tasks']})",
        "",
        "Routing",
    ]
    for route, count in r["routes"].items():
        lines.append(f"  {route:<24}{count:>5}")
    lines += [
        "",
        "Escalation",
        f"  escalated to strong     {r['escalations']:>5}  ({_pct(r['escalation_rate'])} of bulk tasks)",
    ]
    for reason, count in r["check_failure_reasons"].items():
        lines.append(f"    check: {reason:<20}{count:>3}")
    lines += [
        f"  sampled for review      {r['sampled']:>5}",
        f"  sample overturned       {r['sample_overturned']:>5}  "
        f"({_pct(r['sample_disagreement_rate'])} of sampled)",
        f"  accepted unreviewed     {r['unreviewed_accepted']:>5}",
        f"  needs human review      {len(r['needs_review']):>5}",
        "",
        "By task kind",
    ]
    for kind, row in sorted(r["by_kind"].items()):
        lines.append(f"  {kind:<12} tasks {row['tasks']:>3}   escalated {row['escalated']:>3}")
    lines += ["", "Cost by provider (USD, illustrative prices)",
              f"  {'provider':<14}{'calls':>6}{'in tok':>9}{'out tok':>9}{'cost':>12}"]
    for name, row in sorted(r["providers"].items()):
        lines.append(f"  {name:<14}{row['calls']:>6}{row['input_tokens']:>9}"
                     f"{row['output_tokens']:>9}{row['cost']:>12.6f}")
    lines += [
        f"  {'total':<38}{r['total_cost']:>12.6f}",
        f"  {'baseline, all strong (estimate)':<38}{r['baseline_all_strong_cost']:>12.6f}",
        f"  {'saved':<38}{r['savings']:>12.6f}  ({_pct(r['savings_rate'])})",
        "",
        "Sensitive audit",
        f"  sensitive tasks sent off the strong model: {r['sensitive_calls_off_strong']}"
        + ("  OK" if r["sensitive_calls_off_strong"] == 0 else "  VIOLATION"),
    ]
    return "\n".join(lines)
