import pytest

from surfcast.models import Spot, degrees_to_compass, metres_to_feet


@pytest.mark.parametrize(
    ("deg", "label"),
    [
        (0, "N"),
        (359, "N"),
        (45, "NE"),
        (90, "E"),
        (180, "S"),
        (270, "W"),
        (292.5, "WNW"),
        (None, "-"),
    ],
)
def test_degrees_to_compass(deg, label):
    assert degrees_to_compass(deg) == label


def test_metres_to_feet():
    assert metres_to_feet(1.0) == 3.3
    assert metres_to_feet(None) is None


def test_spot_validates_coordinates():
    with pytest.raises(ValueError):
        Spot("bad", 91, 0)
    with pytest.raises(ValueError):
        Spot("bad", 0, -181)
