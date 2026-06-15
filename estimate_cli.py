from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from cost_model import Inventory, build_estimates, compare_storage_classes
from estimate_report import print_estimate_report, print_storage_class_comparison
from parser import parse_file
from pdf_report import EstimatePdfContext, write_estimate_pdf
from pricing.loader import load_pricing_config
from pricing.schema import DEFAULT_GROWTH_RATE, STORAGE_CLASSES
from projection import PROJECTION_MODES, project_traffic


def parse_growth_rate(value: str) -> float:
    raw = value.strip()
    if raw.endswith("%"):
        return float(raw[:-1]) / 100.0
    return float(raw)


def parse_storage_classes(value: str) -> tuple[str, ...]:
    classes = tuple(item.strip() for item in value.split(",") if item.strip())
    if not classes:
        raise ValueError("at least one storage class is required")

    invalid = [item for item in classes if item not in STORAGE_CLASSES]
    if invalid:
        allowed = ", ".join(STORAGE_CLASSES)
        raise ValueError(
            f"unknown storage class(es): {', '.join(invalid)}. Allowed: {allowed}"
        )
    return classes


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
        help="Annual growth rate for storage, traffic, and items (e.g. 10%%)",
    )
    estimate.add_argument(
        "--projection-mode",
        choices=PROJECTION_MODES,
        default="simple",
        help="Traffic projection: simple (30-day month) or calendar month",
    )
    estimate.add_argument(
        "--forecast-years",
        type=int,
        default=0,
        metavar="N",
        help="Show multi-year cost forecast for the realistic S3 scenario (0 = hide)",
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
        help="S3 storage class for the detailed estimate",
    )
    estimate.add_argument(
        "--compare-storage-classes",
        nargs="?",
        const=",".join(STORAGE_CLASSES),
        metavar="CLASSES",
        help=(
            "Compare S3 direct costs across storage classes "
            "(comma-separated; omit value to compare all)"
        ),
    )
    estimate.add_argument(
        "--pdf",
        type=Path,
        metavar="PATH",
        help="Write a cost estimate PDF report to this path",
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

    if args.forecast_years < 0:
        console.print("[red]Error:[/red] --forecast-years must be >= 0.")
        return 1

    compare_classes: tuple[str, ...] | None = None
    if args.compare_storage_classes is not None:
        try:
            compare_classes = parse_storage_classes(args.compare_storage_classes)
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
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
    traffic = project_traffic(stats, mode=args.projection_mode)
    result = build_estimates(
        stats,
        inventory,
        pricing,
        args.storage_class,
        projection_mode=args.projection_mode,
    )

    print_estimate_report(
        console,
        log_file=args.file,
        pricing=pricing,
        traffic=traffic,
        result=result,
        pricing_warnings=pricing_warnings,
        selected_storage_class=args.storage_class,
        growth_rate=growth_rate,
        forecast_years=args.forecast_years,
    )

    if compare_classes is not None:
        comparisons = compare_storage_classes(
            stats,
            inventory,
            pricing,
            compare_classes,
            projection_mode=args.projection_mode,
        )
        print_storage_class_comparison(
            console,
            pricing=pricing,
            comparisons=comparisons,
            selected_storage_class=args.storage_class,
        )
    else:
        comparisons = None

    if args.pdf is not None:
        try:
            write_estimate_pdf(
                args.pdf,
                log_file=args.file,
                context=EstimatePdfContext(
                    pricing=pricing,
                    traffic=traffic,
                    result=result,
                    selected_storage_class=args.storage_class,
                    growth_rate=growth_rate,
                    forecast_years=args.forecast_years,
                    storage_comparisons=comparisons,
                    pricing_warnings=tuple(pricing_warnings),
                ),
            )
        except OSError as exc:
            console.print(f"[red]Error:[/red] could not write PDF: {exc}")
            return 1
        console.print(f"[green]PDF report written to[/green] {args.pdf}")

    return 0
