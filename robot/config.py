"""Central config. Everything overridable by env so the Pi port is a .env change."""
import os

from dotenv import load_dotenv

load_dotenv()

# --- OpenAI ---
API_KEY = os.getenv("OPENAI_API_KEY")
CHAT_MODEL = os.getenv("ROBOT_CHAT_MODEL", "gpt-4.1-mini")  # ~270 ms faster to first token than gpt-4o-mini
STT_MODEL = os.getenv("ROBOT_STT_MODEL", "gpt-4o-mini-transcribe")
VISION_MODEL = os.getenv("ROBOT_VISION_MODEL", "gpt-4.1-mini")
TTS_MODEL = os.getenv("ROBOT_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("ROBOT_TTS_VOICE", "ballad")
# Steers delivery, not content. Only honoured by gpt-4o-mini-tts.
TTS_INSTRUCTIONS = os.getenv(
    "ROBOT_TTS_INSTRUCTIONS",
    "Speak like a small, curious, cheerful robot. Warm and quick, never sluggish.",
)
LANGUAGE = os.getenv("ROBOT_LANGUAGE") or None  # e.g. "en", "ru", "uz"; None = autodetect

SYSTEM_PROMPT = os.getenv(
    "ROBOT_SYSTEM_PROMPT",
    "You are a small spherical rolling robot with a friendly digital face, and "
    "you can drive around the house. Use your tools to move; never claim to have "
    "moved without calling one. Answer ordinary questions directly and briefly. "
    "You are speaking out loud, so keep replies to one or two short sentences. "
    "No markdown, no lists, no emoji, no stage directions. Be warm and a little playful.",
)
MAX_HISTORY_TURNS = int(os.getenv("ROBOT_MAX_HISTORY_TURNS", "12"))
MAP_FILE = os.getenv("ROBOT_MAP", "sim_house.txt")

# --- Audio devices (None = system default; on the Pi set these to the I2S card) ---
def _dev(name: str):
    v = os.getenv(name)
    if not v:
        return None
    return int(v) if v.lstrip("-").isdigit() else v


INPUT_DEVICE = _dev("ROBOT_INPUT_DEVICE")
OUTPUT_DEVICE = _dev("ROBOT_OUTPUT_DEVICE")

# --- Recording / voice activity ---
MIC_SAMPLERATE = int(os.getenv("ROBOT_MIC_SAMPLERATE", "16000"))  # Whisper wants >=16k
BLOCK_MS = 30                     # VAD frame size
START_TIMEOUT_S = float(os.getenv("ROBOT_START_TIMEOUT_S", "15"))   # wait for speech
SILENCE_HANG_S = float(os.getenv("ROBOT_SILENCE_HANG_S", "0.9"))    # end-of-turn silence
MIN_SPEECH_S = float(os.getenv("ROBOT_MIN_SPEECH_S", "0.35"))       # ignore coughs/clicks
MAX_UTTERANCE_S = float(os.getenv("ROBOT_MAX_UTTERANCE_S", "20"))   # hard cap
NOISE_MULTIPLIER = float(os.getenv("ROBOT_NOISE_MULTIPLIER", "3.5"))
NOISE_FLOOR = float(os.getenv("ROBOT_NOISE_FLOOR", "250"))          # int16 RMS, absolute min

# Cheap USB mics record very quietly, and quiet audio transcribes worse. Each
# utterance is lifted so its loudest moment sits near full scale.
MIC_NORMALIZE = os.getenv("ROBOT_MIC_NORMALIZE", "1").lower() not in ("0", "false", "no")
MIC_TARGET_PEAK = float(os.getenv("ROBOT_MIC_TARGET_PEAK", "0.85"))  # fraction of full scale
MIC_MAX_GAIN = float(os.getenv("ROBOT_MIC_MAX_GAIN", "12"))          # don't amplify silence

# --- Playback ---
TTS_SAMPLERATE = 24000  # fixed by the OpenAI pcm response format
SPEAK_COOLDOWN_S = float(os.getenv("ROBOT_SPEAK_COOLDOWN_S", "0.4"))  # avoid self-hearing
