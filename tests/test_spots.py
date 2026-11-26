import pytest

from surfcast.spots import SPOTS, find_spot, get_spot


@pytest.mark.parametrize(
    ("query", "slug"),
    [
        ("rockaway", "rockaway"),
        ("rockaway beach nyc", "rockaway"),
        ("Rockaway Beach, NYC", "rockaway"),
        ("nyc", "rockaway"),
        ("Nazaré", "nazare"),
        ("nazare", "nazare"),
        ("pipe", "pipeline"),
        ("north shore oahu", "pipeline"),
        ("ocean beach", "ocean-beach"),
        ("sf", "ocean-beach"),
        ("what's the surf forecast for malibu today", "malibu"),
        ("Jeffreys Bay", "jbay"),
        ("ditch plains", "montauk"),
        ("ocean beach sf", "ocean-beach"),  # comma in the name must not matter
        ("nazareth", "nazare"),  # how speech recognisers tend to hear it
        ("jay bay", "jbay"),
    ],
)
def test_find_spot_from_free_text(query, slug):
    assert find_spot(query) is SPOTS[slug]


def test_find_spot_every_slug_and_name_round_trips():
    for slug, spot in SPOTS.items():
        assert find_spot(slug) is spot
        assert find_spot(spot.name) is spot


@pytest.mark.parametrize("query", ["beach", "california", "new york"])
def test_find_spot_ambiguous(query):
    with pytest.raises(ValueError, match="could be any of"):
        find_spot(query)


@pytest.mark.parametrize("query", ["atlantis", "", "   ", "???"])
def test_find_spot_unknown(query):
    with pytest.raises(KeyError):
        find_spot(query)


def test_get_spot_exact_slug_only():
    assert get_spot("MALIBU") is SPOTS["malibu"]
    with pytest.raises(KeyError):
        get_spot("rockaway beach nyc")
