"""Measure where the milliseconds go, and whether streaming is worth it.

Isolates the three API round-trips — no mic, no speaker, so the numbers are
network and API only. Playback is deterministic once audio starts flowing; the
only latency a person feels is the gap before it does.

  python bench_latency.py          # 3 runs
  python bench_latency.py 5
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

from robot import brain, config

SAMPLE = Path("bench_sample.wav")
SAMPLE_TEXT = "What is it like rolling around on the floor all day?"


def sample_wav() -> bytes:
    """A fixed spoken utterance, so STT timing isn't confounded by what you said."""
    if SAMPLE.exists():
        return SAMPLE.read_bytes()
    print(f"Generating a test utterance ({SAMPLE})...")
    import io
    import wave

    pcm = b"".join(brain._tts_chunks(SAMPLE_TEXT))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.TTS_SAMPLERATE)
        w.writeframes(pcm)
    SAMPLE.write_bytes(buf.getvalue())
    return buf.getvalue()


def _ms(t0: float) -> float:
    return (time.perf_counter() - t0) * 1000


def one_run(wav: bytes) -> dict[str, float]:
    out: dict[str, float] = {}

    t0 = time.perf_counter()
    heard = brain.transcribe(wav)
    out["stt"] = _ms(t0)

    # Streaming chat: when does the first sentence become speakable?
    convo = brain.Conversation()
    t0 = time.perf_counter()
    first_sentence = None
    for sentence in convo.reply_stream(
        heard, on_first_token=lambda: out.setdefault("_tok", _ms(t0))
    ):
        if first_sentence is None:
            first_sentence = sentence
            out["chat_first_sentence"] = _ms(t0)
    out["chat_full"] = _ms(t0)
    out["chat_first_token"] = out.pop("_tok", out["chat_full"])

    # TTS: time to the first byte of audio, for one sentence vs the whole reply.
    for label, text in (("tts_sentence", first_sentence), ("tts_full", convo.last_reply)):
        t0 = time.perf_counter()
        for _ in brain._tts_chunks(text):
            break
        out[label] = _ms(t0)

    out["batched_ttfa"] = out["stt"] + out["chat_full"] + out["tts_full"]
    out["streaming_ttfa"] = out["stt"] + out["chat_first_sentence"] + out["tts_sentence"]
    return out


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    brain.warmup()  # measure steady state, not the TLS handshake
    wav = sample_wav()
    print(f"models: stt={config.STT_MODEL} chat={config.CHAT_MODEL} tts={config.TTS_MODEL}")
    print(f"{runs} runs...\n")

    results = []
    for i in range(runs):
        r = one_run(wav)
        results.append(r)
        print(f"  run {i + 1}: to-first-audio  batched {r['batched_ttfa']:.0f}ms"
              f"   streaming {r['streaming_ttfa']:.0f}ms")

    def med(k: str) -> float:
        return statistics.median(r[k] for r in results)

    print("\n  median stage times")
    for key, label in [
        ("stt", "transcription"),
        ("chat_first_token", "chat, first token"),
        ("chat_first_sentence", "chat, first sentence"),
        ("chat_full", "chat, full reply"),
        ("tts_sentence", "tts first byte (one sentence)"),
        ("tts_full", "tts first byte (whole reply)"),
    ]:
        print(f"    {label:32} {med(key):7.0f} ms")

    b, s = med("batched_ttfa"), med("streaming_ttfa")
    print(f"\n  TIME TO FIRST AUDIO   batched {b:.0f} ms   streaming {s:.0f} ms")
    saved = b - s
    print(f"  streaming saves {saved:.0f} ms ({saved / b * 100:.0f}%)")
    if saved < 120:
        print("  -> under ~120ms is not perceptible; ROBOT_STREAM=0 is fine and simpler.")
    else:
        print("  -> worth keeping streaming on (the default).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
