"""Settings read from the environment. Nothing here is secret."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    sample_rate: float = 0.2
    seed: int = 0
    sensitive_tags: tuple = ("sensitive",)

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        env = os.environ if env is None else env
        tags = tuple(t.strip().lower() for t in env.get("CFR_SENSITIVE_TAGS", "sensitive").split(",")
                     if t.strip())
        return cls(
            sample_rate=float(env.get("CFR_SAMPLE_RATE", "0.2")),
            seed=int(env.get("CFR_SEED", "0")),
            sensitive_tags=tags or ("sensitive",),
        )
