"""Step 0 — prove the mic and speaker work. No API key, no network.

Records you until you stop talking, then plays it straight back.
"""
from robot import audio_io, config


def main() -> int:
    import sounddevice as sd

    print(sd.query_devices())
    print(f"\ninput={config.INPUT_DEVICE or 'default'}  output={config.OUTPUT_DEVICE or 'default'}")

    print("\nCalibrating — stay quiet...")
    threshold = audio_io.calibrate_noise()
    print(f"threshold = {threshold:.0f}")

    print("Say something.")
    audio = audio_io.record_utterance(threshold, on_speech_start=lambda: print("  hearing you..."))
    if audio is None:
        print("Heard nothing. Is the right mic selected? Try lowering ROBOT_NOISE_MULTIPLIER.")
        return 1

    import numpy as np
    peak = int(np.max(np.abs(audio.astype(np.int32))))
    pct = peak / 32767 * 100
    verdict = "good" if pct > 25 else "QUIET — raise gain in alsamixer, or lower ROBOT_NOISE_MULTIPLIER"
    print(f"Peak level: {pct:.0f}% of maximum  ({verdict})")
    _, gain = audio_io.normalize(audio)
    if gain > 1.05:
        print(f"  the loop would boost this x{gain:.1f} before sending it to Whisper")

    print(f"Captured {len(audio) / config.MIC_SAMPLERATE:.1f}s. Playing it back...")
    audio_io.play(audio, config.MIC_SAMPLERATE)
    print("If you heard yourself, audio is good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
