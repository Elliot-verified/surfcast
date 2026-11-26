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
    assert said[0] == "Yes? Which surf spot?"
    assert "Here is the surf forecast for Rockaway Beach" in out
    assert said[1].startswith("Rockaway Beach on ")
    assert "feet" in said[1] and "knots" in said[1]
    assert not errors


def test_wake_phrase_and_spot_in_one_breath(client):
    rc, out, said, _ = run(["hey surf what's the forecast for pipeline"], client, once=True)
    assert rc == 0
    assert "Pipeline, Oahu" in out
    assert said[0].startswith("Pipeline, Oahu on ")


def test_speech_without_wake_phrase_is_ignored(client):
    rc, out, said, errors = run(["rockaway beach", "random chatter"], client)
    assert rc == 0
    assert "Here is the surf forecast" not in out
    assert said == [] and errors == []
    assert "Heard: rockaway beach" in out  # still shown so the user can see recognition


def test_no_wake_mode_answers_directly(client):
    rc, out, said, _ = run(["nazare"], client, wake=None)
    assert rc == 0
    assert "Nazaré" in out and said[0].startswith("Nazaré on ")


def test_unknown_spot_apologises_and_keeps_listening(client):
    rc, out, said, errors = run(["atlantis", "beach", "malibu"], client, wake=None)
    assert rc == 0
    assert any("unknown spot 'atlantis'" in e for e in errors)
    assert any("could be any of" in e for e in errors)
    assert said.count("Sorry, I did not catch a surf spot. Try again.") == 2
    assert "Malibu (Surfrider)" in out


def test_unknown_word_markers_are_stripped(client):
    rc, out, said, errors = run(["hey surf [unk]", "[unk] [unk]", "hey surf [unk] malibu"], client)
    assert rc == 0
    assert errors == ["Sorry, please name a surf spot"]  # not "unknown spot 'unk'"
    assert said[0] == "Yes? Which surf spot?"  # "hey surf [unk]" is just the wake phrase
    assert said[1] == "Sorry, I did not catch a surf spot. Try again."
    assert "Malibu (Surfrider)" in out


def test_quit_word_stops(client):
    rc, out, said, _ = run(["quit", "malibu"], client, wake=None)
    assert rc == 0
    assert said == ["Goodbye."]
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


def test_summarize_sentence(client):
    forecast = client.forecast(SPOTS["malibu"], days=1)
    text = voice.summarize(forecast)
    assert text.startswith("Malibu (Surfrider) on ")
    assert "waves" in text and "feet" in text
    assert "swell" in text and "seconds from the west" in text
    assert "wind" in text and "knots from the" in text
    assert text.endswith(".")


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
    monkeypatch.setattr(voice, "make_speaker", lambda device, enabled: lambda t: None)
    assert main(["listen", "--once", "--no-speak"], client=client) == 0
    assert "Rockaway Beach" in capsys.readouterr().out
    assert "hey surf" in captured["grammar"]

    captured.clear()
    assert (
        main(["listen", "--once", "--no-speak", "--no-wake", "--free-speech"], client=client) == 0
    )
    assert captured["grammar"] is None
