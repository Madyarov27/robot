"""Navigation by looking, for a robot with a camera and no map.

perceive -> decide -> act, at roughly one decision every few seconds. The
vision call is slow (1.5-4 s), so each decision buys a short motion burst and
the loop re-looks before committing further. That cadence is why motion lives
on its own thread: the robot is never blindly coasting while waiting on the API.

Interface-compatible with `nav.Navigator`, so `skills.py` drives either one.
"""
from __future__ import annotations

import threading
import time

from . import vision
from .motion import MotionController

MAX_STEPS = 40          # give up rather than wander (and bill) forever
MAX_FORWARD_M = 1.0
MAX_TURN_DEG = 60.0


class VisionNavigator:
    def __init__(self, camera: vision.Camera, motion: MotionController,
                 on_step=None) -> None:
        self.camera = camera
        self.motion = motion
        self.on_step = on_step
        self.status = "idle"
        self.last_seen = "nothing yet"
        self.places: dict[str, str] = {}   # name -> what it looked like
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # -- commands (same surface as nav.Navigator) ------------------------
    def go_to(self, place: str) -> str:
        self._start(f"find and reach the {place}", f"going to {place}")
        return f"Looking for the {place}."

    def explore(self) -> str:
        self._start(
            "explore the home, covering new ground and avoiding obstacles; "
            "never answer 'arrived'",
            "exploring",
        )
        return "Exploring."

    def cancel(self) -> str:
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=6)
        self.motion.stop()
        self.status = "idle"
        return "Stopped."

    def remember_here(self, name: str) -> str:
        self.places[name.lower().strip()] = self.last_seen
        return f"Got it — this is the {name}."

    def nearest_place(self) -> tuple[str, float]:
        return ("", float("inf"))  # no metric map to measure against

    # -- the loop --------------------------------------------------------
    def _start(self, goal: str, status: str) -> None:
        self.cancel()
        self._cancel.clear()
        self.status = status
        self._thread = threading.Thread(target=self._run, args=(goal,), daemon=True)
        self._thread.start()

    def _run(self, goal: str) -> None:
        recent: list[str] = []
        for _ in range(MAX_STEPS):
            if self._cancel.is_set():
                return
            try:
                frame = self.camera.capture()
                decision = vision.decide(frame, goal, recent)
            except Exception as exc:
                self.status = f"can't see ({type(exc).__name__})"
                self.motion.stop()
                return

            self.last_seen = decision["see"]
            action, amount = decision["action"], float(decision["amount"])
            recent.append(f"{action} {amount:g}")
            if self.on_step:
                self.on_step(decision)

            if action == "arrived":
                self.status = "arrived"
                self.motion.stop()
                return
            if action in ("stop", "blocked"):
                self.status = "blocked" if action == "blocked" else "idle"
                self.motion.stop()
                return
            self._execute(action, amount)
        self.status = "gave up"
        self.motion.stop()

    def _execute(self, action: str, amount: float) -> None:
        """Run one short burst, then stop and look again."""
        m = self.motion
        if action in ("forward", "back"):
            metres = min(abs(amount), MAX_FORWARD_M)
            speed = m.DRIVE_SPEED * (1 if action == "forward" else -1)
            duration = metres * m.UNITS_PER_M / m.DRIVE_SPEED
            m.set_velocity(speed, 0.0)
        else:
            degrees = min(abs(amount), MAX_TURN_DEG)
            speed = m.TURN_SPEED * (1 if action == "left" else -1)
            duration = degrees / m.TURN_SPEED
            m.set_velocity(0.0, speed)

        # Interruptible sleep: a "stop" command must land within ~100 ms.
        end = time.time() + min(duration, 6.0)
        while time.time() < end and not self._cancel.is_set():
            time.sleep(0.05)
        m.stop()
