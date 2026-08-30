"""The OpenAI half of the loop: speech -> text -> reply -> speech."""
from __future__ import annotations

import queue
import re
import threading
from typing import Iterable, Iterator

from openai import OpenAI

from . import config
from .audio_io import Speaker
from .skills import TOOLS

_MAX_TOOL_ROUNDS = 3

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not config.API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        _client = OpenAI(api_key=config.API_KEY, timeout=30.0, max_retries=2)
    return _client


def warmup() -> None:
    """Open the TLS connection before the first turn needs it.

    The handshake costs ~250-400 ms and httpx pools the connection afterwards,
    so paying it during startup instead of mid-conversation is free latency.
    """
    try:
        client().models.list()
    except Exception:
        pass  # a failed warmup must never stop the robot from starting


def transcribe(wav_bytes: bytes) -> str:
    kwargs = {"language": config.LANGUAGE} if config.LANGUAGE else {}
    result = client().audio.transcriptions.create(
        model=config.STT_MODEL,
        file=("speech.wav", wav_bytes, "audio/wav"),
        response_format="text",
        **kwargs,
    )
    # response_format="text" yields a bare string; other formats yield an object.
    text = result if isinstance(result, str) else result.text
    return text.strip()


class Conversation:
    """Chat history, trimmed so a long session can't grow unbounded on the Pi."""

    def __init__(self, system_prompt: str | None = None) -> None:
        self.system_prompt = system_prompt or config.SYSTEM_PROMPT
        self.messages: list[dict] = []
        self.last_reply = ""

    def reply(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        response = client().chat.completions.create(
            model=config.CHAT_MODEL,
            messages=[{"role": "system", "content": self.system_prompt}, *self.messages],
            max_tokens=120,
            temperature=0.8,
        )
        text = (response.choices[0].message.content or "").strip()
        self.messages.append({"role": "assistant", "content": text})
        self._trim()
        return text

    def reply_stream(self, user_text: str, on_first_token=None,
                     skills=None, on_action=None) -> Iterator[str]:
        """Yield the reply sentence by sentence as the model produces it.

        If `skills` is given the model may call a tool first; the tool runs,
        its result is fed back, and the spoken reply then streams as usual.
        Actions are dispatched to background threads, so the robot starts
        moving while it is still saying that it will.
        """
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(_MAX_TOOL_ROUNDS):
            text, tool_calls = yield from self._one_round(on_first_token, skills)
            if not tool_calls:
                self.last_reply = text
                self._trim()
                return
            self.messages.append({
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": c["args"]}}
                    for c in tool_calls
                ],
            })
            for call in tool_calls:
                result = skills.run(call["name"], call["args"])
                if on_action:
                    on_action(call["name"], result)
                self.messages.append({
                    "role": "tool", "tool_call_id": call["id"], "content": result,
                })
            on_first_token = None  # only the first round counts for latency

    def _one_round(self, on_first_token, skills):
        """One streamed completion. Yields sentences; returns (text, tool_calls)."""
        kwargs = {"tools": TOOLS, "tool_choice": "auto"} if skills else {}
        stream = client().chat.completions.create(
            model=config.CHAT_MODEL,
            messages=[{"role": "system", "content": self.system_prompt}, *self.messages],
            max_tokens=160,
            temperature=0.8,
            stream=True,
            **kwargs,
        )

        full, buf, first = [], "", True
        pending: dict[int, dict] = {}
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            for tc in (delta.tool_calls or []):
                slot = pending.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] += tc.function.name
                if tc.function and tc.function.arguments:
                    slot["args"] += tc.function.arguments
            piece = delta.content
            if not piece:
                continue
            if first:
                first = False
                if on_first_token:
                    on_first_token()
            full.append(piece)
            buf += piece
            sentence, buf = _split_sentence(buf)
            if sentence:
                yield sentence
        if buf.strip():
            yield buf.strip()

        text = "".join(full).strip()
        tool_calls = [pending[i] for i in sorted(pending)]
        if text and not tool_calls:
            self.messages.append({"role": "assistant", "content": text})
        return text, tool_calls

    def _trim(self) -> None:
        limit = config.MAX_HISTORY_TURNS * 2
        if len(self.messages) > limit:
            self.messages = self.messages[-limit:]


