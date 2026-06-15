from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from abuse import parse_log
from cost_model import Inventory, build_estimates, compare_storage_classes
from defaults import (
    DEFAULT_COMPARE_STORAGE_CLASSES,
    DEFAULT_REPORT_OUTPUT_DIR,
    default_report_paths,
    discover_geoip_db,
)
from estimate_cli import parse_growth_rate, parse_storage_classes
from estimate_report import print_estimate_report, print_storage_class_comparison
from export_csv import write_problematic_ips_csv
from geo import MaxMindGeoIpResolver, open_geoip_resolver
from pdf_report import EstimatePdfContext, write_combined_pdf
from pricing.loader import load_pricing_config
from pricing.schema import DEFAULT_GROWTH_RATE, STORAGE_CLASSES
from projection import PROJECTION_MODES, project_traffic
from report import (
    print_bot_summary,
    print_country_breakdown,
    print_top_ips,
    print_top_user_agents,
    print_traffic_stats,
)


def register_report_command(subparsers: argparse._SubParsersAction) -> None:
    report = subparsers.add_parser(
        "report",
        help="Generate a combined PDF report and abusive-IP CSV",
        description=(
            "Build a management report from a log file: traffic analysis, "
            "bot/abuse breakdown, optional country stats, AWS cost estimate, "
            "and optional storage-class comparison."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    report.add_argument("file", type=Path, help="Input log file")
    report.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_REPORT_OUTPUT_DIR,
        metavar="DIR",
        help=(
            f"Directory for PDF and CSV outputs "
            f"(default: {DEFAULT_REPORT_OUTPUT_DIR})"
        ),
    )
    report.add_argument(
        "--pdf",
        type=Path,
        metavar="PATH",
        help="PDF output path (default: <output-dir>/management-report.pdf)",
    )
    report.add_argument(
        "--csv-ips",
        type=Path,
        metavar="PATH",
        help="CSV output path (default: <output-dir>/problematic-ips.csv)",
    )
    report.add_argument(
        "--no-csv-ips",
        action="store_true",
        help="Skip CSV export",
    )
    report.add_argument(
        "--geoip-db",
        type=Path,
        metavar="PATH",
        help="GeoLite2-Country.mmdb (auto-detected in cwd if omitted)",
    )
    report.add_argument(
        "--storage-gb",
        type=float,
        required=True,
        help="Total stored data volume in GB",
    )
    report.add_argument(
        "--items",
        type=int,
        required=True,
        help="Number of stored objects (for Intelligent-Tiering monitoring)",
    )
    report.add_argument(
        "--growth",
        default=f"{DEFAULT_GROWTH_RATE:.0%}",
        help="Annual growth rate for storage, traffic, and items (e.g. 10%%)",
    )
    report.add_argument(
        "--projection-mode",
        choices=PROJECTION_MODES,
        default="simple",
        help="Traffic projection: simple (30-day month) or calendar month",
    )
    report.add_argument(
        "--forecast-years",
        type=int,
        default=0,
        metavar="N",
        help="Include multi-year cost forecast in the PDF (0 = hide)",
    )
    report.add_argument(
        "--pricing",
        type=Path,
        default=Path("pricing/eu-south-2.json"),
        help="Pricing JSON file",
    )
    report.add_argument(
        "--storage-class",
        choices=STORAGE_CLASSES,
        default="STANDARD",
        help="S3 storage class for the detailed estimate",
    )
    report.add_argument(
        "--compare-storage-classes",
        nargs="?",
        const=DEFAULT_COMPARE_STORAGE_CLASSES,
        metavar="CLASSES",
        help=(
            "Include S3 storage class comparison in the PDF "
            "(comma-separated; omit value to compare all)"
        ),
    )
    report.add_argument(
        "--countries-top",
        type=int,
        default=15,
        metavar="N",
        help="Top N countries in the PDF (default: 15)",
    )
    report.add_argument(
        "--abuse-top",
        type=int,
        default=15,
        metavar="N",
        help="Top N IPs and user-agents in the PDF (default: 15)",
    )
    report.add_argument(
        "--abuse-min-bytes-pct",
        type=float,
        default=5.0,
        metavar="PCT",
        help="Abuse threshold for CSV export (default: 5)",
    )
    report.add_argument(
        "--csv-ips-top",
        type=int,
        default=0,
        metavar="N",
        help="Max rows in CSV (0 = all abusive IPs, default)",
    )
    report.set_defaults(func=cmd_report)


def resolve_report_outputs(args: argparse.Namespace) -> tuple[Path, Path | None]:
    default_pdf, default_csv = default_report_paths(output_dir=args.output_dir)
    pdf_path = args.pdf or default_pdf
    if args.no_csv_ips:
        csv_path = None
    else:
        csv_path = args.csv_ips or default_csv
    return pdf_path, csv_path


def resolve_geoip_db(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit
    return discover_geoip_db()


def cmd_report(args: argparse.Namespace) -> int:
    console = Console()

    if not args.file.is_file():
        console.print(f"[red]Error:[/red] file '{args.file}' does not exist.")
        return 1

    if args.storage_gb < 0 or args.items < 0:
        console.print("[red]Error:[/red] storage and items must be >= 0.")
        return 1

    for name, value in (
        ("countries-top", args.countries_top),
        ("abuse-top", args.abuse_top),
        ("forecast-years", args.forecast_years),
        ("csv-ips-top", args.csv_ips_top),
    ):
        if value < 0:
            console.print(f"[red]Error:[/red] --{name} must be >= 0.")
            return 1

    if args.abuse_min_bytes_pct < 0:
        console.print("[red]Error:[/red] --abuse-min-bytes-pct must be >= 0.")
        return 1

    try:
        growth_rate = parse_growth_rate(args.growth)
    except ValueError:
        console.print(
            f"[red]Error:[/red] invalid growth rate '{args.growth}'. "
            "Use a value like 10% or 0.1."
        )
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

    geoip_db = resolve_geoip_db(args.geoip_db)
    resolver = None
    if geoip_db is not None:
        if not geoip_db.is_file():
            console.print(
                f"[red]Error:[/red] GeoIP database '{geoip_db}' does not exist."
            )
            return 1
        try:
            resolver = open_geoip_resolver(geoip_db)
        except (OSError, RuntimeError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            return 1
    elif args.geoip_db is None:
        console.print(
            "[yellow]Note:[/yellow] no GeoIP database found; "
            "country breakdown will be omitted from the report."
        )

    pdf_path, csv_path = resolve_report_outputs(args)

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

    inventory = Inventory(
        storage_gb=args.storage_gb,
        items=args.items,
        annual_growth_rate=growth_rate,
    )
    traffic = project_traffic(stats, mode=args.projection_mode)
    estimate_result = build_estimates(
        stats,
        inventory,
        pricing,
        args.storage_class,
        projection_mode=args.projection_mode,
    )
    storage_comparisons = None
    if compare_classes is not None:
        storage_comparisons = compare_storage_classes(
            stats,
            inventory,
            pricing,
            compare_classes,
            projection_mode=args.projection_mode,
        )

    estimate_context = EstimatePdfContext(
        pricing=pricing,
        traffic=traffic,
        result=estimate_result,
        selected_storage_class=args.storage_class,
        growth_rate=growth_rate,
        forecast_years=args.forecast_years,
        storage_comparisons=storage_comparisons,
        pricing_warnings=tuple(pricing_warnings),
    )

    try:
        write_combined_pdf(
            pdf_path,
            log_file=args.file,
            result=result,
            estimate=estimate_context,
            abuse_top=args.abuse_top,
            countries_top=args.countries_top,
            abuse_min_bytes_pct=args.abuse_min_bytes_pct,
        )
    except OSError as exc:
        console.print(f"[red]Error:[/red] could not write PDF: {exc}")
        return 1

    console.print(f"[green]PDF report written to[/green] {pdf_path}")

    if csv_path is not None:
        csv_limit = args.csv_ips_top or None
        try:
            row_count = write_problematic_ips_csv(
                csv_path,
                result.ips,
                total_records=stats.total_records,
                total_bytes=stats.total_bytes,
                min_bytes_pct=args.abuse_min_bytes_pct,
                limit=csv_limit,
            )
        except OSError as exc:
            console.print(f"[red]Error:[/red] could not write CSV: {exc}")
            return 1
        console.print(
            f"[green]Problematic IP CSV written to[/green] {csv_path} "
            f"({row_count} rows)"
        )

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

    print_estimate_report(
        console,
        log_file=args.file,
        pricing=pricing,
        traffic=traffic,
        result=estimate_result,
        pricing_warnings=pricing_warnings,
        selected_storage_class=args.storage_class,
        growth_rate=growth_rate,
        forecast_years=args.forecast_years,
    )
    if storage_comparisons is not None:
        print_storage_class_comparison(
            console,
            pricing=pricing,
            comparisons=storage_comparisons,
            selected_storage_class=args.storage_class,
        )

    return 0
