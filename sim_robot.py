"""Drive the whole brain from the keyboard, with a simulated body.

No mic, no speaker, no API spend on speech — just chat + tools, so you can test
what the robot *understands* and *does*. Type what you would have said.

  python sim_robot.py

  > what is pi to four digits            -> answers, no movement
  > go to the corridor                   -> plans a path and drives there
  > repeat what I say next               -> (no skill needed; history handles it)
  > explore freely                       -> wanders until told to stop
  > stop / where are you / map / quit
"""
from __future__ import annotations

import threading
import time

from robot import config
from robot.brain import Conversation
from robot.motion import SimMotion
from robot.nav import GridMap, Navigator
from robot.skills import Skills


def render(grid: GridMap, nav: Navigator) -> str:
    p = nav.motion.pose
    rx, ry = int(round(p.x)), int(round(p.y))
    path = {(x, y) for x, y in nav.path}
    arrow = "→↗↑↖←↙↓↘"[int(((p.heading % 360) + 22.5) // 45) % 8]
    out = []
    for y, row in enumerate(grid.rows):
        line = ""
        for x, ch in enumerate(row):
            if (x, y) == (rx, ry):
                line += arrow
            elif (x, y) in path:
                line += "·"
            elif (x, y) in grid.places.values():
                line += "◇"
            else:
                line += "█" if ch == "#" else " "
        out.append(line)
    legend = "  ".join(f"◇{n}" for n in sorted(grid.places))
    return "\n".join(out) + f"\n  {legend}\n  status: {nav.status}"


def watcher(grid: GridMap, nav: Navigator, stop: threading.Event) -> None:
    """Reprint the map while the robot is moving, so you can see it travel."""
    last = ""
    while not stop.is_set():
        if nav.status != "idle":
            frame = render(grid, nav)
            if frame != last:
                print("\n" + frame, flush=True)
                last = frame
        time.sleep(0.6)


def main() -> int:
    grid = GridMap.load(config.MAP_FILE)
    motion = SimMotion(*grid.places.get("desk", (1, 1)), heading=0)
    nav = Navigator(grid, motion)
    skills = Skills(nav)
    convo = Conversation()

    stop = threading.Event()
    threading.Thread(target=watcher, args=(grid, nav, stop), daemon=True).start()

    print(render(grid, nav))
    print("\nType what you would say. 'map' redraws, 'quit' exits.\n")

    try:
        while True:
            try:
                said = input("> ").strip()
            except EOFError:
                break
            if not said:
                continue
            if said in ("quit", "exit"):
                break
            if said == "map":
                print(render(grid, nav))
                continue

            def announce(name: str, result: str) -> None:
                print(f"  [{name}] {result}")

            spoken = []
            for sentence in convo.reply_stream(said, skills=skills, on_action=announce):
                spoken.append(sentence)
            print(f"  bot: {' '.join(spoken)}")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        nav.cancel()
        motion.close()
    print("\nBye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
