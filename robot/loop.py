"""The main voice loop: record -> Whisper -> Chat -> TTS -> play, forever.

Run with:  python -m robot.loop

With the face window on (the default) pygame owns the main thread — macOS
insists on it — and the conversation runs on a worker. ROBOT_FACE=console
drops the window and keeps everything on one thread.
"""
from __future__ import annotations

import os
import sys
import threading
import time

from . import audio_io, config
from .brain import Conversation, speak, speak_stream, transcribe, warmup
from .face import ConsoleFace, Face, FaceState
from .timing import TurnTimer


def make_face() -> Face:
    """Windowed face unless asked otherwise; falls back if there's no display."""
    if os.getenv("ROBOT_FACE", "window").lower() == "console":
        return ConsoleFace()
    try:
        from .face_window import WindowFace

        return WindowFace()
    except Exception as exc:
        print(f"(no face window: {exc}; using console face)", file=sys.stderr)
        return ConsoleFace()


def converse(face: Face, stop: threading.Event) -> None:
    """One turn after another until `stop` is set. Runs off the main thread."""
    convo = Conversation()
    set_level = getattr(face, "set_level", None)
    streaming = os.getenv("ROBOT_STREAM", "1").lower() not in ("0", "false", "no")

    # Overlap the TLS handshake with noise calibration; both take ~0.5 s.
    threading.Thread(target=warmup, daemon=True).start()

    print("Calibrating to room noise — stay quiet for half a second...")
    threshold = audio_io.calibrate_noise()
    print(f"Speech threshold: {threshold:.0f} (int16 RMS)")
    print(f"Ready ({'streaming' if streaming else 'batched'} reply). Just talk. Ctrl-C to stop.\n")

    while not stop.is_set():
        face.set(FaceState.IDLE)
        try:
            audio = audio_io.record_utterance(
                threshold,
                on_speech_start=lambda: face.set(FaceState.LISTENING),
                stop=stop,
            )
            if audio is None:
                continue

            # The clock starts the moment you stop talking — that gap is the
            # only latency a person actually perceives.
            timer = TurnTimer()
            face.set(FaceState.THINKING)

            audio, gain = audio_io.normalize(audio)
            if gain > 1.05:
                timer.marks.append(("gain x%.1f" % gain, timer.marks[-1][1] if timer.marks else 0.0))
            heard = transcribe(audio_io.to_wav_bytes(audio))
            timer.mark("stt")
            if not heard:
                face.set(FaceState.CONFUSED)
                time.sleep(0.8)
                continue
            print(f"  you : {heard}")

            def talking() -> None:
                timer.mark("first-audio")
                face.set(FaceState.TALKING)

            if streaming:
                sentences = convo.reply_stream(
                    heard, on_first_token=lambda: timer.mark("chat-first-token")
                )
                speak_stream(sentences, on_first_audio=talking, on_level=set_level)
                print(f"  bot : {convo.last_reply}")
            else:
                answer = convo.reply(heard)
                timer.mark("chat")
                print(f"  bot : {answer}")
                speak(answer, on_first_audio=talking, on_level=set_level)

            timer.mark("speech")
            timer.print()
        except KeyboardInterrupt:
            break
        except Exception as exc:  # keep the robot alive; one bad turn isn't fatal
            face.set(FaceState.ERROR)
            print(f"  !! {type(exc).__name__}: {exc}", file=sys.stderr)
            time.sleep(1.5)
            continue

        # Let the speaker settle so the mic doesn't retrigger on our own voice.
        time.sleep(config.SPEAK_COOLDOWN_S)

    stop.set()


def main() -> int:
    face = make_face()
    stop = threading.Event()

    if hasattr(face, "run_until"):
        worker = threading.Thread(target=converse, args=(face, stop), daemon=True)
        worker.start()
        face.run_until(stop)          # main thread, as Cocoa requires
    else:
        try:
            converse(face, stop)
        except KeyboardInterrupt:
            stop.set()

    print("\nBye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
