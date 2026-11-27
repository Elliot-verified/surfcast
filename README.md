# surfcast

A small command-line tool that pulls surf forecast data for any surf spot:
wave height, swell height/period/direction, and wind.

Data comes from the free [Open-Meteo](https://open-meteo.com/) marine and
weather APIs. No API key required. Zero runtime dependencies (voice mode
optionally adds [Vosk](https://alphacephei.com/vosk/) for offline speech recognition).

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

Just run `surfcast` and it will ask you where:

```
$ surfcast
Where do you want to know the surf forecast? rockaway beach nyc

Here is the surf forecast for Rockaway Beach:

Rockaway Beach  (40.5790, -73.8360)  tz=America/New_York  source=open-meteo
Time       Waves  Swell  Period  Swell dir  Wind    Wind dir
---------  -----  -----  ------  ---------  ------  --------
Wed 06:00  2.6ft  2.3ft  9s      ESE        6.2kt   N
...

Where do you want to know the surf forecast?
```

Spot names are matched loosely: slugs, full names, nearby cities and nicknames
all work ("rockaway beach nyc", "pipe", "sf", "nazare"). Press Enter on an
empty line or type `quit` to finish.

Or skip the question and pass the place directly:

```bash
surfcast ask rockaway beach nyc
surfcast ask "north shore oahu" --days 5
```

## Voice mode

On a Raspberry Pi (or any Linux box) with a microphone and speaker, surfcast
can answer spoken questions with a short surf report:

```bash
pip install "surfcast[voice]"      # adds vosk (offline speech recognition) and piper-tts (natural voice)
sudo apt install alsa-utils ffmpeg # mic capture and playback, audio file decoding

surfcast listen
# Listening. Ask "what are the waves in rockaway?" or say "hey surf" and a spot name.
# Heard: what are the waves in rockaway new york
# Here is the surf forecast for Rockaway Beach: ...
# Here's Rockaway Beach today. It's looking fun sized, 3 to 4 feet and holding steady,
# from a 3 foot east swell at 9 seconds. Wind is light, around 5 knots out of the west.
# Should be a fun one.
```

Any question that mentions waves, surf, swell or a forecast is answered
straight away; anything else needs the wake phrase first. Add "tomorrow" to
hear the next day. The first run downloads a ~40 MB English speech model and a
~60 MB voice to `~/.cache/surfcast`. Everything runs offline except the
forecast request itself. Recognition is constrained to the spot catalogue and
a few question words, so even a small model gets names like "Teahupo'o" right.
Useful flags:

```bash
surfcast listen --mic plughw:2,0 --speaker plughw:3,0   # pick ALSA devices (see arecord -l / aplay -l)
surfcast listen --voice en_US-amy-medium                 # another Piper voice (or a path to a .onnx file)
surfcast listen --no-wake                                # answer any speech, no "hey surf" needed
surfcast listen --wake "ok waves"                        # custom wake phrase
surfcast listen --no-speak --once                        # print only, exit after one forecast
surfcast listen --audio clip.wav                         # transcribe a recording instead of the mic
```

Without `piper-tts` installed, surfcast falls back to `espeak-ng` if present.
Say "quit" to stop.

The scripted commands below are still there for exact control and
machine-readable output:

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
