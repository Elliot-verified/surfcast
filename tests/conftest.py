from __future__ import annotations

import json
from pathlib import Path

import pytest

from surfcast.client import SurfForecastClient

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def fake_fetcher():
    """Return a fetcher that serves recorded fixtures and logs requested URLs."""
    calls: list[str] = []

    def fetch(url: str) -> dict:
        calls.append(url)
        if url.startswith("https://marine-api.open-meteo.com"):
            return load("marine_malibu.json")
        if url.startswith("https://api.open-meteo.com"):
            return load("weather_malibu.json")
        raise AssertionError(f"unexpected URL {url}")

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


@pytest.fixture
def client(fake_fetcher) -> SurfForecastClient:
    return SurfForecastClient(fetcher=fake_fetcher)
