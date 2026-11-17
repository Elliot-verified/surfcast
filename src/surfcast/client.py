"""HTTP client for the Open-Meteo marine and weather forecast APIs.

Open-Meteo is free for non-commercial use and needs no API key.
Docs: https://open-meteo.com/en/docs/marine-weather-api
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime
from typing import Any

from surfcast.models import Forecast, ForecastHour, Spot

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

MARINE_VARS = [
    "wave_height",
    "wave_direction",
    "wave_period",
    "swell_wave_height",
    "swell_wave_direction",
    "swell_wave_period",
]
WEATHER_VARS = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]

USER_AGENT = "surfcast/0.1 (+https://github.com/Elliot-verified/surfcast)"

Fetcher = Callable[[str], dict[str, Any]]


class ForecastError(RuntimeError):
    """Raised when a forecast cannot be retrieved or parsed."""


def _http_get_json(url: str, timeout: float = 15.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            reason = json.loads(body).get("reason", body)
        except json.JSONDecodeError:
            reason = body
        raise ForecastError(
            f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}: {reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ForecastError(
            f"could not reach {urllib.parse.urlsplit(url).netloc}: {exc.reason}"
        ) from exc


class SurfForecastClient:
    """Fetches and merges marine (swell) and weather (wind) forecasts for a spot.

    Pass a custom ``fetcher`` to replace the HTTP layer, e.g. for tests or caching.
    """

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self._fetch = fetcher or _http_get_json

    def forecast(self, spot: Spot, days: int = 3, include_wind: bool = True) -> Forecast:
        if not 1 <= days <= 16:
            raise ValueError("days must be between 1 and 16")

        marine = self._fetch(self.marine_url(spot, days))
        hourly = marine.get("hourly")
        if not hourly or "time" not in hourly:
            raise ForecastError("marine response did not contain hourly data")

        wind_hourly: dict[str, Any] = {}
        if include_wind:
            weather = self._fetch(self.weather_url(spot, days))
            wind_hourly = weather.get("hourly") or {}

        wind_by_time = {t: i for i, t in enumerate(wind_hourly.get("time", []))}

        hours: list[ForecastHour] = []
        for i, stamp in enumerate(hourly["time"]):
            w = wind_by_time.get(stamp)
            hours.append(
                ForecastHour(
                    time=datetime.fromisoformat(stamp),
                    wave_height_m=_at(hourly, "wave_height", i),
                    wave_direction_deg=_at(hourly, "wave_direction", i),
                    wave_period_s=_at(hourly, "wave_period", i),
                    swell_height_m=_at(hourly, "swell_wave_height", i),
                    swell_direction_deg=_at(hourly, "swell_wave_direction", i),
                    swell_period_s=_at(hourly, "swell_wave_period", i),
                    wind_speed_kmh=_at(wind_hourly, "wind_speed_10m", w),
                    wind_direction_deg=_at(wind_hourly, "wind_direction_10m", w),
                    wind_gusts_kmh=_at(wind_hourly, "wind_gusts_10m", w),
                )
            )

        return Forecast(spot=spot, timezone=marine.get("timezone", "UTC"), hours=hours)

    @staticmethod
    def marine_url(spot: Spot, days: int) -> str:
        return _build_url(MARINE_URL, spot, days, MARINE_VARS)

    @staticmethod
    def weather_url(spot: Spot, days: int) -> str:
        return _build_url(WEATHER_URL, spot, days, WEATHER_VARS)


def _build_url(base: str, spot: Spot, days: int, variables: list[str]) -> str:
    params = {
        "latitude": f"{spot.latitude:.4f}",
        "longitude": f"{spot.longitude:.4f}",
        "hourly": ",".join(variables),
        "forecast_days": str(days),
        "timezone": "auto",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


def _at(series: dict[str, Any], key: str, index: int | None) -> float | None:
    if index is None:
        return None
    values = series.get(key)
    if not values or index >= len(values):
        return None
    value = values[index]
    return None if value is None else float(value)


def fetch_forecast(spot: Spot, days: int = 3, include_wind: bool = True) -> Forecast:
    """Convenience wrapper around :class:`SurfForecastClient`."""
    return SurfForecastClient().forecast(spot, days=days, include_wind=include_wind)
