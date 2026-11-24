"""Command line entry: python -m cheap_first_router [--tasks FILE | --demo N].

The command line always uses the two offline mock providers. Exit code 0 on a clean run,
1 if the sensitive audit fails, 2 on bad input.
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import Settings
from .models import Task
from .providers import MockCheapProvider, MockStrongProvider
from .report import build_report, render_text
from .router import Router
from .synthetic import make_tasks


def load_tasks(path: str) -> list:
    tasks = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                tasks.append(Task.from_dict(json.loads(line)))
            except (ValueError, TypeError) as exc:  # JSONDecodeError is a ValueError
                raise ValueError(f"{path} line {number}: {exc}") from exc
    return tasks


def main(argv=None) -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(prog="cheap_first_router", description=__doc__)
    parser.add_argument("--tasks", help="JSONL file, one task per line")
    parser.add_argument("--demo", type=int, default=40, help="number of synthetic tasks (default 40)")
    parser.add_argument("--sample-rate", type=float, default=settings.sample_rate)
    parser.add_argument("--seed", type=int, default=settings.seed)
    parser.add_argument("--json", dest="json_path", help="also write the report as JSON to this path")
    parser.add_argument("--trace", action="store_true", help="print one routing line per task")
    args = parser.parse_args(argv)

    try:
        tasks = load_tasks(args.tasks) if args.tasks else make_tasks(args.demo)
        router = Router(MockCheapProvider(seed=args.seed), MockStrongProvider(),
                        sample_rate=args.sample_rate, seed=args.seed,
                        sensitive_tags=settings.sensitive_tags)
        result = router.run(tasks)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.trace:
        for o in result.outcomes:
            note = ",".join(o.check_failures)
            print(f"{o.task_id}  {o.kind:<10} {o.route:<22} final={o.final_tier:<6} {note}")
        print()
    report = build_report(result)
    print(render_text(report))
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)
    return 1 if report["sensitive_calls_off_strong"] else 0


if __name__ == "__main__":
    sys.exit(main())
