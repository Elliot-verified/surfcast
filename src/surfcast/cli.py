"""Command-line interface for surfcast."""

from __future__ import annotations

import argparse
import sys

from surfcast import __version__
from surfcast.client import ForecastError, SurfForecastClient
from surfcast.format import render_csv, render_json, render_table
from surfcast.models import Spot
from surfcast.spots import SPOTS, get_spot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="surfcast",
        description="Pull surf forecast data (swell, period, wind) for a surf spot.",
    )
    parser.add_argument("--version", action="version", version=f"surfcast {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    fc = sub.add_parser("forecast", help="fetch a forecast for a spot")
    where = fc.add_mutually_exclusive_group(required=True)
    where.add_argument("--spot", help="built-in spot slug (see `surfcast spots`)")
    where.add_argument("--lat", type=float, help="latitude (use with --lon)")
    fc.add_argument("--lon", type=float, help="longitude (use with --lat)")
    fc.add_argument("--name", help="label for a custom --lat/--lon location")
    fc.add_argument("--days", type=int, default=3, help="forecast days, 1-16 (default 3)")
    fc.add_argument(
        "--format", choices=["table", "json", "csv"], default="table", help="output format"
    )
    fc.add_argument("--all-hours", action="store_true", help="include night hours")
    fc.add_argument("--no-wind", action="store_true", help="skip the wind request")

    sub.add_parser("spots", help="list built-in spots")
    return parser


def resolve_spot(args: argparse.Namespace) -> Spot:
    if args.spot:
        return get_spot(args.spot)
    if args.lon is None:
        raise SystemExit("error: --lon is required with --lat")
    name = args.name or f"{args.lat:.4f}, {args.lon:.4f}"
    return Spot(name=name, latitude=args.lat, longitude=args.lon)


def main(argv: list[str] | None = None, client: SurfForecastClient | None = None) -> int:
    args = build_parser().parse_args(argv)

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
