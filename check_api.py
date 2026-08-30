"""Steps 1 & 2 — exercise chat, transcription and TTS one at a time.

  python check_api.py key     (auth + model availability; costs nothing)
  python check_api.py chat
  python check_api.py tts
  python check_api.py stt     (records you, prints the transcript)
  python check_api.py all
"""
import sys

from robot import audio_io, brain, config


def check_key() -> None:
    """Confirm the key authenticates and the three configured models exist."""
    key = config.API_KEY or ""
    print(f"key loaded: {key[:7]}...{key[-4:]}  ({len(key)} chars)")

    available = {m.id for m in brain.client().models.list()}
    print(f"auth OK — {len(available)} models visible on this account")

    fallbacks = {
        config.CHAT_MODEL: "gpt-4o-mini or gpt-4.1-mini",
        config.STT_MODEL: "whisper-1",
        config.TTS_MODEL: "tts-1",
    }
    missing = False
    for role, model in (
        ("chat", config.CHAT_MODEL),
        ("stt ", config.STT_MODEL),
        ("tts ", config.TTS_MODEL),
    ):
        if model in available:
            print(f"  {role}: {model}  OK")
        else:
            missing = True
            print(f"  {role}: {model}  NOT AVAILABLE -> set it in .env to {fallbacks[model]}")
    if missing:
        raise SystemExit("Fix the model names in .env before running the other checks.")


def check_chat() -> None:
    print(f"chat model: {config.CHAT_MODEL}")
    convo = brain.Conversation()
    print("bot:", convo.reply("Say hello and tell me what you are, in one sentence."))


def check_tts() -> None:
    print(f"tts model: {config.TTS_MODEL}  voice: {config.TTS_VOICE}")
    brain.speak(
        "Hello. I am a small round robot, and this is my voice.",
        on_first_audio=lambda: print("  audio started"),
    )
    print("done")


def check_stt() -> None:
    print(f"stt model: {config.STT_MODEL}")
    threshold = audio_io.calibrate_noise()
    print("Say something.")
    audio = audio_io.record_utterance(threshold, on_speech_start=lambda: print("  listening..."))
    if audio is None:
        print("Heard nothing.")
        return
    audio, gain = audio_io.normalize(audio)
    if gain > 1.05:
        print(f"  quiet mic — boosted x{gain:.1f}")
    print("heard:", brain.transcribe(audio_io.to_wav_bytes(audio)))


CHECKS = {"key": check_key, "chat": check_chat, "tts": check_tts, "stt": check_stt}


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = list(CHECKS) if which == "all" else [which]
    for name in names:
        if name not in CHECKS:
            print(f"unknown check: {name}. pick from {list(CHECKS)} or 'all'")
            return 2
        print(f"\n=== {name} ===")
        CHECKS[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
