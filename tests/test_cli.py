import csv
import io
import json

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
