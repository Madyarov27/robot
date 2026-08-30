"""Laptop preview sink: shows the 240x240 face in a pygame window.

macOS (Cocoa) will abort the process if SDL creates its window off the main
thread, so the window owns the main thread and the conversation runs on a
worker. On the Pi this file is replaced by ~10 lines that push the same PIL
image over SPI, and that inversion goes away.
"""
from __future__ import annotations

import os
import threading

import pygame

from .face import Face, FaceState
from .face_render import SIZE, FaceAnimator

SCALE = int(os.getenv("ROBOT_FACE_SCALE", "2"))
FPS = int(os.getenv("ROBOT_FACE_FPS", "30"))


class WindowFace(Face):
    """Construct and pump this on the MAIN thread. `set`/`set_level` are safe
    to call from any thread — they only assign to the animator."""

    def __init__(self) -> None:
        super().__init__()
        self.animator = FaceAnimator(FaceState.BOOTING)
        pygame.init()
        self._screen = pygame.display.set_mode((SIZE * SCALE, SIZE * SCALE))
        pygame.display.set_caption("robot face — GC9A01 preview (240x240)")
        self._clock = pygame.time.Clock()
        self._closed = False

    def on_state(self, state: FaceState) -> None:
        self.animator.set_state(state)

    def set_level(self, level: float) -> None:
        """0..1 speech loudness — the mouth follows this while talking."""
        self.animator.level = max(0.0, min(1.0, level))

    def pump(self) -> bool:
        """Render one frame. Returns False once the window has been closed."""
        if self._closed:
            return False
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (
                event.type == pygame.KEYDOWN and event.key in (pygame.K_q, pygame.K_ESCAPE)
            ):
                self._closed = True
                return False

        dt = self._clock.tick(FPS) / 1000.0
        img = self.animator.frame(dt)
        surface = pygame.image.frombytes(img.tobytes(), img.size, "RGB")
        if SCALE != 1:
            surface = pygame.transform.smoothscale(surface, (SIZE * SCALE, SIZE * SCALE))
        self._screen.blit(surface, (0, 0))
        pygame.display.flip()
        return True

    def run_until(self, stop: threading.Event) -> None:
        """Main-thread render loop; ends when the window closes or `stop` is set."""
        try:
            while not stop.is_set():
                if not self.pump():
                    break
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
        pygame.quit()
