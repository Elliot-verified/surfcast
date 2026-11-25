import csv
import io
import json

import pytest

from surfcast.cli import main


def test_table_output(client, capsys):
    assert main(["forecast", "--spot", "malibu"], client=client) == 0
    out = capsys.readouterr().out
    assert "Malibu (Surfrider)" in out
    assert "Swell" in out and "Wind" in out
    assert "ft" in out and "kt" in out


def test_json_output(client, capsys):
    assert main(["forecast", "--spot", "malibu", "--format", "json"], client=client) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["spot"]["slug"] == "malibu"
    assert data["hours"][0]["swell_compass"] == "W"


def test_csv_output_all_hours(client, capsys):
    assert (
        main(["forecast", "--spot", "malibu", "--format", "csv", "--all-hours"], client=client) == 0
    )
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 48
    assert "wave_height_ft" in rows[0]


def test_custom_coordinates(client, capsys):
    rc = main(["forecast", "--lat", "33.38", "--lon", "-117.59", "--name", "Lowers"], client=client)
    assert rc == 0
    assert "Lowers" in capsys.readouterr().out


def test_unknown_spot_exits_nonzero(client, capsys):
    assert main(["forecast", "--spot", "atlantis"], client=client) == 1
    assert "unknown spot" in capsys.readouterr().err


def test_spots_lists_catalogue(capsys):
    assert main(["spots"]) == 0
    out = capsys.readouterr().out
    assert "malibu" in out and "pipeline" in out


def test_spot_accepts_free_text(client, capsys):
    assert main(["forecast", "--spot", "rockaway beach nyc"], client=client) == 0
    assert "Rockaway Beach" in capsys.readouterr().out


def test_ask_prompts_then_answers(client, capsys, monkeypatch):
    answers = iter(["rockaway beach nyc", ""])
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr("builtins.input", fake_input)
    assert main([], client=client) == 0
    out = capsys.readouterr().out
    assert prompts[0] == "Where do you want to know the surf forecast? "
    assert "Here is the surf forecast for Rockaway Beach" in out
    assert "Swell" in out and "ft" in out
    assert len(prompts) == 2  # asked again after answering, then quit on empty line


def test_ask_recovers_from_unknown_place(client, capsys, monkeypatch):
    answers = iter(["atlantis", "beach", "pipe", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert main(["ask"], client=client) == 0
    captured = capsys.readouterr()
    assert "unknown spot 'atlantis'" in captured.err
    assert "could be any of" in captured.err
    assert "Pipeline, Oahu" in captured.out


def test_ask_with_place_argument_is_one_shot(client, capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("should not prompt"))
    assert main(["ask", "rockaway", "beach", "nyc", "--days", "2"], client=client) == 0
    assert "Rockaway Beach" in capsys.readouterr().out
    assert main(["ask", "atlantis"], client=client) == 1


def test_ask_handles_eof(client, capsys, monkeypatch):
    def eof(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    assert main([], client=client) == 0
