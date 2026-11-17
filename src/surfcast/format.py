"""Output formatting for forecasts: table, JSON, CSV."""

from __future__ import annotations

import csv
import io
import json

from surfcast.models import Forecast, ForecastHour


def _fmt(value: float | None, suffix: str = "") -> str:
    return "-" if value is None else f"{value:g}{suffix}"


def _row(hour: ForecastHour) -> list[str]:
    return [
        hour.time.strftime("%a %H:%M"),
        _fmt(hour.wave_height_ft, "ft"),
        _fmt(hour.swell_height_ft, "ft"),
        _fmt(hour.swell_period_s, "s"),
        hour.swell_compass,
        _fmt(hour.wind_speed_kts, "kt"),
        hour.wind_compass,
    ]


HEADERS = ["Time", "Waves", "Swell", "Period", "Swell dir", "Wind", "Wind dir"]


def render_table(forecast: Forecast, hours: list[ForecastHour] | None = None) -> str:
    hours = forecast.hours if hours is None else hours
    rows = [_row(h) for h in hours]
    widths = [max(len(cell) for cell in col) for col in zip(HEADERS, *rows, strict=True)]

    def line(cells: list[str]) -> str:
        return "  ".join(cell.ljust(w) for cell, w in zip(cells, widths, strict=True)).rstrip()

    out = [
        f"{forecast.spot.name}  ({forecast.spot.latitude:.4f}, {forecast.spot.longitude:.4f})"
        f"  tz={forecast.timezone}  source={forecast.source}",
        line(HEADERS),
        line(["-" * w for w in widths]),
    ]
    current_day = None
    for h, row in zip(hours, rows, strict=True):
        if current_day is not None and h.time.date() != current_day:
            out.append("")
        current_day = h.time.date()
        out.append(line(row))
    return "\n".join(out)


def render_json(forecast: Forecast, hours: list[ForecastHour] | None = None) -> str:
    data = forecast.to_dict()
    if hours is not None:
        data["hours"] = [h.to_dict() for h in hours]
    return json.dumps(data, indent=2)


def render_csv(forecast: Forecast, hours: list[ForecastHour] | None = None) -> str:
    hours = forecast.hours if hours is None else hours
    buf = io.StringIO()
    if not hours:
        return ""
    writer = csv.DictWriter(buf, fieldnames=list(hours[0].to_dict().keys()))
    writer.writeheader()
    for h in hours:
        writer.writerow(h.to_dict())
    return buf.getvalue()
