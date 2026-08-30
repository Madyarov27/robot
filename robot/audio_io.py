"""Mic capture with simple energy VAD, and low-latency PCM playback.

Deliberately uses only sounddevice + numpy so the exact same code runs on the Pi
Zero 2 W against an I2S mic/amp (ALSA) as on a laptop (CoreAudio).
"""
from __future__ import annotations

import io
import wave

import numpy as np
import sounddevice as sd

from . import config


def _rms(block: np.ndarray) -> float:
    if block.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(block.astype(np.float32)))))


def calibrate_noise(seconds: float = 0.5) -> float:
    """Sample ambient room noise and return an int16 RMS speech threshold."""
    frames = int(config.MIC_SAMPLERATE * seconds)
    audio = sd.rec(
        frames,
        samplerate=config.MIC_SAMPLERATE,
        channels=1,
        dtype="int16",
        device=config.INPUT_DEVICE,
    )
    sd.wait()
    return max(config.NOISE_FLOOR, _rms(audio[:, 0]) * config.NOISE_MULTIPLIER)


def record_utterance(threshold: float, on_speech_start=None, stop=None) -> np.ndarray | None:
    """Block until one utterance is captured. Returns int16 mono, or None.

    None means: nobody spoke before START_TIMEOUT_S, what we heard was too
    short to be speech, or `stop` (a threading.Event) was set mid-capture.
    """
    block_frames = int(config.MIC_SAMPLERATE * config.BLOCK_MS / 1000)
    blocks: list[np.ndarray] = []
    speaking = False
    silent_blocks = 0
    waited_blocks = 0

    hang_blocks = int(config.SILENCE_HANG_S * 1000 / config.BLOCK_MS)
    timeout_blocks = int(config.START_TIMEOUT_S * 1000 / config.BLOCK_MS)
    max_blocks = int(config.MAX_UTTERANCE_S * 1000 / config.BLOCK_MS)
    # Keep a little pre-roll so we don't clip the first consonant.
    preroll_blocks = int(300 / config.BLOCK_MS)
    preroll: list[np.ndarray] = []

    with sd.InputStream(
        samplerate=config.MIC_SAMPLERATE,
        channels=1,
        dtype="int16",
        blocksize=block_frames,
        device=config.INPUT_DEVICE,
    ) as stream:
        while True:
            if stop is not None and stop.is_set():
                return None
            block, overflowed = stream.read(block_frames)
            del overflowed  # a dropped frame here is not worth failing the turn over
            mono = block[:, 0]
            loud = _rms(mono) > threshold

            if not speaking:
                preroll.append(mono)
                if len(preroll) > preroll_blocks:
                    preroll.pop(0)
                if loud:
                    speaking = True
                    blocks = list(preroll)
                    if on_speech_start:
                        on_speech_start()
                else:
                    waited_blocks += 1
                    if waited_blocks > timeout_blocks:
                        return None
                continue

            blocks.append(mono)
            silent_blocks = 0 if loud else silent_blocks + 1
            if silent_blocks >= hang_blocks or len(blocks) >= max_blocks:
                break

    audio = np.concatenate(blocks)
    voiced_s = (len(blocks) - silent_blocks) * config.BLOCK_MS / 1000
    if voiced_s < config.MIN_SPEECH_S:
        return None
    return audio


def normalize(audio: np.ndarray) -> tuple[np.ndarray, float]:
    """Lift a quiet recording toward full scale. Returns (audio, gain applied).

    Peak-based rather than a fixed gain, so it adapts to whatever microphone is
    plugged in instead of needing to be tuned per device. Capped so that near
    silence isn't amplified into noise, and clipped so it can never wrap around.
    """
    if not config.MIC_NORMALIZE or audio.size == 0:
        return audio, 1.0
    peak = float(np.max(np.abs(audio.astype(np.int32))))
    if peak < 1:
        return audio, 1.0
    gain = min(config.MIC_MAX_GAIN, config.MIC_TARGET_PEAK * 32767.0 / peak)
    if gain <= 1.05:                      # already loud enough; leave it alone
        return audio, 1.0
    boosted = np.clip(audio.astype(np.float32) * gain, -32768, 32767)
    return boosted.astype(np.int16), gain


def to_wav_bytes(audio: np.ndarray, samplerate: int | None = None) -> bytes:
    """Wrap int16 mono PCM in a WAV container for the transcription endpoint."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(samplerate or config.MIC_SAMPLERATE)
        wav.writeframes(audio.tobytes())
    return buf.getvalue()


class Speaker:
    """Streaming sink for 24 kHz mono s16le PCM chunks from the TTS endpoint.

    Also reports a 0..1 loudness for each chunk it plays, so the face can move
    its mouth in step with the actual waveform instead of faking it on a timer.
    """

    def __init__(self, on_level=None) -> None:
        self._on_level = on_level
        self._stream = sd.RawOutputStream(
            samplerate=config.TTS_SAMPLERATE,
            channels=1,
            dtype="int16",
            device=config.OUTPUT_DEVICE,
        )
        self._tail = b""

    def __enter__(self) -> "Speaker":
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        # Flush any odd trailing byte's partner, then let the buffer drain.
        if self._stream.active:
            silence = b"\x00" * (2 * int(config.TTS_SAMPLERATE * 0.05))
            try:
                self._stream.write(silence)
            except sd.PortAudioError:
                pass
        self._stream.stop()
        self._stream.close()
        if self._on_level:
            self._on_level(0.0)

    def write(self, chunk: bytes) -> None:
        """Chunks arrive on arbitrary byte boundaries; frames must stay aligned."""
        data = self._tail + chunk
        usable = len(data) - (len(data) % 2)
        self._tail = data[usable:]
        if not usable:
            return
        payload = data[:usable]
        if self._on_level:
            samples = np.frombuffer(payload, dtype=np.int16)
            # Compress the range: speech RMS sits low, but the mouth should open wide.
            self._on_level(min(1.0, (_rms(samples) / 9000.0) ** 0.65))
        self._stream.write(payload)


def play(audio: np.ndarray, samplerate: int) -> None:
    """Blocking playback of an int16 mono array (used by the check scripts)."""
    sd.play(audio, samplerate=samplerate, device=config.OUTPUT_DEVICE)
    sd.wait()
