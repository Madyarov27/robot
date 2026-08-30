"""Seeing, and deciding what to do about it.

No LiDAR and no map: the robot takes a picture, a vision model reads it, and
returns one movement decision. That call costs seconds and money, so it can
never sit inside a control loop — it runs at walking pace and hands short
motion bursts to the 20 Hz controller, which is why `motion.py` was built
independent of the API in the first place.

Cameras are pluggable: a webcam while you wait for hardware, picamera2 on the
robot, a still image for tests.
"""
from __future__ import annotations

import base64
import io
import json
import time

from PIL import Image

from . import config
from .brain import client

# Vision cost and latency scale with pixels. This is plenty to tell a corridor
# from a kitchen, and keeps each frame well under 50 KB.
FRAME_W, FRAME_H = 512, 384
JPEG_QUALITY = 70

ACTIONS = ("forward", "left", "right", "back", "stop", "arrived", "blocked")

_DECISION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "movement_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "see": {"type": "string", "description": "One short sentence: what is in view."},
                "action": {"type": "string", "enum": list(ACTIONS)},
                "amount": {
                    "type": "number",
                    "description": "Metres to drive for forward/back, or degrees to turn for left/right.",
                },
                "reason": {"type": "string", "description": "One short sentence of justification."},
            },
            "required": ["see", "action", "amount", "reason"],
            "additionalProperties": False,
        },
    },
}

_SYSTEM = (
    "You are the eyes of a small spherical robot about 15 cm tall, rolling on the floor "
    "of a home. The camera sits low, near floor level. You are given the current view and "
    "a goal. Return exactly one next movement.\n"
    "Rules: prefer small steps — at most 1 metre forward, at most 60 degrees per turn. "
    "Never drive into an obstacle, a wall, a step, or a person's feet. If the way ahead is "
    "blocked, turn instead. Use 'arrived' only when the goal is clearly reached. Use "
    "'blocked' if there is no safe move at all."
)


class Camera:
    def capture(self) -> Image.Image:
        raise NotImplementedError

    def close(self) -> None:
        pass


class WebcamCamera(Camera):
    """Laptop webcam — lets you test the whole loop before the Pi camera lands."""

    def __init__(self, index: int = 0) -> None:
        import cv2

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            raise RuntimeError(
                "Could not open the webcam. On macOS grant camera access under "
                "System Settings > Privacy & Security > Camera."
            )

    def capture(self) -> Image.Image:
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("Webcam read failed.")
        rgb = self._cv2.cvtColor(frame, self._cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    def close(self) -> None:
        self._cap.release()


class PiCamera(Camera):
    """Raspberry Pi Camera Module via picamera2 (Pi only).

    NOTE: the Pi Zero 2 W's CSI connector is the narrow 22-pin type. A standard
    15-pin camera ribbon will NOT fit — you need the Zero-specific cable.
    """

    def __init__(self) -> None:
        from picamera2 import Picamera2

        self._cam = Picamera2()
        self._cam.configure(
            self._cam.create_still_configuration(main={"size": (FRAME_W, FRAME_H)})
        )
        self._cam.start()
        time.sleep(1.5)  # let auto-exposure settle

    def capture(self) -> Image.Image:
        return Image.fromarray(self._cam.capture_array()).convert("RGB")

    def close(self) -> None:
        self._cam.stop()


class FileCamera(Camera):
    """A fixed image, for testing the decision layer without any hardware."""

    def __init__(self, path: str) -> None:
        self._img = Image.open(path).convert("RGB")

    def capture(self) -> Image.Image:
        return self._img.copy()


def encode(img: Image.Image) -> tuple[str, int]:
    """Downscale and JPEG-encode a frame; returns (data-url, bytes)."""
    img = img.convert("RGB")
    img.thumbnail((FRAME_W, FRAME_H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    raw = buf.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode(), len(raw)


def decide(img: Image.Image, goal: str, recent: list[str] | None = None) -> dict:
    """Ask the vision model for one movement. Returns the parsed decision."""
    url, nbytes = encode(img)
    context = ""
    if recent:
        # Without this the robot happily turns left forever.
        context = "\nYour last few moves were: " + "; ".join(recent[-4:]) + "."
    response = client().chat.completions.create(
        model=config.VISION_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Goal: {goal}.{context}"},
                    {"type": "image_url", "image_url": {"url": url, "detail": "low"}},
                ],
            },
        ],
        max_tokens=200,
        response_format=_DECISION_SCHEMA,
    )
    out = json.loads(response.choices[0].message.content)
    out["_bytes"] = nbytes
    out["_usage"] = response.usage.total_tokens if response.usage else 0
    return out
