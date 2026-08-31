"""Conversational AI over the keyboard — no mic needed.

Type a request, the model answers briefly, and it speaks the reply out loud.
Same chat + TTS pipeline `robot.loop` uses — this just swaps the microphone
for your keyboard, so you can test real conversation on the Pi before the
mic arrives (and it stays useful afterward as a quick debug tool).

  python chat.py

Ctrl-C or an empty line to quit.
"""
from __future__ import annotations

from robot.brain import Conversation, speak_stream
from robot.timing import TurnTimer

# Kept separate from robot.loop's default prompt: no mention of tools or
# driving, since this script has no body attached — just a short-answer chat.
SYSTEM_PROMPT = (
    "You are a small robot with a friendly voice. Answer questions directly "
    "and briefly — one or two short sentences, spoken out loud. No markdown, "
    "no lists, no emoji, no stage directions. Be warm and a little playful."
)


def main() -> int:
    convo = Conversation(system_prompt=SYSTEM_PROMPT)
    print("Type a request. Ctrl-C or an empty line to quit.\n")

    try:
        while True:
            try:
                text = input("> ").strip()
            except EOFError:
                break
            if not text:
                break

            timer = TurnTimer()
            sentences = convo.reply_stream(
                text, on_first_token=lambda: timer.mark("first-token")
            )
            speak_stream(sentences, on_first_audio=lambda: timer.mark("first-audio"))
            timer.mark("done")

            print(f"  bot: {convo.last_reply}")
            timer.print()
    except KeyboardInterrupt:
        pass

    print("\nBye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
