"""Offline demo: route a synthetic batch through mock providers and print the report.

Run from the repo root:  python demo/run_demo.py
No install, network or keys needed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cheap_first_router.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(["--demo", "40", "--sample-rate", "0.25", "--seed", "1", "--trace"]))
