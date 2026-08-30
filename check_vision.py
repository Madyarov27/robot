"""Does the vision model actually see obstacles? Test it with your laptop webcam.

This is the gate for buying a camera. If the model can't reliably tell "clear
floor ahead" from "chair leg in the way" through a webcam, it won't do it
through a Pi camera either, and the whole navigation plan needs rethinking
before you spend money on one.

  python check_vision.py                      # one decision, then quits
  python check_vision.py --loop               # keeps looking every few seconds
  python check_vision.py --goal "reach the kitchen"

Hold the laptop low — near floor height — and point it at real things: an open
doorway, a wall, a chair leg, a person's feet, a doorway with a step.
Grade each answer yourself. That is the whole point.
"""
from __future__ import annotations

import argparse
import time

from robot import config, vision


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", default="reach the corridor")
    ap.add_argument("--loop", action="store_true", help="keep deciding until Ctrl-C")
    ap.add_argument("--every", type=float, default=4.0, help="seconds between looks")
    ap.add_argument("--save", metavar="DIR", help="write each frame here to review later")
    args = ap.parse_args()

    try:
        cam = vision.WebcamCamera()
    except Exception as exc:
        print(f"Camera unavailable: {exc}")
        return 1

    print(f"model: {config.VISION_MODEL}   goal: {args.goal}")
    print("Point the camera at something and grade the answer yourself.\n")

    recent: list[str] = []
    n = 0
    try:
        while True:
            n += 1
            frame = cam.capture()
            t = time.perf_counter()
            d = vision.decide(frame, args.goal, recent)
            ms = (time.perf_counter() - t) * 1000
            recent.append(f"{d['action']} {d['amount']:g}")

            if args.save:
                import os
                os.makedirs(args.save, exist_ok=True)
                path = f"{args.save}/look_{n:03d}.jpg"
                frame.save(path, quality=85)

            print(f"[{n}] {ms:.0f} ms · {d['_usage']} tok · {d['_bytes'] // 1024} KB")
            print(f"    sees   : {d['see']}")
            print(f"    action : {d['action']} {d['amount']:g}")
            print(f"    reason : {d['reason']}\n")

            if not args.loop:
                break
            time.sleep(args.every)
    except KeyboardInterrupt:
        pass
    finally:
        cam.close()

    print("Grade it: did it flag real obstacles, and did it stay sane over several looks?")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
