"""Map, path planning, and the waypoint follower.

The planner is deliberately hardware-independent: it consumes a grid and a pose
and emits velocity commands. Swapping SimMotion for real motors, or dead
reckoning for camera-based localisation, does not touch this file.
"""
from __future__ import annotations

import heapq
import math
import random
import threading
import time
from pathlib import Path

from .motion import MotionController, angle_diff

FREE, WALL = ".", "#"


class GridMap:
    """Occupancy grid plus named places, parsed from a text file.

    Lines of '.' and '#' are the map; lines like '@corridor 5,3' name a cell.
    """

    def __init__(self, rows: list[str], places: dict[str, tuple[int, int]]) -> None:
        self.rows = rows
        self.h = len(rows)
        self.w = max(len(r) for r in rows) if rows else 0
        self.places = places

    @classmethod
    def load(cls, path: str | Path) -> "GridMap":
        rows: list[str] = []
        places: dict[str, tuple[int, int]] = {}
        for line in Path(path).read_text().splitlines():
            if not line.strip() or line.startswith("#!"):
                continue
            if line.startswith("@"):
                name, coords = line[1:].split()
                x, y = coords.split(",")
                places[name.lower()] = (int(x), int(y))
            else:
                rows.append(line)
        return cls(rows, places)

    def free(self, x: int, y: int) -> bool:
        if not (0 <= y < self.h and 0 <= x < len(self.rows[y])):
            return False
        return self.rows[y][x] != WALL

    def neighbours(self, x: int, y: int):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            nx, ny = x + dx, y + dy
            if not self.free(nx, ny):
                continue
            # No cutting corners diagonally through a wall gap.
            if dx and dy and not (self.free(x + dx, y) and self.free(x, y + dy)):
                continue
            yield nx, ny, math.hypot(dx, dy)

    def free_cells(self) -> list[tuple[int, int]]:
        return [(x, y) for y in range(self.h) for x in range(len(self.rows[y]))
                if self.rows[y][x] == FREE]


def a_star(grid: GridMap, start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    """Shortest path as a list of cells, or [] if the goal is unreachable."""
    if not grid.free(*goal) or not grid.free(*start):
        return []
    open_set = [(0.0, start)]
    came: dict[tuple, tuple] = {}
    cost = {start: 0.0}
    while open_set:
        _, cur = heapq.heappop(open_set)
        if cur == goal:
            path = [cur]
            while cur in came:
                cur = came[cur]
                path.append(cur)
            return path[::-1]
        for nx, ny, step in grid.neighbours(*cur):
            new = cost[cur] + step
            if new < cost.get((nx, ny), float("inf")):
                cost[(nx, ny)] = new
                came[(nx, ny)] = cur
                priority = new + math.hypot(goal[0] - nx, goal[1] - ny)
                heapq.heappush(open_set, (priority, (nx, ny)))
    return []


def simplify(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Drop collinear cells so the follower turns at corners, not every step."""
    if len(path) < 3:
        return path
    out = [path[0]]
    for prev, cur, nxt in zip(path, path[1:], path[2:]):
        if (cur[0] - prev[0], cur[1] - prev[1]) != (nxt[0] - cur[0], nxt[1] - cur[1]):
            out.append(cur)
    out.append(path[-1])
    return out


class Navigator:
    """Drives the robot along a planned path on its own thread.

    Every goal supersedes the last, and `cancel()` stops the robot immediately —
    a voice command must always be able to interrupt what the robot is doing.
    """

    ARRIVE_DIST = 0.35      # cells
    TURN_FIRST = 35.0       # deg: above this, turn in place before driving

    def __init__(self, grid: GridMap, motion: MotionController) -> None:
        self.grid = grid
        self.motion = motion
        self.path: list[tuple[int, int]] = []
        self.goal_name = ""
        self.status = "idle"
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._exploring = False

    # -- commands -------------------------------------------------------
    def go_to(self, name: str) -> str:
        place = self.grid.places.get(name.lower().strip())
        if place is None:
            known = ", ".join(sorted(self.grid.places)) or "nowhere yet"
            return f"I don't know where '{name}' is. I know: {known}."
        return self._start(place, name)

    def explore(self) -> str:
        self.cancel()
        self._exploring = True
        self._cancel.clear()
        self._thread = threading.Thread(target=self._explore_loop, daemon=True)
        self._thread.start()
        self.status = "exploring"
        return "Exploring."

    def cancel(self) -> str:
        self._exploring = False
        self._cancel.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self.motion.stop()
        self.status = "idle"
        self.path = []
        return "Stopped."

    def nearest_place(self) -> tuple[str, float]:
        """Closest named place to the robot, so it can say where it is in words."""
        p = self.motion.pose
        if not self.grid.places:
            return ("", float("inf"))
        name, cell = min(self.grid.places.items(),
                         key=lambda kv: p.distance_to(*kv[1]))
        return (name, p.distance_to(*cell))

    def remember_here(self, name: str) -> str:
        p = self.motion.pose
        cell = (int(round(p.x)), int(round(p.y)))
        if not self.grid.free(*cell):
            return "I can't name this spot, I seem to be inside a wall."
        self.grid.places[name.lower().strip()] = cell
        return f"Got it, this is the {name}."

    # -- internals ------------------------------------------------------
    def _start(self, cell: tuple[int, int], name: str) -> str:
        self.cancel()
        p = self.motion.pose
        start = (int(round(p.x)), int(round(p.y)))
        path = simplify(a_star(self.grid, start, cell))
        if not path:
            return f"I can't find a way to the {name} from here."
        with self._lock:
            self.path, self.goal_name = path, name
        self._cancel.clear()
        self._thread = threading.Thread(target=self._follow, args=(path,), daemon=True)
        self._thread.start()
        self.status = f"going to {name}"
        return f"Heading to the {name}."

    def _follow(self, path: list[tuple[int, int]]) -> bool:
        """Turn-then-drive along the waypoints. Returns True if it arrived."""
        for wx, wy in path[1:]:
            deadline = time.time() + 30
            while not self._cancel.is_set():
                if time.time() > deadline:
                    self.motion.stop()
                    self.status = "stuck"
                    return False
                pose = self.motion.pose
                if pose.distance_to(wx, wy) < self.ARRIVE_DIST:
                    break
                error = angle_diff(pose.bearing_to(wx, wy), pose.heading)
                turn = max(-120.0, min(120.0, error * 3.0))
                # Turn in place for big corrections, otherwise steer while moving.
                forward = 0.0 if abs(error) > self.TURN_FIRST else 0.9
                self.motion.set_velocity(forward, turn)
                time.sleep(0.05)
            if self._cancel.is_set():
                break
        self.motion.stop()
        if not self._cancel.is_set():
            # Don't announce "idle" between legs of an exploration.
            self.status = "exploring" if self._exploring else "idle"
            return True
        return False

    def _explore_loop(self) -> None:
        cells = self.grid.free_cells()
        while not self._cancel.is_set() and self._exploring:
            target = random.choice(cells)
            p = self.motion.pose
            path = simplify(a_star(self.grid, (int(round(p.x)), int(round(p.y))), target))
            if len(path) < 2:
                continue
            with self._lock:
                self.path = path
            self._follow(path)
            if self._cancel.is_set():
                return
            time.sleep(0.5)
