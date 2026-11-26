"""Command-line interface for surfcast."""

from __future__ import annotations

import argparse
import sys

from surfcast import __version__
from surfcast.client import ForecastError, SurfForecastClient
from surfcast.format import render_csv, render_json, render_table
from surfcast.models import Spot
from surfcast.spots import SPOTS, find_spot

PROMPT = "Where do you want to know the surf forecast? "
QUIT_WORDS = {"q", "quit", "exit", "bye", "done", "no", "nothing"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surfcast",
        description="Pull surf forecast data (swell, period, wind) for a surf spot.",
    )
    parser.add_argument("--version", action="version", version=f"surfcast {__version__}")
    sub = parser.add_subparsers(dest="command")

    fc = sub.add_parser("forecast", help="fetch a forecast for a spot")
    where = fc.add_mutually_exclusive_group(required=True)
    where.add_argument("--spot", help="built-in spot slug or name, e.g. 'rockaway beach nyc'")
    where.add_argument("--lat", type=float, help="latitude (use with --lon)")
    fc.add_argument("--lon", type=float, help="longitude (use with --lat)")
    fc.add_argument("--name", help="label for a custom --lat/--lon location")
    fc.add_argument("--days", type=int, default=3, help="forecast days, 1-16 (default 3)")
    fc.add_argument(
        "--format", choices=["table", "json", "csv"], default="table", help="output format"
    )
    fc.add_argument("--all-hours", action="store_true", help="include night hours")
    fc.add_argument("--no-wind", action="store_true", help="skip the wind request")

    ask = sub.add_parser(
        "ask",
        help="ask for a spot by name and get its forecast (default when no command is given)",
    )
    ask.add_argument("place", nargs="*", help="spot name, e.g. 'rockaway beach nyc' (or be asked)")
    ask.add_argument("--days", type=int, default=3, help="forecast days, 1-16 (default 3)")
    ask.add_argument("--all-hours", action="store_true", help="include night hours")

    ls = sub.add_parser("listen", help="voice mode: say a spot, hear the forecast (needs [voice])")
    ls.add_argument("--wake", default=None, help='wake phrase (default "hey surf"); "" to disable')
    ls.add_argument("--no-wake", action="store_true", help="respond to any speech, no wake phrase")
    ls.add_argument("--mic", help="ALSA capture device for arecord, e.g. plughw:2,0")
    ls.add_argument("--speaker", help="ALSA playback device for aplay, e.g. plughw:3,0")
    ls.add_argument("--no-speak", action="store_true", help="print only, do not talk back")
    ls.add_argument("--once", action="store_true", help="exit after the first forecast")
    ls.add_argument("--days", type=int, default=3, help="forecast days, 1-16 (default 3)")
    ls.add_argument("--audio", help="transcribe this audio file instead of the microphone")
    ls.add_argument("--model", help="Vosk model directory (default: auto-download small en-us)")
    ls.add_argument("--free-speech", action="store_true", help="do not constrain recogniser")

    sub.add_parser("spots", help="list built-in spots")
    return parser


def resolve_spot(args: argparse.Namespace) -> Spot:
    if args.spot:
        return find_spot(args.spot)
    if args.lon is None:
        raise SystemExit("error: --lon is required with --lat")
    name = args.name or f"{args.lat:.4f}, {args.lon:.4f}"
    return Spot(name=name, latitude=args.lat, longitude=args.lon)


def ask(args: argparse.Namespace, client: SurfForecastClient) -> int:
    """Interactive mode: ask where, answer with the forecast, repeat until the user is done."""
    place = " ".join(args.place).strip()
    asked = False
    while True:
        if not place:
            try:
                place = input(PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            asked = True
            if not place or place.lower() in QUIT_WORDS:
                return 0

        try:
            spot = find_spot(place)
            forecast = client.forecast(spot, days=args.days)
        except (KeyError, ValueError, ForecastError) as exc:
            message = exc.args[0] if exc.args else str(exc)
            print(f"Sorry, {message}", file=sys.stderr)
            if not asked:
                return 1
        else:
            hours = forecast.hours if args.all_hours else forecast.daylight()
            print(f"\nHere is the surf forecast for {spot.name}:\n")
            print(render_table(forecast, hours))
            print()
        if not asked:
            return 0
        place = ""


def listen_command(args: argparse.Namespace, client: SurfForecastClient) -> int:
    from surfcast import voice

    wake = None if args.no_wake or args.wake == "" else (args.wake or voice.DEFAULT_WAKE)
    try:
        transcriber = voice.VoskTranscriber(
            model_dir=args.model,
            grammar=None if args.free_speech else voice.grammar_phrases(wake),
        )
        chunks = voice.file_chunks(args.audio) if args.audio else voice.mic_chunks(args.mic)
    except (RuntimeError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    speak = voice.make_speaker(args.speaker, enabled=not args.no_speak)
    try:
        return voice.listen(
            transcriber, chunks, client, wake=wake, days=args.days, once=args.once, speak=speak
        )
    except KeyboardInterrupt:
        print()
        return 0


def main(argv: list[str] | None = None, client: SurfForecastClient | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command is None or args.command == "ask":
        if args.command is None:
            args.place, args.days, args.all_hours = [], 3, False
        return ask(args, client or SurfForecastClient())

    if args.command == "listen":
        return listen_command(args, client or SurfForecastClient())

    if args.command == "spots":
        width = max(len(slug) for slug in SPOTS)
        for slug, spot in sorted(SPOTS.items()):
            print(f"{slug.ljust(width)}  {spot.name}  ({spot.latitude:.4f}, {spot.longitude:.4f})")
        return 0

    try:
        spot = resolve_spot(args)
        forecast = (client or SurfForecastClient()).forecast(
            spot, days=args.days, include_wind=not args.no_wind
        )
    except (KeyError, ValueError, ForecastError) as exc:
        message = exc.args[0] if exc.args else str(exc)
        print(f"error: {message}", file=sys.stderr)
        return 1

    hours = forecast.hours if args.all_hours else forecast.daylight()
    renderer = {"table": render_table, "json": render_json, "csv": render_csv}[args.format]
    print(renderer(forecast, hours))
    return 0


if __name__ == "__main__":
    sys.exit(main())
