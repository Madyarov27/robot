"""Face state machine.

Today it prints to the terminal. When the GC9A01 arrives, subclass Face and
render frames in `on_state` — the rest of the robot never changes.
"""
from __future__ import annotations

from enum import Enum


class FaceState(str, Enum):
    BOOTING = "booting"
    IDLE = "idle"        # awake, waiting for a voice
    LISTENING = "listening"
    THINKING = "thinking"  # API round-trip in flight
    TALKING = "talking"
    CONFUSED = "confused"  # heard something, understood nothing
    ERROR = "error"


class Face:
    def __init__(self) -> None:
        self.state = FaceState.BOOTING

    def set(self, state: FaceState) -> None:
        if state == self.state:
            return
        self.state = state
        self.on_state(state)

    def on_state(self, state: FaceState) -> None:  # pragma: no cover - override point
        pass


_GLYPHS = {
    FaceState.BOOTING: "( · · )  booting",
    FaceState.IDLE: "( ^ ^ )  idle",
    FaceState.LISTENING: "( O O )  listening",
    FaceState.THINKING: "( - - )  thinking",
    FaceState.TALKING: "( ^ ^ )~ talking",
    FaceState.CONFUSED: "( o_O )  didn't catch that",
    FaceState.ERROR: "( x x )  error",
}


class ConsoleFace(Face):
    def on_state(self, state: FaceState) -> None:
        print(f"  {_GLYPHS[state]}", flush=True)
