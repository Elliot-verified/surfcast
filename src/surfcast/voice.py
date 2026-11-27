"""Voice mode: listen on a microphone, recognise a surf spot, speak the forecast.

Speech recognition is done offline with Vosk (``pip install surfcast[voice]``),
constrained to a grammar built from the spot catalogue so a small model still
gets names like "Teahupo'o" right. Audio comes from ``arecord`` (ALSA) or a
file. Speech output prefers Piper, a neural text-to-speech engine that sounds
like a person (also in the ``[voice]`` extra), and falls back to
``espeak-ng``/``espeak`` when Piper is not installed.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import wave
import zipfile
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from surfcast.client import ForecastError, SurfForecastClient
from surfcast.format import render_table
from surfcast.models import Forecast, ForecastHour
from surfcast.spots import ALIASES, SPOTS, _normalize, find_spot

SAMPLE_RATE = 16000
CHUNK_BYTES = 4000  # 125 ms of 16 kHz mono 16-bit audio

DEFAULT_MODEL = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{DEFAULT_MODEL}.zip"
MODEL_DIR = Path(os.environ.get("SURFCAST_MODEL_DIR", Path.home() / ".cache" / "surfcast"))

DEFAULT_WAKE = "hey surf"

# Piper voices live on Hugging Face as <locale>-<name>-<quality>.onnx plus a .json config.
DEFAULT_VOICE = "en_US-lessac-medium"
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{path}"

COMPASS_WORDS = {"N": "north", "S": "south", "E": "east", "W": "west"}

# Words that mean "I'm talking to you" even without the wake phrase.
QUESTION_WORDS = {"what", "whats", "how", "hows", "tell", "give", "any"}
TOPIC_WORDS = {"waves", "surf", "surfing", "forecast", "report", "conditions", "swell"}
QUIT_WORDS = {"quit", "stop", "exit", "goodbye", "bye"}

Chunks = Iterable[bytes]
Speaker = Callable[[str], None]
Player = Callable[[bytes, int], None]  # (16-bit mono PCM, sample rate)


class Transcriber(Protocol):
    """Turns a stream of raw 16 kHz mono PCM chunks into finished utterances."""

    def transcribe(self, chunks: Chunks) -> Iterator[str]: ...


# --------------------------------------------------------------------------- audio sources


def mic_chunks(device: str | None = None) -> Iterator[bytes]:
    """Yield raw PCM from the default (or given) ALSA capture device via ``arecord``."""
    if shutil.which("arecord") is None:
        raise RuntimeError("arecord not found; install alsa-utils or use --audio FILE")
    cmd = ["arecord", "-q", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", "-t", "raw"]
    if device:
        cmd += ["-D", device]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    assert proc.stdout is not None
    try:
        while chunk := proc.stdout.read(CHUNK_BYTES):
            yield chunk
    finally:
        proc.terminate()


def file_chunks(path: str | Path) -> Iterator[bytes]:
    """Yield raw PCM from an audio file, resampling to 16 kHz mono with ffmpeg if needed."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found; it is needed to read audio files")
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar",
           str(SAMPLE_RATE), "-"]  # fmt: skip
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    assert proc.stdout is not None
    while chunk := proc.stdout.read(CHUNK_BYTES):
        yield chunk
    proc.wait()


# --------------------------------------------------------------------------- recognition


def grammar_phrases(wake: str | None = None) -> list[str]:
    """Words and phrases the recogniser should expect: spot names, aliases, questions, wake."""
    phrases = {
        "surf", "forecast", "what's", "whats", "what", "are", "the", "for", "at", "in",
        "please", "today", "tomorrow", "waves", "how", "how's", "hows", "is", "it", "like",
        "going", "to", "be", "looking", "right", "now", "this", "weekend", "tell", "me",
        "about", "give", "report", "conditions", "swell", "any", "good", "out", "there",
        "beach", "yes", "no", "quit", "stop", "thanks", "thank", "you",
    }  # fmt: skip
    for slug, spot in SPOTS.items():
        phrases.add(_normalize(spot.name))
        phrases.update(slug.split("-"))
        phrases.update(_normalize(a) for a in ALIASES.get(slug, []))
    if wake:
        phrases.add(_normalize(wake))
    phrases.discard("")
    return sorted(phrases) + ["[unk]"]


