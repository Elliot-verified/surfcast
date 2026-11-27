from __future__ import annotations

import pytest

from surfcast import voice
from surfcast.spots import SPOTS


class FakeTranscriber:
    def __init__(self, utterances: list[str]) -> None:
        self.utterances = utterances

    def transcribe(self, chunks):
        for _chunk in chunks:  # consume the stream like a real recogniser would
            pass
        yield from self.utterances


def run(utterances, client, **kwargs):
    said: list[str] = []
    printed: list[str] = []
    errors: list[str] = []
    rc = voice.listen(
        FakeTranscriber(utterances),
        [b"\x00" * 10],
        client,
        speak=said.append,
        out=printed.append,
        err=errors.append,
        **kwargs,
    )
    return rc, "\n".join(printed), said, errors


def test_wake_phrase_then_spot(client):
    rc, out, said, errors = run(["hey surf", "rockaway beach new york"], client)
    assert rc == 0
    assert said[0] == "Yeah? Which spot?"
    assert "Here is the surf forecast for Rockaway Beach" in out
    assert said[1].startswith("Here's Rockaway Beach on ")
    assert "feet" in said[1] and "knots" in said[1]
    assert said[1] in out  # the spoken report is printed too
    assert not errors


def test_natural_question_needs_no_wake_phrase(client):
    rc, out, said, errors = run(["what are the waves in rockaway new york"], client)
    assert rc == 0
    assert "Here is the surf forecast for Rockaway Beach" in out
    assert said[0].startswith("Here's Rockaway Beach on ")
    assert not errors


def test_tomorrow_picks_the_second_day(client):
    rc, _, said, _ = run(["how's the surf at malibu tomorrow"], client)
    assert rc == 0
    assert said[0].startswith("Here's Malibu on ")
    today_rc, _, today_said, _ = run(["how's the surf at malibu today"], client)
    assert today_rc == 0
    assert said[0] != today_said[0]


def test_ambiguous_question_offers_the_choices(client):
    rc, _, said, errors = run(["what are the waves in new york"], client)
    assert rc == 0
    assert said == ["That could be Montauk or Rockaway Beach. Which one did you mean?"]
    assert errors and "could be any of" in errors[0]


def test_wake_phrase_and_spot_in_one_breath(client):
    rc, out, said, _ = run(["hey surf what's the forecast for pipeline"], client, once=True)
    assert rc == 0
    assert "Pipeline, Oahu" in out
    assert said[0].startswith("Here's Pipeline on ")


def test_speech_without_wake_phrase_is_ignored(client):
    rc, out, said, errors = run(["rockaway beach", "random chatter"], client)
    assert rc == 0
    assert "Here is the surf forecast" not in out
    assert said == [] and errors == []
    assert "Heard: rockaway beach" in out  # still shown so the user can see recognition


def test_no_wake_mode_answers_directly(client):
    rc, out, said, _ = run(["nazare"], client, wake=None)
    assert rc == 0
    assert "Nazaré" in out and said[0].startswith("Here's Nazaré on ")


def test_unknown_spot_apologises_and_keeps_listening(client):
    rc, out, said, errors = run(["atlantis", "beach", "malibu"], client, wake=None)
    assert rc == 0
    assert any("unknown spot 'atlantis'" in e for e in errors)
    assert any("could be any of" in e for e in errors)
    assert said[0] == "Sorry, I didn't catch which beach you meant. Which spot?"
    assert said[1].startswith("That could be ")
    assert "Malibu (Surfrider)" in out


def test_unknown_word_markers_are_stripped(client):
    rc, out, said, errors = run(["hey surf [unk]", "[unk] [unk]", "hey surf [unk] malibu"], client)
    assert rc == 0
    assert errors == ["Sorry, please name a surf spot"]  # not "unknown spot 'unk'"
    assert said[0] == "Yeah? Which spot?"  # "hey surf [unk]" is just the wake phrase
    assert said[1] == "Sorry, I didn't catch which beach you meant. Which spot?"
    assert "Malibu (Surfrider)" in out


def test_quit_word_stops(client):
    rc, out, said, _ = run(["quit", "malibu"], client, wake=None)
    assert rc == 0
    assert said == ["Catch you later."]
    assert "Malibu" not in out


def test_once_stops_after_first_forecast(client):
    rc, out, said, _ = run(["malibu", "pipeline"], client, wake=None, once=True)
    assert rc == 0
    assert "Malibu" in out and "Pipeline" not in out
    assert len(said) == 1


def test_wake_resets_after_each_answer(client):
    rc, out, said, _ = run(["hey surf malibu", "pipeline", "hey surf pipeline"], client)
    assert rc == 0
    assert out.count("Here is the surf forecast") == 2
    assert "Pipeline, Oahu" in out


