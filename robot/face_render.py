"""Draws the face as a 240x240 PIL image — the GC9A01's exact geometry.

Everything here is resolution- and library-correct for the real display: the Pi
drivers (adafruit_rgb_display.gc9a01, luma.lcd) take a PIL Image directly, so
this module ports to hardware unchanged. Only the *sink* differs — a window on
the laptop, an SPI bus on the robot.
"""
from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, fields, replace

from PIL import Image, ImageDraw

from .face import FaceState

SIZE = 240                     # GC9A01 is 240x240 round
CENTER = SIZE / 2
BG = (6, 8, 12)
EYE = (86, 220, 255)
EYE_DIM = (40, 110, 130)
ERROR_COLOR = (255, 96, 96)

# Oversampling factor for the eye edges. 3 is smooth; drop to 2 on the Pi Zero
# if frames get tight — it is the single most expensive knob in the renderer.
SUPERSAMPLE = int(os.getenv("ROBOT_FACE_SUPERSAMPLE", "3"))


@dataclass
class Pose:
    """Every animatable quantity. Poses are interpolated, so all fields are floats."""

    eye_w: float = 46
    eye_h: float = 58
    eye_r: float = 16          # corner radius
    gap: float = 78            # horizontal distance between eye centres
    eye_y: float = 108         # eye centre, from top
    tilt_l: float = 0          # degrees, positive = counter-clockwise
    tilt_r: float = 0
    squint_r: float = 1.0      # right-eye height scale; asymmetry reads as expression
    mouth_w: float = 0         # 0 = no mouth drawn
    mouth_open: float = 0      # 0..1


POSES = {
    FaceState.BOOTING:   Pose(eye_h=4, eye_r=2, eye_w=40),
    FaceState.IDLE:      Pose(),
    FaceState.LISTENING: Pose(eye_w=54, eye_h=70, eye_r=20, eye_y=104, gap=82),
    FaceState.THINKING:  Pose(eye_w=44, eye_h=34, eye_y=96, tilt_l=-6, tilt_r=6),
    FaceState.TALKING:   Pose(eye_h=56, mouth_w=54, mouth_open=0.15),
    FaceState.CONFUSED:  Pose(eye_w=42, eye_h=58, eye_r=10, tilt_l=-20, tilt_r=14,
                              squint_r=0.42, eye_y=106, mouth_w=34, mouth_open=0.45),
    FaceState.ERROR:     Pose(eye_w=44, eye_h=44, eye_y=106),
}

_NUMERIC = [f.name for f in fields(Pose)]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _blend(a: Pose, b: Pose, t: float) -> Pose:
    out = {}
    for n in _NUMERIC:
        av, bv = getattr(a, n), getattr(b, n)
        out[n] = bv if abs(bv - av) < 0.25 else _lerp(av, bv, t)
    return Pose(**out)


_EYE_CACHE: dict[tuple, Image.Image] = {}
_EYE_CACHE_MAX = 512