def _download(url: str, target: Path, log: Callable[[str], None], what: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"Downloading {what} to {target.parent} ...")
    tmp = target.with_suffix(target.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310
    tmp.replace(target)


def ensure_model(model_dir: str | Path | None = None, log: Callable[[str], None] = print) -> Path:
    """Return the Vosk model directory, downloading the small English model on first use."""
    if model_dir:
        path = Path(model_dir)
        if not path.is_dir():
            raise FileNotFoundError(f"model directory not found: {path}")
        return path
    path = MODEL_DIR / DEFAULT_MODEL
    if path.is_dir():
        return path
    archive = MODEL_DIR / f"{DEFAULT_MODEL}.zip"
    _download(MODEL_URL, archive, log, f"speech model ({DEFAULT_MODEL}, ~40 MB)")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(MODEL_DIR)
    archive.unlink()
    return path


@contextlib.contextmanager
def _quiet_stderr() -> Iterator[None]:
    """Hide Kaldi's C++ warnings (e.g. grammar words missing from the model vocabulary)."""
    sys.stderr.flush()
    saved = os.dup(2)
    try:
        with open(os.devnull, "wb") as devnull:
            os.dup2(devnull.fileno(), 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


class VoskTranscriber:
    """Offline recogniser backed by Vosk. Requires ``pip install surfcast[voice]``."""

    def __init__(
        self,
        model_dir: str | Path | None = None,
        grammar: list[str] | None = None,
        log: Callable[[str], None] = print,
    ) -> None:
        try:
            import vosk
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "voice mode needs the vosk package: pip install 'surfcast[voice]'"
            ) from exc
        vosk.SetLogLevel(-1)
        path = ensure_model(model_dir, log)
        with _quiet_stderr():
            model = vosk.Model(str(path))
            if grammar:
                self._rec = vosk.KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar))
            else:
                self._rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)

    def transcribe(self, chunks: Chunks) -> Iterator[str]:
        for chunk in chunks:
            if self._rec.AcceptWaveform(chunk):
                text = json.loads(self._rec.Result()).get("text", "").strip()
                if text:
                    yield text
        text = json.loads(self._rec.FinalResult()).get("text", "").strip()
        if text:
            yield text


# --------------------------------------------------------------------------- speech output


def voice_url(voice: str, suffix: str = ".onnx") -> str:
    """'en_US-lessac-medium' -> the Hugging Face URL of its .onnx (or .onnx.json) file."""
    try:
        locale, name, quality = voice.split("-")
    except ValueError:
        raise ValueError(f"voice must look like en_US-lessac-medium, got '{voice}'") from None
    lang = locale.split("_")[0]
    return VOICE_URL.format(path=f"{lang}/{locale}/{name}/{quality}/{voice}{suffix}")


def ensure_voice(voice: str | Path = DEFAULT_VOICE, log: Callable[[str], None] = print) -> Path:
    """Return the path of a Piper voice model, downloading it (~60 MB) on first use."""
    given = Path(voice)
    if given.suffix == ".onnx":
        if not given.is_file() or not given.with_suffix(".onnx.json").is_file():
            raise FileNotFoundError(f"voice model (and its .json) not found: {given}")
        return given
    model = MODEL_DIR / f"{voice}.onnx"
    config = MODEL_DIR / f"{voice}.onnx.json"
    if not config.is_file():
        _download(voice_url(str(voice), ".onnx.json"), config, log, f"voice config ({voice})")
    if not model.is_file():
        _download(voice_url(str(voice)), model, log, f"voice ({voice}, ~60 MB)")
    return model


def _pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def make_player(device: str | None = None) -> Player | None:
    """Return a function that plays 16-bit mono PCM through aplay (Linux) or afplay (macOS)."""
    if shutil.which("aplay"):

        def aplay(pcm: bytes, rate: int) -> None:
            cmd = ["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-c", "1", "-r", str(rate)]
            if device:
                cmd += ["-D", device]
            subprocess.run(cmd, input=pcm, check=False)

        return aplay
    if shutil.which("afplay"):  # pragma: no cover - macOS only

        def afplay(pcm: bytes, rate: int) -> None:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(_pcm_to_wav(pcm, rate))
            try:
                subprocess.run(["afplay", tmp.name], check=False)
            finally:
                os.unlink(tmp.name)

        return afplay
    return None


def load_piper_voice(voice: str | Path, log: Callable[[str], None] = print) -> Any | None:
    """Load a Piper voice, or return None (with a hint) when piper-tts is not installed."""
    try:
        from piper import PiperVoice
    except ImportError:
        log("Tip: pip install piper-tts for a natural-sounding voice (using espeak for now).")
        return None
    path = ensure_voice(voice, log)
    with _quiet_stderr():
        return PiperVoice.load(str(path))


def piper_speaker(piper_voice: Any, play: Player) -> Speaker:
    """Speak with a loaded Piper voice: synthesise the whole sentence, then play it."""

    def speak(text: str) -> None:
        chunks = list(piper_voice.synthesize(text))
        if chunks:
            play(b"".join(c.audio_int16_bytes for c in chunks), chunks[0].sample_rate)

    return speak