def speak(text: str, on_first_audio=None, on_level=None) -> None:
    """Stream TTS straight to the speaker so playback starts before it's generated."""
    kwargs = {}
    if config.TTS_MODEL.startswith("gpt-4o"):
        kwargs["instructions"] = config.TTS_INSTRUCTIONS

    first = True
    with Speaker(on_level=on_level) as speaker:
        with client().audio.speech.with_streaming_response.create(
            model=config.TTS_MODEL,
            voice=config.TTS_VOICE,
            input=text,
            response_format="pcm",  # 24 kHz mono s16le
            **kwargs,
        ) as response:
            for chunk in response.iter_bytes(2048):
                if first and chunk:
                    first = False
                    if on_first_audio:
                        on_first_audio()
                speaker.write(chunk)


# Require real whitespace after the punctuation: mid-stream the buffer ends
# after every token, so an "$" alternative splits "3.141" into "3." and "141".
_SENTENCE_END = re.compile(r"[.!?…]+\s+")
_MIN_SENTENCE = 12  # don't ship "Hi." to TTS on its own; the request overhead isn't worth it


def _split_sentence(buf: str) -> tuple[str | None, str]:
    """Peel one complete sentence off the front of the buffer, if there is one."""
    # Take the first break that yields a chunk worth its own TTS request — not
    # merely the first break, or "Hi. I roll around." never splits at all.
    for match in _SENTENCE_END.finditer(buf):
        if match.end() >= _MIN_SENTENCE:
            return buf[: match.end()].strip(), buf[match.end():]
    # A long clause with no end in sight: break at a comma so audio keeps flowing.
    if len(buf) > 140:
        cut = buf.rfind(", ", 0, 140)
        if cut > _MIN_SENTENCE:
            return buf[: cut + 1].strip(), buf[cut + 2:]
    return None, buf


def _tts_chunks(text: str) -> Iterator[bytes]:
    kwargs = {}
    if config.TTS_MODEL.startswith("gpt-4o"):
        kwargs["instructions"] = config.TTS_INSTRUCTIONS
    with client().audio.speech.with_streaming_response.create(
        model=config.TTS_MODEL,
        voice=config.TTS_VOICE,
        input=text,
        response_format="pcm",
        **kwargs,
    ) as response:
        yield from response.iter_bytes(2048)


def speak_stream(sentences: Iterable[str], on_first_audio=None, on_level=None) -> None:
    """Speak sentences back to back through one open output stream.

    A producer thread pulls sentences (which are themselves still arriving from
    the chat stream) and requests TTS for each, while the main thread drains PCM
    to the speaker. So sentence two is being synthesised while sentence one is
    still being heard, and the device is never reopened mid-reply — reopening is
    what makes naive per-sentence TTS sound gappy.
    """
    chunks: queue.Queue = queue.Queue(maxsize=256)
    error: list[BaseException] = []

    def produce() -> None:
        try:
            for sentence in sentences:
                if sentence.strip():
                    for chunk in _tts_chunks(sentence):
                        chunks.put(chunk)
        except BaseException as exc:  # surfaced on the consumer side
            error.append(exc)
        finally:
            chunks.put(None)

    producer = threading.Thread(target=produce, daemon=True)
    producer.start()

    first = True
    with Speaker(on_level=on_level) as speaker:
        while True:
            chunk = chunks.get()
            if chunk is None:
                break
            if first:
                first = False
                if on_first_audio:
                    on_first_audio()
            speaker.write(chunk)

    producer.join(timeout=5)
    if error:
        raise error[0]
