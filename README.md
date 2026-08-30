# Rolling robot — voice loop

Phase 1 of the spherical robot: the full `mic → Whisper → Chat → TTS → speaker` loop,
running on a laptop, written so that moving it to the Pi Zero 2 W is a `.env` change
rather than a rewrite.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then paste your OPENAI_API_KEY into .env
```

## Bring-up order

Each step fails loudly on its own, so you always know which piece is broken.

```bash
python check_audio.py     # 0. mic + speaker only — records you, plays it back. No API.
python check_api.py key   # 1a. auth + model availability. Costs nothing.
python check_api.py chat  # 1b. Chat Completions
python check_api.py stt   # 2a. transcription (records you, prints the transcript)
python check_api.py tts   # 2b. speech out
python preview_face.py    # 3. the face, no API calls — cycles every state
python -m robot.loop      # 4. the whole conversation loop, with the face
python bench_latency.py   # 5. where the milliseconds go (no mic needed)
python sim_robot.py       # 6. type commands, watch a simulated robot obey
```

## Layout

| file | role |
|---|---|
| [robot/config.py](robot/config.py) | every tunable, env-overridable |
| [robot/audio_io.py](robot/audio_io.py) | energy VAD capture, streaming PCM playback |
| [robot/brain.py](robot/brain.py) | the three OpenAI calls + chat history |
| [robot/face.py](robot/face.py) | face state machine |
| [robot/face_render.py](robot/face_render.py) | draws the face as a 240x240 PIL image |
| [robot/face_window.py](robot/face_window.py) | laptop preview window (the only file the Pi replaces) |
| [robot/timing.py](robot/timing.py) | per-turn stage timing |
| [robot/skills.py](robot/skills.py) | what the robot can *do*, as tool definitions |
| [robot/motion.py](robot/motion.py) | 20 Hz motion thread; sim body + real-motor seam |
| [robot/nav.py](robot/nav.py) | grid map + A* — the **simulator's** navigator |
| [robot/vision.py](robot/vision.py) | camera (webcam / picamera2 / file) + one vision decision |
| [robot/vision_nav.py](robot/vision_nav.py) | **the real navigator**: perceive → decide → act |
| [robot/loop.py](robot/loop.py) | the loop that ties them together |

## How a turn works

The mic runs continuously. `record_utterance` watches int16 RMS per 30 ms frame:
speech starts when a frame crosses the threshold (calibrated against room noise at
startup, `NOISE_MULTIPLIER × ambient`), and the turn ends after `SILENCE_HANG_S` of
quiet. A 300 ms pre-roll buffer is prepended so the first consonant isn't clipped.

TTS is requested as raw `pcm` and streamed into an open output stream, so the robot
starts talking before the sentence has finished generating. Chunks land on arbitrary
byte boundaries, so `Speaker.write` holds back a trailing odd byte to keep 16-bit
frames aligned.

## The face

`face_render.py` draws into a **240x240 PIL image — the GC9A01's exact geometry**,
corners masked black because the panel is round. That matters: the Pi display
drivers (`adafruit_rgb_display.gc9a01`, `luma.lcd`) accept a PIL image directly, so
the drawing code moves to hardware untouched. Only the sink changes — a pygame
window here, `disp.image(img)` there.

States ease into each other rather than snapping (`_blend` at ~9x dt), eyes blink on
a random 2.4-6.5 s timer and drift with a slow gaze wander, so an idle robot never
looks frozen.

**The mouth is driven by the actual audio.** `Speaker` computes RMS per 43 ms PCM
chunk as it plays and hands it to the face, so the mouth tracks real syllables
instead of a timer that only looks synced until you watch closely.

Render cost is ~9 ms/frame on this laptop. The Pi Zero 2 W is several times slower,
so if 30 fps doesn't hold there, drop `ROBOT_FACE_FPS` to 20 and the supersample
factor `ss` in `_rounded_eye` from 3 to 2.

### Threading

macOS aborts the process if SDL creates its window off the main thread. So the
window owns the main thread and the conversation runs on a worker — that's why
`converse()` takes a stop event and `record_utterance` checks it between 30 ms
blocks. `ROBOT_FACE=console` skips all of it and stays single-threaded.

## Understanding vs. doing

The model chooses between answering and acting. Questions ("what is pi to four
digits") never reach [robot/skills.py](robot/skills.py) — it just answers. Only
physical verbs become tool calls: `go_to`, `explore`, `stop`, `remember_here`,
`where_am_i`.

There is deliberately **no "repeat what I say next" skill**. That instruction is
already in the chat history, so the model does it natively on the following turn.
Modes you get for free are modes not worth building.

Actions dispatch to background threads, so the robot says "heading there now" and
starts moving *while* it says it.

## Navigation: seeing, not mapping

No LiDAR, no map. The robot photographs what is in front of it, a vision model
returns one movement, it moves a short distance, and it looks again.

Measured, `gpt-4.1-mini` at `detail: "low"`, 512x384 JPEG:

| | |
|---|---|
| per decision | **1.6-4.1 s**, ~600 tokens, ~5 KB frame |
| full cycle (look + move) | ~4.7 s |
| effective pace | ~0.1 m/s |

That cadence is the whole reason [robot/motion.py](robot/motion.py) runs its own
20 Hz thread: the robot must never be blind *and* coasting. Each decision buys one
short burst, then it stops and re-looks. `cancel()` lands in ~14 ms, so a spoken
"stop" always wins.

**Untested: perception quality.** The decision loop is verified end to end, but
only against synthetic scenes and a static image — which cannot tell you whether
the model reliably sees a real chair leg. Grant camera access (macOS: System
Settings > Privacy & Security > Camera) and `WebcamCamera` will test it for real,
today, before the Pi camera arrives.

[robot/nav.py](robot/nav.py) (grid + A*) is now the **simulator's** navigator. It
stays useful for exercising the skill layer with no camera and no API spend.

## Latency

Every turn prints its stage breakdown (`ROBOT_TIMING=0` to silence it), and
`bench_latency.py` measures the API round-trips with no mic involved.

Measured from Tashkent, warm connection, median of 4 runs:

| stage | ms |
|---|---|
| transcription | ~1085 |
| chat, first token | ~945 |
| chat, full reply | ~1397 |
| tts, first audio byte | ~890 |
| **total, to first audio** | **~2970 streaming / ~3340 batched** |

Three sequential REST round-trips, each ~1 s. Network RTT is only 82 ms, so this
is model time, not connectivity.

**What actually helped**

- *Connection warmup* (`brain.warmup()`, kicked off at startup alongside noise
  calibration): the TLS handshake costs 250-400 ms and used to sit inside the
  first turn. **~1200 ms off the first response.**
- *`gpt-4.1-mini` instead of `gpt-4o-mini`*: **~270 ms** faster to first token.
- *Sentence streaming* (`ROBOT_STREAM=0` to compare): **~230-370 ms**, less than
  hoped — see below.

**What didn't, so don't retry it**

- *Compressing audio before upload.* FLAC halves the payload (94 KB → 57 KB) and
  is **40% slower** — server-side decode costs more than the transfer saves.
  Payload size barely matters at all: 202 KB and 94 KB transcribe in the same time.
- *`whisper-1` or `gpt-4o-transcribe`*: both slower than `gpt-4o-mini-transcribe`.
- *`tts-1`*: **2.4 s** to first byte, twice as slow as `gpt-4o-mini-tts`. The
  older, cheaper model is not the faster one.

**Why streaming underdelivers here.** The system prompt caps replies at one or two
sentences, so there is rarely a second sentence to overlap — first-sentence and
full-reply times are only ~390 ms apart. Streaming pays off in proportion to reply
length, so if you relax the prompt to allow longer answers, streaming keeps
time-to-first-audio flat while the robot gets more interesting. That is the
argument for longer replies, not against streaming.

**The floor.** ~3 s is what a three-hop REST chain costs. Getting under a second
means collapsing it into one persistent connection — the Realtime API, which does
speech-to-speech over a WebSocket with server-side turn detection. That is a real
rewrite of `brain.py` and it costs more per minute, so it is a deliberate choice,
not a tweak.

## Tuning

- Robot never hears you → lower `ROBOT_NOISE_MULTIPLIER` (try 2.0).
- Robot triggers on room noise → raise it (try 5.0).
- Robot cuts you off mid-sentence → raise `ROBOT_SILENCE_HANG_S`.
- Wrong language transcribed → set `ROBOT_LANGUAGE=en` (or `ru` / `uz`).
- Face too small on screen → `ROBOT_FACE_SCALE=3`.
- Face stutters → `ROBOT_FACE_FPS=20`.

## Porting to the Pi

1. Same repo, same commands. `sounddevice` talks to ALSA there.
2. Swap `face_window.py` for an SPI sink — same `Face` interface, `disp.image(img)`.
3. `python check_audio.py` prints the device table — put the I2S card's index into
   `ROBOT_INPUT_DEVICE` / `ROBOT_OUTPUT_DEVICE` in `.env`.
4. If the I2S mic is 48 kHz-only, set `ROBOT_MIC_SAMPLERATE=48000` — WAV carries the
   rate, so transcription still works.

## Known limits (deliberate, for v1)

- **The robot can hear itself.** It simply doesn't listen while speaking, plus a
  `SPEAK_COOLDOWN_S` settle. Real barge-in needs echo cancellation (`speexdsp`) —
  worth it only once there's a real speaker in a real shell.
- **No wake word.** It answers any voice loud enough. A Pi Zero 2 W can run Porcupine
  or `openWakeWord` if that becomes annoying.
- **Chat waits for the full reply before speaking.** Replies are capped at ~2
  sentences so this is a few hundred ms. If it drags, stream the chat response and
  hand each finished sentence to `speak()`.
