"""Cheap-first model router: bulk work goes to a low cost model, a strong model verifies."""

from .models import CallRecord, Completion, Outcome, Task, Usage, Verification
from .providers import MockCheapProvider, MockStrongProvider, Provider
from .report import build_report, render_text
from .router import Router, RunResult, SensitiveLeakError

__all__ = [
    "CallRecord", "Completion", "Outcome", "Task", "Usage", "Verification",
    "MockCheapProvider", "MockStrongProvider", "Provider",
    "build_report", "render_text", "Router", "RunResult", "SensitiveLeakError",
]
__version__ = "0.1.0"
