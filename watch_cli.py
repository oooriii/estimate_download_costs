from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console

from geo import MaxMindGeoIpResolver, open_geoip_resolver
from source import iter_events
from watch.aggregator import WatchAggregator
from watch.blocking import recommend_blocks
from watch.config_loader import resolve_watch_runtime
from watch.country_blocks import open_country_blocks_resolver
from watch.country_blocks_export import export_flagged_country_cidrs
from watch.live_display import LiveMonitor, render_snapshot
from watch.snapshot import SnapshotScheduler, write_blocks_csv, write_snapshot_json


def _recommend_blocks(snapshot, *, thresholds, runtime_config, country_blocks):
    return recommend_blocks(
        snapshot,
        thresholds=thresholds,
        country_blocks=country_blocks,
        official_cidr_limit=runtime_config.country_blocks.display_limit,
    )


def _process_events(
    *,
    console: Console,
    aggregator: WatchAggregator,
    thresholds,
    runtime_config,
    country_blocks,
    input_paths: list[Path] | None,
    live: bool,
    refresh_seconds: float,
    snapshot_scheduler: SnapshotScheduler | None,
    export_csv: Path | None,
    export_json: Path | None,
    export_country_cidrs: Path | None,
) -> int:
    reading_stdin = not input_paths
    if live and reading_stdin and sys.stdin.isatty():
        console.print(
            "[red]Error:[/red] pipe Apache logs into stdin or pass log files.\n"
            "Example: ssh host 'sudo tail -F /var/log/apache2/access_ssl.log' "
            "| uv run python main.py watch --geoip-db GeoLite2-Country.mmdb"
        )
        return 1

    last_blocks: tuple = ()

    def handle_snapshot(snapshot, blocks, *, now: datetime | None = None) -> None:
        nonlocal last_blocks
        last_blocks = blocks
        if snapshot_scheduler is not None and snapshot_scheduler.enabled:
            written = snapshot_scheduler.maybe_write(snapshot, blocks, now=now)
            if written is not None:
                json_path, csv_path = written
                console.print(
                    f"[dim]Snapshot saved:[/dim] {json_path.name}, {csv_path.name}"
                )

    if live:
        with LiveMonitor(
            console,
            refresh_per_second=1.0 / max(refresh_seconds, 0.1),
        ) as monitor:
            for event in iter_events(input_paths):
                aggregator.ingest(event)
                snapshot = aggregator.snapshot(now=event.timestamp)
                blocks = _recommend_blocks(
                    snapshot,
                    thresholds=thresholds,
                    runtime_config=runtime_config,
                    country_blocks=country_blocks,
                )
                monitor.update(snapshot, blocks)
                handle_snapshot(snapshot, blocks, now=event.timestamp)
    else:
        last_snapshot = None
        for event in iter_events(input_paths):
            aggregator.ingest(event)
            last_snapshot = aggregator.snapshot(now=event.timestamp)
            blocks = _recommend_blocks(
                last_snapshot,
                thresholds=thresholds,
                runtime_config=runtime_config,
                country_blocks=country_blocks,
            )
            handle_snapshot(last_snapshot, blocks, now=event.timestamp)

        if last_snapshot is None:
            console.print("[yellow]Warning:[/yellow] no valid log events found.")
            return 1

        render_snapshot(console, last_snapshot, last_blocks)

        if export_csv is not None:
            write_blocks_csv(export_csv, last_blocks)
            console.print(f"[green]Block recommendations CSV:[/green] {export_csv}")
        if export_json is not None:
            write_snapshot_json(export_json, last_snapshot, last_blocks)
            console.print(f"[green]Snapshot JSON:[/green] {export_json}")

    if export_country_cidrs is not None and country_blocks is not None and last_blocks:
        written = export_flagged_country_cidrs(
            export_country_cidrs,
            last_blocks,
            country_blocks,
        )
        for path in written:
            console.print(f"[green]Official country CIDRs:[/green] {path}")

    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    console = Console()

    try:
        runtime_config, thresholds = resolve_watch_runtime(args)
    except (OSError, RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    resolver = None
    geoip_path = Path(runtime_config.geoip_db) if runtime_config.geoip_db else None
    if geoip_path is not None:
        try:
            resolver = open_geoip_resolver(geoip_path)
        except (OSError, RuntimeError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            return 1

    country_blocks = None
    try:
        country_blocks = open_country_blocks_resolver(
            geoip_db=geoip_path,
            locations=runtime_config.country_blocks.locations,
            blocks_ipv4=runtime_config.country_blocks.blocks_ipv4,
            blocks_ipv6=runtime_config.country_blocks.blocks_ipv6,
        )
    except (OSError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    if country_blocks is None and runtime_config.country_blocks.locations:
        console.print(
            "[yellow]Warning:[/yellow] country blocks CSV files not found; "
            "official CIDR recommendations disabled."
        )

    aggregator = WatchAggregator(thresholds=thresholds, geo_resolver=resolver)
    input_paths = args.files if args.files else None

    snapshot_scheduler = None
    if runtime_config.snapshots.every_seconds > 0:
        snapshot_scheduler = SnapshotScheduler(
            directory=Path(runtime_config.snapshots.directory),
            every_seconds=runtime_config.snapshots.every_seconds,
            country_blocks=country_blocks,
            export_country_cidrs=runtime_config.country_blocks.export_with_snapshots,
        )

    try:
        return _process_events(
            console=console,
            aggregator=aggregator,
            thresholds=thresholds,
            runtime_config=runtime_config,
            country_blocks=country_blocks,
            input_paths=input_paths,
            live=runtime_config.live,
            refresh_seconds=runtime_config.refresh_seconds,
            snapshot_scheduler=snapshot_scheduler,
            export_csv=args.export_csv,
            export_json=args.export_json,
            export_country_cidrs=args.export_country_cidrs,
        )
    finally:
        if isinstance(resolver, MaxMindGeoIpResolver):
            resolver.close()


def register_watch_command(subparsers: argparse._SubParsersAction) -> None:
    watch = subparsers.add_parser(
        "watch",
        help="Monitor Apache access/error logs live and suggest blocks by RPS",
    )
    watch.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Log files to analyze (default: read from stdin)",
    )
    watch.add_argument(
        "--config",
        type=Path,
        metavar="PATH",
        help="Optional YAML config file (CLI flags override config values)",
    )
    watch.add_argument(
        "--geoip-db",
        type=Path,
        metavar="PATH",
        help="MaxMind GeoLite2-Country.mmdb for country breakdown and blocks",
    )
    watch.add_argument(
        "--country-blocks-locations",
        type=Path,
        metavar="PATH",
        help="GeoLite2-Country-Locations-en.csv (auto-detected from --geoip-db)",
    )
    watch.add_argument(
        "--country-blocks-ipv4",
        type=Path,
        metavar="PATH",
        help="GeoLite2-Country-Blocks-IPv4.csv (auto-detected from --geoip-db)",
    )
    watch.add_argument(
        "--country-blocks-ipv6",
        type=Path,
        metavar="PATH",
        help="GeoLite2-Country-Blocks-IPv6.csv (auto-detected from --geoip-db)",
    )
    watch.add_argument(
        "--country-cidr-limit",
        type=int,
        default=5,
        metavar="N",
        help="Official CIDR samples per flagged country (default: 5)",
    )
    watch.add_argument(
        "--live",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Live Rich dashboard (default: on; use --no-live for batch)",
    )
    watch.add_argument(
        "--refresh",
        type=float,
        default=2.0,
        metavar="SEC",
        help="Live UI refresh interval (default: 2)",
    )
    watch.add_argument(
        "--window",
        type=float,
        default=300.0,
        metavar="SEC",
        help="Sliding window for RPS calculations (default: 300)",
    )
    watch.add_argument(
        "--burst-window",
        type=float,
        default=3.0,
        metavar="SEC",
        help="Group requests within this gap as one burst (default: 3)",
    )
    watch.add_argument(
        "--min-burst-rps",
        type=float,
        default=10.0,
        help="Flag actor when a burst reaches this RPS (default: 10)",
    )
    watch.add_argument(
        "--min-burst-req",
        type=int,
        default=20,
        help="Minimum requests in a burst to flag an actor (default: 20)",
    )
    watch.add_argument(
        "--min-rps-ip",
        type=float,
        default=2.0,
        help="Flag IP at or above this sustained RPS (default: 2)",
    )
    watch.add_argument(
        "--min-rps-subnet",
        type=float,
        default=5.0,
        help="Flag /24 subnet at or above this sustained RPS (default: 5)",
    )
    watch.add_argument(
        "--min-rps-country",
        type=float,
        default=10.0,
        help="Flag country at or above this RPS (default: 10)",
    )
    watch.add_argument(
        "--min-req-ip",
        type=int,
        default=50,
        help="Minimum requests in window to flag an IP (default: 50)",
    )
    watch.add_argument(
        "--min-req-subnet",
        type=int,
        default=100,
        help="Minimum requests in window to flag a subnet (default: 100)",
    )
    watch.add_argument(
        "--min-req-country",
        type=int,
        default=200,
        help="Minimum requests in window to flag a country (default: 200)",
    )
    watch.add_argument(
        "--subnet-v4",
        type=int,
        default=24,
        metavar="BITS",
        help="IPv4 subnet mask for range grouping (default: 24)",
    )
    watch.add_argument(
        "--top",
        type=int,
        default=15,
        metavar="N",
        help="Top N rows per table (default: 15)",
    )
    watch.add_argument(
        "--snapshot-dir",
        type=Path,
        metavar="PATH",
        help="Directory for periodic snapshots (live mode)",
    )
    watch.add_argument(
        "--snapshot-every",
        type=float,
        default=0.0,
        metavar="SEC",
        help="Write snapshot JSON/CSV every N seconds (0 = off, default)",
    )
    watch.add_argument(
        "--export-csv",
        type=Path,
        metavar="PATH",
        help="Write block recommendations to CSV (batch mode)",
    )
    watch.add_argument(
        "--export-json",
        type=Path,
        metavar="PATH",
        help="Write snapshot JSON (batch mode)",
    )
    watch.add_argument(
        "--export-country-cidrs",
        type=Path,
        metavar="DIR",
        help="Export all official GeoLite2 CIDR ranges for flagged countries",
    )
    watch.set_defaults(func=cmd_watch)
