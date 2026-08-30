"""Motion control, decoupled from the API loop.

The controller runs its own 20 Hz thread. Nothing here ever blocks on a network
call — that separation is the whole point: a 3 s API round-trip must not freeze
a robot that is mid-turn.

`MotionController` is the seam. `SimMotion` integrates a simple kinematic model
on the laptop; the Pi implementation drives a TB6612FNG and reads an IMU for
heading, exposing exactly the same three methods.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


@dataclass
class Pose:
    x: float = 0.0        # grid cells
    y: float = 0.0
    heading: float = 0.0  # degrees, 0 = +x, counter-clockwise positive

    def distance_to(self, x: float, y: float) -> float:
        return math.hypot(x - self.x, y - self.y)

    def bearing_to(self, x: float, y: float) -> float:
        return math.degrees(math.atan2(y - self.y, x - self.x))


def angle_diff(a: float, b: float) -> float:
    """Signed shortest angular distance from b to a, in degrees."""
    return (a - b + 180) % 360 - 180


class MotionController:
    """Interface the navigator drives. Implementations must be non-blocking."""

    UNITS_PER_M = 1.0   # SimMotion works in grid cells; real motors in metres
    DRIVE_SPEED = 0.35  # units/s used when the navigator asks for a distance
    TURN_SPEED = 70.0   # deg/s

    def set_velocity(self, forward: float, turn: float) -> None:
        """forward: cells/s. turn: deg/s, positive = counter-clockwise."""
        raise NotImplementedError

    def stop(self) -> None:
        self.set_velocity(0.0, 0.0)

    @property
    def pose(self) -> Pose:
        raise NotImplementedError


class SimMotion(MotionController):
    """Kinematic simulation with the imperfections that actually matter.

    Slip and heading drift are modelled deliberately: a navigator that only
    works on perfect odometry is a navigator that will fail on the real sphere.
    """

    MAX_FORWARD = 1.2   # cells/s
    MAX_TURN = 140.0    # deg/s
    UNITS_PER_M = 2.0   # the sim grid is 0.5 m per cell

    def __init__(self, x: float = 1.0, y: float = 1.0, heading: float = 0.0,
                 slip: float = 0.04, drift: float = 0.6) -> None:
        self._pose = Pose(x, y, heading)
        self._cmd = (0.0, 0.0)
        self._slip = slip          # fraction of commanded distance lost
        self._drift = drift        # deg/s of heading error while driving
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_velocity(self, forward: float, turn: float) -> None:
        with self._lock:
            self._cmd = (
                max(-self.MAX_FORWARD, min(self.MAX_FORWARD, forward)),
                max(-self.MAX_TURN, min(self.MAX_TURN, turn)),
            )

    @property
    def pose(self) -> Pose:
        with self._lock:
            return Pose(self._pose.x, self._pose.y, self._pose.heading)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        dt = 1 / 20
        while not self._stop.is_set():
            with self._lock:
                fwd, turn = self._cmd
                p = self._pose
                p.heading = (p.heading + turn * dt) % 360
                if fwd:
                    # the shell slips, and the robot pulls to one side
                    p.heading = (p.heading + self._drift * dt) % 360
                    d = fwd * dt * (1 - self._slip)
                    p.x += d * math.cos(math.radians(p.heading))
                    p.y += d * math.sin(math.radians(p.heading))
            time.sleep(dt)
