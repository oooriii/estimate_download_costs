from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from cost_model import Inventory, build_estimates
from estimate_report import print_estimate_report
from parser import parse_file
from pricing.loader import load_pricing_config
from pricing.schema import DEFAULT_GROWTH_RATE, STORAGE_CLASSES
from projection import project_traffic


def parse_growth_rate(value: str) -> float:
    raw = value.strip()
    if raw.endswith("%"):
        return float(raw[:-1]) / 100.0
    return float(raw)


def register_estimate_command(subparsers: argparse._SubParsersAction) -> None:
    estimate = subparsers.add_parser(
        "estimate",
        help="Estimate AWS monthly and annual costs from a log file",
    )
    estimate.add_argument("file", type=Path, help="Input log file")
    estimate.add_argument(
        "--storage-gb",
        type=float,
        required=True,
        help="Total stored data volume in GB",
    )
    estimate.add_argument(
        "--items",
        type=int,
        required=True,
        help="Number of stored objects (for Intelligent-Tiering monitoring)",
    )
    estimate.add_argument(
        "--growth",
        default=f"{DEFAULT_GROWTH_RATE:.0%}",
        help="Annual growth rate (e.g. 10%% or 0.1). Default: 10%%",
    )
    estimate.add_argument(
        "--pricing",
        type=Path,
        default=Path("pricing/eu-south-2.json"),
        help="Pricing JSON file",
    )
    estimate.add_argument(
        "--storage-class",
        choices=STORAGE_CLASSES,
        default="STANDARD",
        help="S3 storage class for cost calculation",
    )
    estimate.set_defaults(func=cmd_estimate)


def cmd_estimate(args: argparse.Namespace) -> int:
    console = Console()

    if not args.file.is_file():
        console.print(f"[red]Error:[/red] file '{args.file}' does not exist.")
        return 1

    if args.storage_gb < 0 or args.items < 0:
        console.print("[red]Error:[/red] storage and items must be >= 0.")
        return 1

    try:
        growth_rate = parse_growth_rate(args.growth)
    except ValueError:
        console.print(
            f"[red]Error:[/red] invalid growth rate '{args.growth}'. "
            "Use a value like 10% or 0.1."
        )
        return 1

    if not args.pricing.is_file():
        console.print(
            f"[red]Error:[/red] pricing file '{args.pricing}' does not exist."
        )
        return 1

    try:
        pricing, pricing_warnings = load_pricing_config(args.pricing)
    except (OSError, ValueError) as exc:
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
        stats = parse_file(args.file, progress=progress)

    if stats.total_records == 0:
        console.print(
            f"[yellow]Warning:[/yellow] no valid records found in '{args.file}'."
        )
        return 1

    inventory = Inventory(
        storage_gb=args.storage_gb,
        items=args.items,
        annual_growth_rate=growth_rate,
    )
    traffic = project_traffic(stats)
    result = build_estimates(stats, inventory, pricing, args.storage_class)

    print_estimate_report(
        console,
        log_file=args.file,
        pricing=pricing,
        traffic=traffic,
        result=result,
        pricing_warnings=pricing_warnings,
    )
    return 0
