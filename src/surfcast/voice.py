"""Voice mode: listen on a microphone, recognise a surf spot, speak the forecast.

Speech recognition is done offline with Vosk (``pip install surfcast[voice]``),
constrained to a grammar built from the spot catalogue so a small model still
gets names like "Teahupo'o" right. Audio comes from ``arecord`` (ALSA) or a
file; speech output uses ``espeak-ng``/``espeak`` when installed.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Protocol

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

COMPASS_WORDS = {"N": "north", "S": "south", "E": "east", "W": "west"}

Chunks = Iterable[bytes]
Speaker = Callable[[str], None]


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
    """Words and phrases the recogniser should expect: spot names, aliases, wake phrase."""
    phrases = {
        "surf", "forecast", "what's", "the", "for", "at", "in", "please", "today",
        "tomorrow", "waves", "how", "is", "it", "yes", "no", "quit", "stop", "thanks",
    }  # fmt: skip
    for slug, spot in SPOTS.items():
        phrases.add(_normalize(spot.name))
        phrases.update(slug.split("-"))
        phrases.update(_normalize(a) for a in ALIASES.get(slug, []))
    if wake:
        phrases.add(_normalize(wake))
    phrases.discard("")
    return sorted(phrases) + ["[unk]"]


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
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    archive = MODEL_DIR / f"{DEFAULT_MODEL}.zip"
    log(f"Downloading speech model ({DEFAULT_MODEL}, ~40 MB) to {MODEL_DIR} ...")
    urllib.request.urlretrieve(MODEL_URL, archive)  # noqa: S310
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


def make_speaker(device: str | None = None, enabled: bool = True) -> Speaker:
    """Return a function that speaks text aloud, or a no-op if TTS is unavailable/disabled."""
    engine = shutil.which("espeak-ng") or shutil.which("espeak")
    if not enabled or engine is None:
        return lambda text: None

    def speak(text: str) -> None:
        if device:
            tts = subprocess.Popen([engine, "--stdout", text], stdout=subprocess.PIPE)
            subprocess.run(["aplay", "-q", "-D", device], stdin=tts.stdout, check=False)
            tts.wait()
        else:
            subprocess.run([engine, text], check=False)

    return speak


def compass_words(label: str) -> str:
    """'WNW' -> 'west northwest'; '-' -> 'unknown'."""
    if not label or label == "-":
        return "unknown"
    if len(label) == 3:  # e.g. WNW -> W + NW
        return f"{COMPASS_WORDS[label[0]]} {compass_words(label[1:])}"
    return "".join(COMPASS_WORDS[c] for c in label)


def _ft(value: float | None) -> str:
    return "unknown" if value is None else f"{value:g}"


def summarize(forecast: Forecast, hours: list[ForecastHour] | None = None) -> str:
    """One spoken sentence about the first day of the forecast."""
    hours = forecast.daylight() if hours is None else hours
    if not hours:
        return f"No forecast hours available for {forecast.spot.name}."
    day = hours[0].time.date()
    today = [h for h in hours if h.time.date() == day] or hours
    waves = [h.wave_height_ft for h in today if h.wave_height_ft is not None]
    swell = [h for h in today if h.swell_height_ft is not None]
    wind = [h for h in today if h.wind_speed_kts is not None]

    parts = [f"{forecast.spot.name} on {day.strftime('%A')}:"]
    if waves:
        lo, hi = min(waves), max(waves)
        parts.append(f"waves {lo:g} to {hi:g} feet," if lo != hi else f"waves {lo:g} feet,")
    if swell:
        mid = swell[len(swell) // 2]
        parts.append(
            f"swell {_ft(mid.swell_height_ft)} feet at {_ft(mid.swell_period_s)} seconds"
            f" from the {compass_words(mid.swell_compass)},"
        )
    if wind:
        mid = wind[len(wind) // 2]
        parts.append(
            f"wind {_ft(mid.wind_speed_kts)} knots from the {compass_words(mid.wind_compass)}."
        )
    return " ".join(parts).rstrip(",") + ("" if parts[-1].endswith(".") else ".")


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
    """Respond to spoken spot names until the audio ends, the user says quit, or --once fires."""
    if wake:
        out(f'Listening. Say "{wake}" and then a surf spot, e.g. "{wake}, rockaway beach".')
    else:
        out("Listening. Say the name of a surf spot.")
    awake = wake is None

    for text in transcriber.transcribe(chunks):
        out(f"Heard: {text}")
        if wake:
            heard_wake, text = _strip_wake(text, wake)
            if heard_wake:
                awake = True
                if not text.strip():
                    speak("Yes? Which surf spot?")
                    continue
            elif not awake:
                continue
        if _normalize(text) in {"quit", "stop", "exit", "goodbye"}:
            speak("Goodbye.")
            return 0

        try:
            spot = find_spot(text)
            forecast = client.forecast(spot, days=days)
        except (KeyError, ValueError, ForecastError) as exc:
            message = exc.args[0] if exc.args else str(exc)
            err(f"Sorry, {message}")
            speak("Sorry, I did not catch a surf spot. Try again.")
            continue

        hours = forecast.daylight()
        out(f"\nHere is the surf forecast for {spot.name}:\n")
        out(render_table(forecast, hours))
        out("")
        speak(summarize(forecast, hours))
        if once:
            return 0
        awake = wake is None
    return 0