def test_summarize_is_short_and_conversational(client):
    forecast = client.forecast(SPOTS["malibu"], days=1)
    text = voice.summarize(forecast)
    assert text.startswith("Here's Malibu on ")
    assert "It's looking" in text and "feet" in text
    assert "foot west northwest swell at" in text and "seconds" in text
    assert "Wind is" in text and "knots out of the" in text
    assert text.endswith(".")
    assert len(text.split(". ")) <= 4  # a few sentences, not a data dump
    assert not any(ch.isdigit() and "." in word for word in text.split() for ch in word)


def test_summarize_relative_days(client):
    forecast = client.forecast(SPOTS["malibu"], days=2)
    first = forecast.daylight()[0].time.date()
    assert voice.summarize(forecast, today=first).startswith("Here's Malibu today.")
    assert voice.summarize(forecast, day_offset=1, today=first).startswith(
        "Here's Malibu tomorrow."
    )
    assert voice.summarize(forecast, day_offset=9, today=first).startswith(
        "Here's Malibu tomorrow."
    )  # clamps to the last day available


def test_summarize_without_hours(client):
    forecast = client.forecast(SPOTS["malibu"], days=1)
    assert "Sorry" in voice.summarize(forecast, hours=[])


@pytest.mark.parametrize(
    ("lo", "hi", "words"),
    [
        (0.3, 0.6, "under a foot"),
        (0.9, 1.2, "about a foot"),
        (2.2, 3.4, "2 to 3 feet"),
        (3.9, 4.1, "about 4 feet"),
    ],
)
def test_feet_words(lo, hi, words):
    assert voice._feet(lo, hi) == words


def test_size_wind_trend_and_verdict_words():
    assert voice.size_words(0.5) == "pretty much flat"
    assert voice.size_words(4) == "fun sized"
    assert voice.size_words(9) == "big"
    assert voice.wind_words(3) == "almost calm"
    assert voice.wind_words(30) == "strong"
    assert voice.trend_words([1, 1, 2, 3, 3, 3]) == "building through the day"
    assert voice.trend_words([3, 3, 3, 1, 1, 1]) == "dropping through the day"
    assert voice.trend_words([2, 2.1, 2, 2.2, 2, 2]) == "holding steady"
    assert voice.trend_words([2]) == "holding steady"
    assert voice.verdict(0.5, 5) == "Probably not worth the drive."
    assert voice.verdict(3, 25) == "Expect it to be choppy out there."
    assert voice.verdict(3, 8) == "Should be a fun one."
    assert voice.verdict(10, 8) == "Experienced surfers only."


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("what are the waves in rockaway", True),
        ("how's the surf at malibu", True),
        ("give me the surf report for pipeline", True),
        ("rockaway beach", False),
        ("what time is it", False),
        ("nice waves today", False),
    ],
)
def test_is_question(text, expected):
    assert voice.is_question(text) is expected


