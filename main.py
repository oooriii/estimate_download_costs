import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from abuse import parse_log
from estimate_cli import register_estimate_command
from geo import MaxMindGeoIpResolver, open_geoip_resolver
from pricing_cli import register_pricing_commands
from report import (
    print_bot_summary,
    print_country_breakdown,
    print_top_ips,
    print_top_user_agents,
    print_traffic_stats,
)


def cmd_analyze(args: argparse.Namespace) -> int:
    console = Console()

    if not args.file.is_file():
        console.print(f"[red]Error:[/red] file '{args.file}' does not exist.")
        return 1

    if args.countries_top < 0:
        console.print("[red]Error:[/red] --countries-top must be >= 0.")
        return 1

    if args.abuse_top < 0:
        console.print("[red]Error:[/red] --abuse-top must be >= 0.")
        return 1

    if args.abuse_min_bytes_pct < 0:
        console.print("[red]Error:[/red] --abuse-min-bytes-pct must be >= 0.")
        return 1

    resolver = None
    if args.geoip_db is not None:
        try:
            resolver = open_geoip_resolver(args.geoip_db)
        except (OSError, RuntimeError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            return 1

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("{task.completed:,} records"),
        console=console,
        transient=True,
    ) as progress:
        try:
            result = parse_log(args.file, geo_resolver=resolver, progress=progress)
        finally:
            if isinstance(resolver, MaxMindGeoIpResolver):
                resolver.close()

    stats = result.stats
    if stats.total_records == 0:
        console.print(
            f"[yellow]Warning:[/yellow] no valid records found in '{args.file}'."
        )
        return 1

    print_traffic_stats(console, args.file, stats)
    print_bot_summary(
        console,
        result.bot_traffic,
        total_records=stats.total_records,
        total_bytes=stats.total_bytes,
    )
    print_top_ips(
        console,
        result.ips,
        total_records=stats.total_records,
        total_bytes=stats.total_bytes,
        top=args.abuse_top,
        min_bytes_pct=args.abuse_min_bytes_pct,
    )
    print_top_user_agents(
        console,
        result.user_agents,
        total_records=stats.total_records,
        total_bytes=stats.total_bytes,
        top=args.abuse_top,
        min_bytes_pct=args.abuse_min_bytes_pct,
    )
    if result.countries is not None:
        print_country_breakdown(
            console,
            result.countries,
            total_records=stats.total_records,
            total_bytes=stats.total_bytes,
            top=args.countries_top,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze Apache log files and estimate AWS download costs.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        help="Parse a log file and show traffic statistics",
    )
    analyze.add_argument("file", type=Path, help="Input log file")
    analyze.add_argument(
        "--geoip-db",
        type=Path,
        metavar="PATH",
        help="MaxMind GeoLite2-Country.mmdb for traffic-by-country breakdown",
    )
    analyze.add_argument(
        "--countries-top",
        type=int,
        default=15,
        metavar="N",
        help="Show top N countries plus an Other row (default: 15)",
    )
    analyze.add_argument(
        "--abuse-top",
        type=int,
        default=15,
        metavar="N",
        help="Show top N IPs and user-agents by traffic volume (default: 15)",
    )
    analyze.add_argument(
        "--abuse-min-bytes-pct",
        type=float,
        default=5.0,
        metavar="PCT",
        help="Highlight clients at or above this %% of records or bytes (default: 5)",
    )
    analyze.set_defaults(func=cmd_analyze)

    register_pricing_commands(subparsers)
    register_estimate_command(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
