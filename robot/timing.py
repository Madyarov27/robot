"""Per-turn stage timing.

The interesting number for a voice robot is not total wall time, it's
*time-to-first-audio* — the gap between you stopping and it starting. Everything
after that is hidden behind its own voice.
"""
from __future__ import annotations

import os
import time

ENABLED = os.getenv("ROBOT_TIMING", "1").lower() not in ("0", "false", "no")


class TurnTimer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()
        self.marks: list[tuple[str, float]] = []

    def mark(self, name: str) -> float:
        """Record a stage boundary. Returns ms since the turn started."""
        ms = (time.perf_counter() - self.t0) * 1000
        self.marks.append((name, ms))
        return ms

    def at(self, name: str) -> float | None:
        for n, ms in self.marks:
            if n == name:
                return ms
        return None

    def stages(self) -> list[tuple[str, float]]:
        """Durations between marks, rather than cumulative offsets."""
        out, prev = [], 0.0
        for name, ms in self.marks:
            out.append((name, ms - prev))
            prev = ms
        return out

    def report(self) -> str:
        parts = [f"{n} {ms:.0f}ms" for n, ms in self.stages()]
        ttfa = self.at("first-audio")
        tail = f"  |  to-first-audio {ttfa:.0f}ms" if ttfa is not None else ""
        return "  ⏱  " + " · ".join(parts) + tail

    def print(self) -> None:
        if ENABLED:
            print(self.report(), flush=True)