def test_voice_url_and_ensure_voice(tmp_path, monkeypatch):
    assert voice.voice_url("en_US-lessac-medium") == (
        "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
        "en/en_US/lessac/medium/en_US-lessac-medium.onnx"
    )
    assert voice.voice_url("en_GB-alba-medium", ".onnx.json").endswith(
        "en_GB-alba-medium.onnx.json"
    )
    with pytest.raises(ValueError):
        voice.voice_url("lessac")

    model = tmp_path / "custom.onnx"
    with pytest.raises(FileNotFoundError):
        voice.ensure_voice(model)
    model.write_bytes(b"onnx")
    model.with_suffix(".onnx.json").write_text("{}")
    assert voice.ensure_voice(model) == model

    downloaded: list[str] = []
    monkeypatch.setattr(voice, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(
        voice, "_download", lambda url, target, log, what: (downloaded.append(url), target.touch())
    )
    assert (
        voice.ensure_voice("en_US-amy-low", log=lambda t: None) == tmp_path / "en_US-amy-low.onnx"
    )
    assert [u.rsplit("/", 1)[1] for u in downloaded] == [
        "en_US-amy-low.onnx.json",
        "en_US-amy-low.onnx",
    ]
    assert voice.ensure_voice("en_US-amy-low") == tmp_path / "en_US-amy-low.onnx"
    assert len(downloaded) == 2  # cached


class FakeChunk:
    def __init__(self, data: bytes, rate: int = 22050) -> None:
        self.audio_int16_bytes = data
        self.sample_rate = rate


class FakePiperVoice:
    def synthesize(self, text):
        yield FakeChunk(text.encode())
        yield FakeChunk(b"!")


def test_piper_speaker_joins_chunks_and_plays():
    played: list[tuple[bytes, int]] = []
    speak = voice.piper_speaker(FakePiperVoice(), lambda pcm, rate: played.append((pcm, rate)))
    speak("hi")
    assert played == [(b"hi!", 22050)]


def test_make_speaker_prefers_piper_then_espeak_then_silence(monkeypatch):
    logs: list[str] = []
    monkeypatch.setattr(voice, "make_player", lambda device: lambda pcm, rate: None)
    monkeypatch.setattr(voice, "load_piper_voice", lambda v, log: FakePiperVoice())
    speak = voice.make_speaker(log=logs.append)
    assert speak.__qualname__.startswith("piper_speaker")

    monkeypatch.setattr(voice, "load_piper_voice", lambda v, log: None)
    monkeypatch.setattr(voice, "espeak_speaker", lambda device: lambda text: None)
    speak = voice.make_speaker(log=logs.append)
    assert not speak.__qualname__.startswith("piper_speaker")

    monkeypatch.setattr(voice, "espeak_speaker", lambda device: None)
    assert voice.make_speaker(log=logs.append)("anything") is None
    assert any("No text-to-speech" in line for line in logs)

    def broken(v, log):
        raise OSError("no network")

    monkeypatch.setattr(voice, "load_piper_voice", broken)
    monkeypatch.setattr(voice, "espeak_speaker", lambda device: lambda text: None)
    voice.make_speaker(log=logs.append)
    assert any("Falling back to espeak" in line for line in logs)
    assert voice.make_speaker(enabled=False)("quiet") is None


def test_pcm_to_wav_header():
    data = voice._pcm_to_wav(b"\x00\x01" * 4, 16000)
    assert data[:4] == b"RIFF" and b"WAVE" in data[:12]


@pytest.mark.parametrize(
    ("label", "words"),
    [
        ("N", "north"),
        ("SW", "southwest"),
        ("WNW", "west northwest"),
        ("ESE", "east southeast"),
        ("-", "unknown"),
    ],
)
def test_compass_words(label, words):
    assert voice.compass_words(label) == words


def test_grammar_covers_catalogue_and_wake():
    phrases = voice.grammar_phrases("hey surf")
    assert "hey surf" in phrases
    assert "rockaway beach" in phrases and "nyc" in phrases and "pipe" in phrases
    assert {"what", "are", "waves", "in", "tomorrow"} <= set(phrases)
    assert "nazare" in phrases  # accents stripped so the model vocabulary matches
    assert phrases[-1] == "[unk]"
    assert "" not in phrases
    assert all("  " not in p for p in phrases)  # would become empty grammar words
    assert "ocean beach sf" in phrases


@pytest.mark.parametrize(
    ("text", "heard", "rest"),
    [
        ("hey surf rockaway", True, "rockaway"),
        ("okay hey surf", True, "okay"),
        ("hey surf", True, ""),
        ("surf rockaway", False, "surf rockaway"),
    ],
)
def test_strip_wake(text, heard, rest):
    assert voice._strip_wake(text, "hey surf") == (heard, rest)


def test_ensure_model_with_explicit_dir(tmp_path):
    assert voice.ensure_model(tmp_path) == tmp_path
    with pytest.raises(FileNotFoundError):
        voice.ensure_model(tmp_path / "missing")


def test_listen_cli_reports_missing_vosk(monkeypatch, capsys, client):
    from surfcast.cli import main

    def boom(*args, **kwargs):
        raise RuntimeError("voice mode needs the vosk package")

    monkeypatch.setattr(voice, "VoskTranscriber", boom)
    assert main(["listen"], client=client) == 1
    assert "vosk" in capsys.readouterr().err


def test_listen_cli_wires_options(monkeypatch, capsys, client):
    from surfcast.cli import main

    captured = {}

    class Rec:
        def __init__(self, model_dir=None, grammar=None, log=print):
            captured["grammar"] = grammar

        def transcribe(self, chunks):
            yield "hey surf rockaway beach"

    monkeypatch.setattr(voice, "VoskTranscriber", Rec)
    monkeypatch.setattr(voice, "mic_chunks", lambda device: iter([b""]))
    monkeypatch.setattr(voice, "make_speaker", lambda device, enabled, voice: lambda t: None)
    assert main(["listen", "--once", "--no-speak"], client=client) == 0
    assert "Rockaway Beach" in capsys.readouterr().out
    assert "hey surf" in captured["grammar"]

    captured.clear()
    assert (
        main(["listen", "--once", "--no-speak", "--no-wake", "--free-speech"], client=client) == 0
    )
    assert captured["grammar"] is None