def espeak_speaker(device: str | None = None) -> Speaker | None:
    """Fallback speaker using espeak-ng/espeak, or None when neither is installed."""
    engine = shutil.which("espeak-ng") or shutil.which("espeak")
    if engine is None:
        return None

    def speak(text: str) -> None:
        if device:
            tts = subprocess.Popen([engine, "--stdout", text], stdout=subprocess.PIPE)
            subprocess.run(["aplay", "-q", "-D", device], stdin=tts.stdout, check=False)
            tts.wait()
        else:
            subprocess.run([engine, text], check=False)

    return speak


def make_speaker(
    device: str | None = None,
    enabled: bool = True,
    voice: str | Path = DEFAULT_VOICE,
    log: Callable[[str], None] = lambda text: print(text, file=sys.stderr),
) -> Speaker:
    """Return a function that speaks text aloud, or a no-op if TTS is unavailable/disabled.

    Prefers Piper (natural voice); falls back to espeak; silent if neither is present.
    """
    if not enabled:
        return lambda text: None
    player = make_player(device)
    if player is not None:
        try:
            piper_voice = load_piper_voice(voice, log)
        except (OSError, ValueError) as exc:
            log(f"Could not load voice '{voice}': {exc}. Falling back to espeak.")
            piper_voice = None
        if piper_voice is not None:
            return piper_speaker(piper_voice, player)
    fallback = espeak_speaker(device)
    if fallback is None:
        log("No text-to-speech engine found; install piper-tts or espeak-ng to hear replies.")
        return lambda text: None
    return fallback


# --------------------------------------------------------------------------- wording


def compass_words(label: str) -> str:
    """'WNW' -> 'west northwest'; '-' -> 'unknown'."""
    if not label or label == "-":
        return "unknown"
    if len(label) == 3:  # e.g. WNW -> W + NW
        return f"{COMPASS_WORDS[label[0]]} {compass_words(label[1:])}"
    return "".join(COMPASS_WORDS[c] for c in label)


def _whole(value: float) -> int:
    return max(1, round(value))


def _feet(lo: float, hi: float) -> str:
    """'2 to 3 feet', 'about 4 feet', 'about a foot', 'under a foot'."""
    if hi < 0.75:
        return "under a foot"
    a, b = _whole(lo), _whole(hi)
    if a == b:
        return "about a foot" if a == 1 else f"about {a} feet"
    return f"{a} to {b} feet"


def _swell_words(hour: ForecastHour) -> str:
    """'a 3 foot west northwest swell at 14 seconds'."""
    height = hour.swell_height_ft or 0.0
    size = "a little" if height < 0.75 else f"a {_whole(height)} foot"
    words = f"{size} {compass_words(hour.swell_compass)} swell"
    if hour.swell_period_s is not None:
        words += f" at {_whole(hour.swell_period_s)} seconds"
    return words


def size_words(height_ft: float) -> str:
    if height_ft < 1:
        return "pretty much flat"
    if height_ft < 2:
        return "tiny"
    if height_ft < 3:
        return "small"
    if height_ft < 5:
        return "fun sized"
    if height_ft < 8:
        return "solid"
    return "big"


def wind_words(knots: float) -> str:
    if knots < 5:
        return "almost calm"
    if knots < 10:
        return "light"
    if knots < 17:
        return "moderate"
    if knots < 25:
        return "breezy"
    return "strong"


