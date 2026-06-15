from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from defaults import default_static_paths
from export_static_csv import (
    write_static_daily_csv,
    write_static_demand_csv,
    write_static_summary_csv,
)
from projection import PROJECTION_MODES
from static_demand import parse_static_demand
from static_report import print_static_report


def register_static_command(subparsers: argparse._SubParsersAction) -> None:
    static = subparsers.add_parser(
        "static",
        help="Analyze static asset requests (CSS, JS, fonts, images) from access logs",
        description=(
            "Analyze static asset requests extracted from Apache access logs. "
            "Theme path classification is tuned for DSpace 5.x (/static/, "
            "/handle/static/, discovery scripts, etc.). DSpace 7.x–10.x layouts "
            "are not supported yet."
        ),
    )
    static.add_argument("file", type=Path, help="Input static-asset log file")
    static.add_argument(
        "--top",
        type=int,
        default=25,
        metavar="N",
        help="Show top N paths and extensions in the terminal (default: 25)",
    )
    static.add_argument(
        "--projection-mode",
        choices=PROJECTION_MODES,
        default="simple",
        help="Monthly projection mode (default: simple = 30-day month)",
    )
    static.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Default directory for CSV exports",
    )
    static.add_argument(
        "--csv",
        type=Path,
        metavar="PATH",
        help="Write top static files to CSV (default: <output-dir>/top-static-files.csv)",
    )
    static.add_argument(
        "--csv-daily",
        type=Path,
        metavar="PATH",
        help="Write daily traffic CSV (default: <output-dir>/static-daily.csv)",
    )
    static.add_argument(
        "--csv-summary",
        type=Path,
        metavar="PATH",
        help="Write summary CSV (default: <output-dir>/static-summary.csv)",
    )
    static.add_argument(
        "--no-csv",
        action="store_true",
        help="Skip all CSV exports",
    )
    static.set_defaults(func=cmd_static)


def resolve_static_outputs(
    args: argparse.Namespace,
) -> tuple[Path | None, Path | None, Path | None]:
    default_files, default_daily, default_summary = default_static_paths(
        output_dir=args.output_dir
    )
    if args.no_csv:
        return None, None, None
    return (
        args.csv or default_files,
        args.csv_daily or default_daily,
        args.csv_summary or default_summary,
    )


def cmd_static(args: argparse.Namespace) -> int:
    console = Console()

    if not args.file.is_file():
        console.print(f"[red]Error:[/red] file '{args.file}' does not exist.")
        return 1

    if args.top < 0:
        console.print("[red]Error:[/red] --top must be >= 0.")
        return 1

    files_csv, daily_csv, summary_csv = resolve_static_outputs(args)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("{task.completed:,} records"),
        console=console,
        transient=True,
    ) as progress:
        result = parse_static_demand(
            args.file,
            projection_mode=args.projection_mode,
            progress=progress,
        )

    if result.stats.total_records == 0:
        console.print(
            f"[yellow]Warning:[/yellow] no valid records found in '{args.file}'."
        )
        return 1

    print_static_report(
        console,
        args.file,
        result,
        top=args.top,
    )

    if summary_csv is not None:
        try:
            write_static_summary_csv(summary_csv, result)
        except OSError as exc:
            console.print(f"[red]Error:[/red] could not write summary CSV: {exc}")
            return 1
        console.print(f"[green]Summary CSV written to[/green] {summary_csv}")

    if daily_csv is not None:
        try:
            row_count = write_static_daily_csv(daily_csv, result)
        except OSError as exc:
            console.print(f"[red]Error:[/red] could not write daily CSV: {exc}")
            return 1
        console.print(
            f"[green]Daily traffic CSV written to[/green] {daily_csv} "
            f"({row_count} rows)"
        )

    if files_csv is not None:
        csv_limit = args.top or None
        try:
            row_count = write_static_demand_csv(files_csv, result, limit=csv_limit)
        except OSError as exc:
            console.print(f"[red]Error:[/red] could not write files CSV: {exc}")
            return 1
        console.print(
            f"[green]Top static files CSV written to[/green] {files_csv} "
            f"({row_count} rows)"
        )

    return 0
