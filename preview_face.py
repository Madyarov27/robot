"""Look at the face without spending an API call.

  python preview_face.py          # cycle every state on a timer
  python preview_face.py idle     # hold one state

The window must own the main thread, so the state driver runs on a worker.
Close the window or press q / Esc to quit.
"""
from __future__ import annotations

import math
import sys
import threading
import time

from robot.face import FaceState
from robot.face_window import WindowFace

ORDER = [
    FaceState.BOOTING, FaceState.IDLE, FaceState.LISTENING, FaceState.THINKING,
    FaceState.TALKING, FaceState.CONFUSED, FaceState.ERROR,
]


def cycle(face: WindowFace, stop: threading.Event, hold: FaceState | None) -> None:
    if hold is not None:
        face.set(hold)
        while not stop.is_set():
            if hold is FaceState.TALKING:
                face.set_level(_fake_speech())
            time.sleep(1 / 60)
        return

    while not stop.is_set():
        for state in ORDER:
            if stop.is_set():
                return
            print(f"  {state.value}")
            face.set(state)
            t0 = time.time()
            while time.time() - t0 < 2.5 and not stop.is_set():
                if state is FaceState.TALKING:
                    face.set_level(_fake_speech())
                time.sleep(1 / 60)
            face.set_level(0.0)


def _fake_speech() -> float:
    """Stand-in for real TTS loudness, so the mouth has something to track."""
    n = time.time() * 9
    return abs(math.sin(n)) * abs(math.sin(n * 0.37))


def main() -> int:
    hold = None
    if len(sys.argv) > 1:
        try:
            hold = FaceState(sys.argv[1].lower())
        except ValueError:
            print(f"unknown state '{sys.argv[1]}'. pick from: {[s.value for s in ORDER]}")
            return 2

    face = WindowFace()
    stop = threading.Event()
    threading.Thread(target=cycle, args=(face, stop, hold), daemon=True).start()
    print(f"{'holding ' + hold.value if hold else 'cycling states, ~2.5s each'}. q or Esc to quit.")
    face.run_until(stop)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