def trend_words(heights: list[float]) -> str:
    """'building', 'dropping' or 'holding steady' across the day."""
    if len(heights) < 3:
        return "holding steady"
    third = max(1, len(heights) // 3)
    early = sum(heights[:third]) / third
    late = sum(heights[-third:]) / third
    if late - early >= 0.5 and late >= early * 1.2:
        return "building through the day"
    if early - late >= 0.5 and early >= late * 1.2:
        return "dropping through the day"
    return "holding steady"


def day_words(day: date, today: date | None = None) -> str:
    today = today or date.today()
    delta = (day - today).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return day.strftime("on %A")


def summarize(
    forecast: Forecast,
    hours: list[ForecastHour] | None = None,
    *,
    day_offset: int = 0,
    today: date | None = None,
) -> str:
    """A short, conversational spoken surf report for one day of the forecast."""
    hours = forecast.daylight() if hours is None else hours
    if not hours:
        return f"Sorry, I don't have any forecast hours for {forecast.spot.name}."
    days = sorted({h.time.date() for h in hours})
    day = days[min(day_offset, len(days) - 1)]
    chosen = [h for h in hours if h.time.date() == day]
    waves = [h.wave_height_ft for h in chosen if h.wave_height_ft is not None]
    swell = [h for h in chosen if h.swell_height_ft is not None]
    wind = [h for h in chosen if h.wind_speed_kts is not None]

    name = forecast.spot.name.split(" (")[0].split(",")[0]  # "Malibu (Surfrider)" -> "Malibu"
    lines = [f"Here's {name} {day_words(day, today)}."]
    if waves:
        lo, hi = min(waves), max(waves)
        sentence = f"It's looking {size_words(hi)}, {_feet(lo, hi)} and {trend_words(waves)}"
        if swell:
            mid = swell[len(swell) // 2]
            sentence += f", from {_swell_words(mid)}"
        lines.append(sentence + ".")
    if wind:
        mid = wind[len(wind) // 2]
        knots = mid.wind_speed_kts or 0.0
        lines.append(
            f"Wind is {wind_words(knots)}, around {_whole(knots)} knots"
            f" out of the {compass_words(mid.wind_compass)}."
        )
    if waves and wind:
        lines.append(verdict(max(waves), wind[len(wind) // 2].wind_speed_kts or 0.0))
    return " ".join(lines)


def verdict(height_ft: float, knots: float) -> str:
    """One hedged closing line; we don't know the beach's orientation, so no 'clean/blown out'."""
    if height_ft < 1:
        return "Probably not worth the drive."
    if knots >= 20:
        return "Expect it to be choppy out there."
    if height_ft < 2:
        return "Longboard territory."
    if height_ft < 5:
        return "Should be a fun one."
    if height_ft < 8:
        return "Bring the step up."
    return "Experienced surfers only."


# --------------------------------------------------------------------------- main loop


def _strip_wake(text: str, wake: str) -> tuple[bool, str]:
    """Return (wake phrase heard, remaining words)."""
    words = _normalize(text).split()
    wake_words = _normalize(wake).split()
    n = len(wake_words)
    for i in range(len(words) - n + 1):
        if words[i : i + n] == wake_words:
            return True, " ".join(words[:i] + words[i + n :])
    return False, text


def is_question(text: str) -> bool:
    """'what are the waves in ...' / 'how's the surf at ...' count as talking to us."""
    words = set(_normalize(text).split())
    return bool(words & QUESTION_WORDS) and bool(words & TOPIC_WORDS)


def day_offset(text: str) -> int:
    return 1 if "tomorrow" in _normalize(text).split() else 0


def _spoken_error(exc: Exception) -> str:
    if isinstance(exc, ValueError) and "could be any of" in str(exc):
        options = str(exc).split("could be any of: ")[1].split(". ")[0]
        names = [o.split(" (")[0].split(",")[0] for o in options.split(", ")]
        return f"That could be {' or '.join(names)}. Which one did you mean?"
    if isinstance(exc, ForecastError):
        return "Sorry, I couldn't reach the forecast service. Try again in a bit."
    return "Sorry, I didn't catch which beach you meant. Which spot?"


def listen(
    transcriber: Transcriber,
    chunks: Chunks,
    client: SurfForecastClient,
    *,
    wake: str | None = DEFAULT_WAKE,
    days: int = 3,
    once: bool = False,
    speak: Speaker = lambda text: None,
    out: Callable[[str], None] = print,
    err: Callable[[str], None] = lambda text: print(text, file=sys.stderr),
) -> int:
    """Answer spoken questions until the audio ends, the user says quit, or --once fires."""
    if wake:
        out(f'Listening. Ask "what are the waves in rockaway?" or say "{wake}" and a spot name.')
    else:
        out("Listening. Say the name of a surf spot.")
    awake = wake is None

    for text in transcriber.transcribe(chunks):
        out(f"Heard: {text}")
        text = " ".join(
            word for word in text.split() if word != "[unk]"
        )  # drop unknown-word markers
        if wake:
            heard_wake, text = _strip_wake(text, wake)
            if heard_wake:
                awake = True
                if not text.strip():
                    speak("Yeah? Which spot?")
                    continue
            elif not awake and not is_question(text):
                continue
        if _normalize(text) in QUIT_WORDS:
            speak("Catch you later.")
            return 0

        try:
            spot = find_spot(text)
            forecast = client.forecast(spot, days=max(days, 1 + day_offset(text)))
        except (KeyError, ValueError, ForecastError) as exc:
            message = exc.args[0] if exc.args else str(exc)
            err(f"Sorry, {message}")
            speak(_spoken_error(exc))
            continue

        hours = forecast.daylight()
        out(f"\nHere is the surf forecast for {spot.name}:\n")
        out(render_table(forecast, hours))
        out("")
        report = summarize(forecast, hours, day_offset=day_offset(text))
        out(report)
        speak(report)
        if once:
            return 0
        awake = wake is None
    return 0
