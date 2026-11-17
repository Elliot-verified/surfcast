"""Data models for surf forecasts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

COMPASS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]  # fmt: skip


def degrees_to_compass(degrees: float | None) -> str:
    """Convert a bearing in degrees to a 16-point compass label."""
    if degrees is None:
        return "-"
    index = int((degrees % 360) / 22.5 + 0.5) % 16
    return COMPASS[index]


def metres_to_feet(metres: float | None) -> float | None:
    if metres is None:
        return None
    return round(metres * 3.28084, 1)


@dataclass(frozen=True)
class Spot:
    """A surf spot identified by name and coordinates."""

    name: str
    latitude: float
    longitude: float
    slug: str = ""

    def __post_init__(self) -> None:
        if not -90 <= self.latitude <= 90:
            raise ValueError(f"latitude out of range: {self.latitude}")
        if not -180 <= self.longitude <= 180:
            raise ValueError(f"longitude out of range: {self.longitude}")


@dataclass
class ForecastHour:
    """Forecast conditions for a single hour."""

    time: datetime
    wave_height_m: float | None = None
    wave_direction_deg: float | None = None
    wave_period_s: float | None = None
    swell_height_m: float | None = None
    swell_direction_deg: float | None = None
    swell_period_s: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    wind_gusts_kmh: float | None = None

    @property
    def wave_height_ft(self) -> float | None:
        return metres_to_feet(self.wave_height_m)

    @property
    def swell_height_ft(self) -> float | None:
        return metres_to_feet(self.swell_height_m)

    @property
    def swell_compass(self) -> str:
        return degrees_to_compass(self.swell_direction_deg)

    @property
    def wind_compass(self) -> str:
        return degrees_to_compass(self.wind_direction_deg)

    @property
    def wind_speed_kts(self) -> float | None:
        if self.wind_speed_kmh is None:
            return None
        return round(self.wind_speed_kmh / 1.852, 1)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["time"] = self.time.isoformat()
        data["wave_height_ft"] = self.wave_height_ft
        data["swell_height_ft"] = self.swell_height_ft
        data["swell_compass"] = self.swell_compass
        data["wind_compass"] = self.wind_compass
        data["wind_speed_kts"] = self.wind_speed_kts
        return data


@dataclass
class Forecast:
    """A multi-hour surf forecast for one spot."""

    spot: Spot
    timezone: str
    hours: list[ForecastHour] = field(default_factory=list)
    source: str = "open-meteo"

    def daylight(self, start_hour: int = 6, end_hour: int = 20) -> list[ForecastHour]:
        """Return only hours between start_hour and end_hour (local time, inclusive)."""
        return [h for h in self.hours if start_hour <= h.time.hour <= end_hour]

    def to_dict(self) -> dict[str, Any]:
        return {
            "spot": asdict(self.spot),
            "timezone": self.timezone,
            "source": self.source,
            "hours": [h.to_dict() for h in self.hours],
        }
