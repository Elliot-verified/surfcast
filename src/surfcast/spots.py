"""A small built-in catalogue of well-known surf spots.

Add your own by passing --lat/--lon on the command line, or extend this dict.
"""

from __future__ import annotations

import re
import unicodedata

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


# Extra words people use for a spot that are not in its name: nearby cities, regions, nicknames.
ALIASES: dict[str, list[str]] = {
    "malibu": ["la", "los angeles", "surfrider", "california", "socal"],
    "huntington": ["hb", "surf city", "orange county", "california", "socal"],
    "trestles": ["lowers", "san clemente", "san onofre", "california", "socal"],
    "ocean-beach": ["ob", "san francisco", "sf", "california", "norcal"],
    "mavericks": ["half moon bay", "california", "norcal"],
    "pipeline": ["pipe", "banzai", "north shore", "oahu", "hawaii"],
    "waikiki": ["honolulu", "oahu", "hawaii"],
    "rincon": ["santa barbara", "carpinteria", "california"],
    "montauk": ["ditch plains", "ditch", "long island", "new york", "ny", "hamptons"],
    "rockaway": ["rockaways", "queens", "nyc", "new york", "ny", "new york city", "brooklyn"],
    "cocoa-beach": ["florida", "fl", "space coast"],
    "nazare": ["nazareth", "portugal", "praia do norte"],  # "nazareth": how recognisers hear it
    "hossegor": ["hossegor", "hoss a gore", "france", "landes", "la graviere"],
    "mundaka": ["moon dhaka", "spain", "basque"],
    "jbay": ["jeffreys", "j-bay", "jay bay", "supertubes", "south africa"],
    "bells": ["torquay", "victoria", "australia"],
    "snapper": ["superbank", "coolangatta", "gold coast", "australia"],
    "uluwatu": ["ulus", "bali", "indonesia"],
    "raglan": ["manu bay", "new zealand", "nz"],
    "teahupoo": ["chopes", "cho poo", "tahiti", "french polynesia"],
}

# Words that carry no location information when someone asks for a forecast.
_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "any",
    "are",
    "at",
    "be",
    "conditions",
    "for",
    "forecast",
    "give",
    "going",
    "good",
    "hey",
    "how",
    "hows",
    "in",
    "is",
    "it",
    "like",
    "looking",
    "me",
    "now",
    "near",
    "of",
    "on",
    "please",
    "report",
    "right",
    "s",
    "surf",
    "surfing",
    "swell",
    "tell",
    "the",
    "there",
    "to",
    "today",
    "tomorrow",
    "waves",
    "weekend",
    "what",
    "whats",
}


def _normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation: 'Nazaré' -> 'nazare'."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def _tokens(text: str) -> set[str]:
    return {t for t in _normalize(text).split() if t not in _STOPWORDS}


def _search_terms(slug: str, spot: Spot) -> tuple[set[str], list[str]]:
    """Return (single-word tokens, multi-word phrases) that identify a spot."""
    words = {slug} | set(slug.split("-")) | _tokens(spot.name)
    phrases = []
    for alias in ALIASES.get(slug, []):
        norm = _normalize(alias)
        if " " in norm:
            phrases.append(norm)
        words |= set(norm.split())
    return words, phrases


def find_spot(query: str) -> Spot:
    """Find a built-in spot from free text such as 'rockaway beach nyc' or 'Nazare'.

    Raises ``KeyError`` when nothing matches and ``ValueError`` when the query
    is ambiguous (e.g. just 'beach').
    """
    text = _normalize(query)
    if not text:
        raise KeyError("please name a surf spot")
    if text in SPOTS:
        return SPOTS[text]

    query_tokens = _tokens(query)
    scores: dict[str, int] = {}
    for slug, spot in SPOTS.items():
        words, phrases = _search_terms(slug, spot)
        score = len(query_tokens & words)
        score += 2 * sum(1 for phrase in phrases if phrase in text)
        if _normalize(spot.name) in text:
            score += 3
        if score:
            scores[slug] = score

    if not scores:
        known = ", ".join(sorted(SPOTS))
        raise KeyError(f"unknown spot '{query}'. Known spots: {known}")

    best = max(scores.values())
    winners = sorted(slug for slug, score in scores.items() if score == best)
    if len(winners) > 1:
        options = ", ".join(SPOTS[slug].name for slug in winners)
        raise ValueError(f"'{query}' could be any of: {options}. Be more specific.")
    return SPOTS[winners[0]]
