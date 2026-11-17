import pytest

from surfcast.client import ForecastError, SurfForecastClient
from surfcast.spots import get_spot


def test_forecast_merges_marine_and_wind(client, fake_fetcher):
    spot = get_spot("malibu")
    fc = client.forecast(spot, days=2)

    assert fc.timezone == "America/Los_Angeles"
    assert len(fc.hours) == 48
    assert len(fake_fetcher.calls) == 2
    assert "forecast_days=2" in fake_fetcher.calls[0]
    assert "latitude=34.0356" in fake_fetcher.calls[0]

    first = fc.hours[0]
    assert first.wave_height_m == 1.0
    assert first.swell_period_s == 13.0
    assert first.wind_speed_kmh == 5.0
    assert first.wind_compass == "S"


def test_missing_values_become_none(client):
    fc = client.forecast(get_spot("malibu"))
    assert fc.hours[5].wave_height_m is None
    assert fc.hours[5].wave_height_ft is None
    # Wind series is one hour shorter than marine series; last hour has no wind.
    assert fc.hours[-1].wind_speed_kmh is None
    assert fc.hours[-1].wind_compass == "-"


def test_no_wind_skips_weather_request(client, fake_fetcher):
    client.forecast(get_spot("malibu"), include_wind=False)
    assert len(fake_fetcher.calls) == 1
    assert fake_fetcher.calls[0].startswith("https://marine-api.open-meteo.com")


def test_daylight_filter(client):
    fc = client.forecast(get_spot("malibu"))
    hours = fc.daylight()
    assert all(6 <= h.time.hour <= 20 for h in hours)
    assert len(hours) == 30  # 15 hours x 2 days


def test_days_out_of_range(client):
    with pytest.raises(ValueError):
        client.forecast(get_spot("malibu"), days=0)


def test_bad_marine_payload_raises():
    bad = SurfForecastClient(fetcher=lambda url: {"hourly": {}})
    with pytest.raises(ForecastError):
        bad.forecast(get_spot("malibu"))


def test_unknown_spot():
    with pytest.raises(KeyError, match="unknown spot"):
        get_spot("nowhere")
