"""A small built-in catalogue of well-known surf spots.

Add your own by passing --lat/--lon on the command line, or extend this dict.
"""

from __future__ import annotations

from surfcast.models import Spot

SPOTS: dict[str, Spot] = {
    s.slug: s
    for s in [
        Spot("Malibu (Surfrider)", 34.0356, -118.6775, slug="malibu"),
        Spot("Huntington Beach Pier", 33.6553, -118.0036, slug="huntington"),
        Spot("Trestles (Lowers)", 33.3828, -117.5886, slug="trestles"),
        Spot("Ocean Beach, SF", 37.7599, -122.5108, slug="ocean-beach"),
        Spot("Mavericks", 37.4936, -122.4994, slug="mavericks"),
        Spot("Pipeline, Oahu", 21.6650, -158.0530, slug="pipeline"),
        Spot("Waikiki", 21.2740, -157.8260, slug="waikiki"),
        Spot("Rincon", 34.3733, -119.4767, slug="rincon"),
        Spot("Montauk (Ditch Plains)", 41.0390, -71.9140, slug="montauk"),
        Spot("Rockaway Beach", 40.5790, -73.8360, slug="rockaway"),
        Spot("Cocoa Beach", 28.3200, -80.6076, slug="cocoa-beach"),
        Spot("Nazaré", 39.6040, -9.0850, slug="nazare"),
        Spot("Hossegor", 43.6630, -1.4420, slug="hossegor"),
        Spot("Mundaka", 43.4070, -2.6990, slug="mundaka"),
        Spot("Jeffreys Bay", -34.0500, 24.9200, slug="jbay"),
        Spot("Bells Beach", -38.3680, 144.2820, slug="bells"),
        Spot("Snapper Rocks", -28.1630, 153.5500, slug="snapper"),
        Spot("Uluwatu", -8.8290, 115.0860, slug="uluwatu"),
        Spot("Raglan (Manu Bay)", -37.8260, 174.8020, slug="raglan"),
        Spot("Teahupo'o", -17.8500, -149.2670, slug="teahupoo"),
    ]
}


def get_spot(slug: str) -> Spot:
    """Look up a built-in spot by slug (case-insensitive)."""
    key = slug.strip().lower()
    try:
        return SPOTS[key]
    except KeyError:
        known = ", ".join(sorted(SPOTS))
        raise KeyError(f"unknown spot '{slug}'. Known spots: {known}") from None
