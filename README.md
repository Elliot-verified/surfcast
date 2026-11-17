# surfcast

A small command-line tool that pulls surf forecast data for any surf spot:
wave height, swell height/period/direction, and wind.

Data comes from the free [Open-Meteo](https://open-meteo.com/) marine and
weather APIs. No API key required. Zero runtime dependencies.

## Install

```bash
pip install git+https://github.com/Elliot-verified/surfcast.git
```

Or for development:

```bash
git clone https://github.com/Elliot-verified/surfcast.git
cd surfcast
pip install -e ".[dev]"
```

## Usage

```bash
# 3-day forecast for a built-in spot (daylight hours only)
surfcast forecast --spot malibu

# any coordinates, 5 days, every hour
surfcast forecast --lat 33.38 --lon -117.59 --name "Lowers" --days 5 --all-hours

# machine-readable output
surfcast forecast --spot pipeline --format json
surfcast forecast --spot pipeline --format csv > pipeline.csv

# list built-in spots
surfcast spots
```

Example table output:

```
Malibu (Surfrider)  (34.0356, -118.6775)  tz=America/Los_Angeles  source=open-meteo
Time       Waves  Swell  Period  Swell dir  Wind    Wind dir
---------  -----  -----  ------  ---------  ------  --------
Tue 06:00  3.9ft  3.3ft  13s     W          3.5kt   SSW
Tue 07:00  4.1ft  3.4ft  13.5s   W          4.3kt   SSW
...
```

Heights are shown in feet and wind in knots in the table; JSON and CSV output
include both metric source values and converted fields.

## Use as a library

```python
from surfcast import fetch_forecast, Spot

spot = Spot("Trestles", 33.3828, -117.5886)
forecast = fetch_forecast(spot, days=2)
for hour in forecast.daylight():
    print(hour.time, hour.swell_height_ft, hour.swell_period_s, hour.swell_compass)
```

`SurfForecastClient` accepts a custom `fetcher` callable, so you can plug in
caching or a different HTTP library without touching the parsing code.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

Tests run entirely offline against recorded fixtures in `tests/fixtures/`.

## Notes

- Open-Meteo marine data is model output (not buoy observations) and is free for
  non-commercial use. See their [terms](https://open-meteo.com/en/terms).
- Forecasts cover 1 to 16 days.
- The wind forecast comes from a separate endpoint and is aligned to the marine
  series by timestamp. Hours without wind data show `-`.

## License

MIT