def _rounded_eye(w: float, h: float, r: float, tilt: float, color) -> Image.Image:
    """One eye, oversampled then rotated so the edges stay smooth.

    Memoised on integer geometry: poses settle and blinks repeat the same
    heights, so in steady state this is a dict lookup instead of a resample.
    """
    key = (max(2, int(w)), max(2, int(h)), int(r), int(round(tilt)), color, SUPERSAMPLE)
    hit = _EYE_CACHE.get(key)
    if hit is not None:
        return hit

    ss = SUPERSAMPLE
    w_i, h_i = key[0], key[1]
    pad = int(max(w_i, h_i) * 0.6)
    box = (w_i + pad * 2, h_i + pad * 2)
    img = Image.new("RGBA", (box[0] * ss, box[1] * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [pad * ss, pad * ss, (pad + w_i) * ss, (pad + h_i) * ss],
        radius=max(1, min(r, w_i / 2, h_i / 2)) * ss,
        fill=color + (255,),
    )
    img = img.resize(box, Image.LANCZOS)
    if abs(tilt) > 0.5:
        img = img.rotate(tilt, resample=Image.BICUBIC, expand=False)

    if len(_EYE_CACHE) >= _EYE_CACHE_MAX:
        _EYE_CACHE.clear()
    _EYE_CACHE[key] = img
    return img


class FaceAnimator:
    """Holds the pose being eased toward, plus blink and gaze timers."""

    def __init__(self, state: FaceState = FaceState.BOOTING) -> None:
        self.state = state
        self.pose = replace(POSES[state])
        self.t = 0.0
        self._blink_at = 2.0
        self._blink_phase = -1.0     # <0 = not blinking
        self._gaze = [0.0, 0.0]
        self._gaze_target = [0.0, 0.0]
        self._gaze_at = 1.5
        self.level = 0.0             # 0..1 speech loudness, drives the mouth

    def set_state(self, state: FaceState) -> None:
        self.state = state

    # -- per-frame update ------------------------------------------------
    def _tick_blink(self, dt: float) -> float:
        """Returns an eye-height multiplier. Blinks are a fast down-up ramp."""
        if self._blink_phase >= 0:
            self._blink_phase += dt
            half = 0.06
            if self._blink_phase >= half * 2:
                self._blink_phase = -1.0
                return 1.0
            # 0 -> closed -> open
            x = self._blink_phase / half
            closed = 1 - abs(1 - x)
            return 1.0 - 0.94 * closed
        if self.t >= self._blink_at:
            self._blink_phase = 0.0
            self._blink_at = self.t + random.uniform(2.4, 6.5)
        return 1.0

    def _tick_gaze(self, dt: float) -> tuple[float, float]:
        if self.t >= self._gaze_at:
            self._gaze_at = self.t + random.uniform(1.2, 3.4)
            reach = 9 if self.state == FaceState.IDLE else 4
            self._gaze_target = [random.uniform(-reach, reach), random.uniform(-reach * 0.5, reach * 0.5)]
        k = min(1.0, dt * 6)
        self._gaze[0] = _lerp(self._gaze[0], self._gaze_target[0], k)
        self._gaze[1] = _lerp(self._gaze[1], self._gaze_target[1], k)
        return self._gaze[0], self._gaze[1]

    def frame(self, dt: float) -> Image.Image:
        self.t += dt
        # Ease toward the target pose so state changes never snap.
        self.pose = _blend(self.pose, POSES[self.state], min(1.0, dt * 9))

        p = self.pose
        blink = self._tick_blink(dt)
        gx, gy = self._tick_gaze(dt)

        if self.state == FaceState.THINKING:      # slow searching drift upward
            gx += math.sin(self.t * 1.7) * 7
            gy += math.sin(self.t * 0.9) * 2
        if self.state == FaceState.LISTENING:     # subtle attentive pulse
            blink *= 1.0 + math.sin(self.t * 3.4) * 0.03

        img = Image.new("RGB", (SIZE, SIZE), BG)
        color = ERROR_COLOR if self.state == FaceState.ERROR else EYE

        if self.state == FaceState.ERROR:
            self._draw_x_eyes(img, p, gx, gy, color)
        else:
            for sign, tilt, scale in ((-1, p.tilt_l, 1.0), (1, p.tilt_r, p.squint_r)):
                eye = _rounded_eye(
                    p.eye_w, max(2.0, p.eye_h * blink * scale), p.eye_r, tilt, color
                )
                cx = CENTER + sign * p.gap / 2 + gx
                cy = p.eye_y + gy
                img.paste(eye, (int(cx - eye.width / 2), int(cy - eye.height / 2)), eye)

        self._draw_mouth(img, p, gx, color)
        _mask_to_circle(img)
        return img

    def _draw_x_eyes(self, img, p: Pose, gx: float, gy: float, color) -> None:
        d = ImageDraw.Draw(img)
        for sign in (-1, 1):
            cx = CENTER + sign * p.gap / 2 + gx
            cy = p.eye_y + gy
            r = p.eye_w / 2
            d.line([cx - r, cy - r, cx + r, cy + r], fill=color, width=9)
            d.line([cx - r, cy + r, cx + r, cy - r], fill=color, width=9)

    def _draw_mouth(self, img, p: Pose, gx: float, color) -> None:
        if p.mouth_w < 3:
            return
        openness = p.mouth_open
        if self.state == FaceState.TALKING:
            openness = max(openness, self.level)
        h = 5 + openness * 34
        w = p.mouth_w * (1.0 + openness * 0.25)
        cx, cy = CENTER + gx * 0.4, 176.0
        ImageDraw.Draw(img).rounded_rectangle(
            [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
            radius=min(h / 2, 12),
            fill=EYE_DIM if self.state == FaceState.CONFUSED else color,
        )


_CORNER_MASK: Image.Image | None = None


def _mask_to_circle(img: Image.Image) -> None:
    """The panel is round — black out the corners so the laptop preview doesn't lie."""
    global _CORNER_MASK
    if _CORNER_MASK is None:
        ss = Image.new("L", (SIZE * 2, SIZE * 2), 255)
        ImageDraw.Draw(ss).ellipse([0, 0, SIZE * 2 - 1, SIZE * 2 - 1], fill=0)
        _CORNER_MASK = ss.resize((SIZE, SIZE), Image.LANCZOS)
    img.paste((0, 0, 0), (0, 0), _CORNER_MASK)
