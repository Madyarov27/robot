"""Type text, the robot speaks it. No mic needed — useful while the mic
search is still ongoing, and handy afterwards for testing TTS on its own.

  python say.py                     # interactive: type a line, hit enter, repeat
  python say.py "Hello there"       # one-shot: speak this and exit
"""
from __future__ import annotations

import sys

from robot.brain import speak


def main() -> int:
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        print(f"speaking: {text}")
        speak(text)
        return 0

    print("Type a line and press Enter to hear it. Ctrl-C or empty line to quit.\n")
    try:
        while True:
            text = input("> ").strip()
            if not text:
                break
            speak(text)
    except KeyboardInterrupt:
        pass
    print("\nBye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
