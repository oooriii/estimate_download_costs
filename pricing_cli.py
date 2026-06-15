from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, Prompt
from rich.table import Table

from pricing.aws_offers import download_offers
from pricing.defaults import EU_SOUTH_2_DEFAULTS
from pricing.generate import PricingGenerationError, generate_pricing_config
from pricing.loader import load_pricing_config, save_pricing_config
from pricing.schema import (
    DEFAULT_USD_EUR_RATE,
    DEFAULT_USD_EUR_RATE_WARNING,
    STORAGE_CLASSES,
    CloudFrontPricing,
    DisplayConfig,
    PriceTier,
    PricingConfig,
    PricingValidationError,
    S3Pricing,
    format_money,
    parse_pricing_config,
)


def _prompt_non_empty(prompt: str, default: str) -> str:
    while True:
        value = Prompt.ask(prompt, default=default).strip()
        if value:
            return value
        Console().print("[red]Value cannot be empty.[/red]")


def _prompt_positive_float(prompt: str, default: float) -> float:
    while True:
        value = FloatPrompt.ask(prompt, default=default)
        if value >= 0:
            return value
        Console().print("[red]Value must be >= 0.[/red]")


def _prompt_positive_rate(prompt: str, default: float) -> float:
    while True:
        value = FloatPrompt.ask(prompt, default=default)
        if value > 0:
            return value
        Console().print("[red]Value must be > 0.[/red]")


def _prompt_ratio(prompt: str, default: float) -> float:
    while True:
        value = FloatPrompt.ask(prompt, default=default)
        if 0 <= value <= 1:
            return value
        Console().print("[red]Value must be between 0 and 1.[/red]")


def _prompt_date(prompt: str, default: date) -> date:
    while True:
        raw = Prompt.ask(prompt, default=default.isoformat()).strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            Console().print("[red]Enter a valid date as YYYY-MM-DD.[/red]")


def _prompt_transfer_tiers(
    console: Console,
    label: str,
    defaults: list[tuple[float | None, float]],
) -> tuple[PriceTier, ...]:
    console.print(f"[bold]{label}[/bold]")
    tiers: list[PriceTier] = []
    for index, (default_limit, default_price) in enumerate(defaults):
        is_last = index == len(defaults) - 1
        if is_last:
            price = _prompt_positive_float(
                "  Final tier price per GB (USD)", default_price
            )
            tiers.append(PriceTier(up_to_gb=None, price=price))
            continue

        limit = _prompt_positive_float(
            f"  Tier {index + 1} up to GB",
            float(default_limit),
        )
        price = _prompt_positive_float(
            f"  Tier {index + 1} price per GB (USD)",
            default_price,
        )
        tiers.append(PriceTier(up_to_gb=limit, price=price))

    if tiers[-1].up_to_gb is not None:
        tiers.append(PriceTier(up_to_gb=None, price=tiers[-1].price))

    return tuple(tiers)


def build_pricing_config_interactive(console: Console) -> PricingConfig:
    console.print(
        Panel(
            "Enter AWS prices in USD from the official pricing pages.\n"
            "All inputs are validated before saving.",
            title="Pricing configuration wizard",
            border_style="cyan",
        )
    )

    region = _prompt_non_empty("AWS region", EU_SOUTH_2_DEFAULTS["region"])
    effective_date = _prompt_date("Pricing effective date", date.today())

    usd_eur_rate = _prompt_positive_rate(
        "USD/EUR exchange rate",
        DEFAULT_USD_EUR_RATE,
    )
    if usd_eur_rate == DEFAULT_USD_EUR_RATE:
        console.print(f"[yellow]Warning:[/yellow] {DEFAULT_USD_EUR_RATE_WARNING}")

    console.print("[bold]S3 storage (USD per GB/month)[/bold]")
    storage = {
        storage_class: _prompt_positive_float(
            f"  {storage_class}",
            EU_SOUTH_2_DEFAULTS["storage_per_gb_month"][storage_class],
        )
        for storage_class in STORAGE_CLASSES
    }

    monitoring = _prompt_positive_float(
        "S3 Intelligent-Tiering monitoring per 1,000 objects (USD)",
        EU_SOUTH_2_DEFAULTS["intelligent_tiering_monitoring_per_1000_objects"],
    )

    console.print("[bold]S3 requests (USD per 1,000)[/bold]")
    requests = {
        "GET": _prompt_positive_float(
            "  GET",
            EU_SOUTH_2_DEFAULTS["requests_per_1000"]["GET"],
        ),
        "PUT": _prompt_positive_float(
            "  PUT",
            EU_SOUTH_2_DEFAULTS["requests_per_1000"]["PUT"],
        ),
        "LIST": _prompt_positive_float(
            "  LIST",
            EU_SOUTH_2_DEFAULTS["requests_per_1000"]["LIST"],
        ),
    }

    s3_tiers = _prompt_transfer_tiers(
        console,
        "S3 data transfer out tiers",
        EU_SOUTH_2_DEFAULTS["s3_transfer_tiers"],
    )

    cloudfront: CloudFrontPricing | None = None
    if Confirm.ask("Include CloudFront pricing?", default=True):
        cf_tiers = _prompt_transfer_tiers(
            console,
            "CloudFront data transfer out tiers",
            EU_SOUTH_2_DEFAULTS["cloudfront_transfer_tiers"],
        )
        cf_get = _prompt_positive_float(
            "CloudFront GET requests per 10,000 (USD)",
            EU_SOUTH_2_DEFAULTS["cloudfront_requests_per_10000"]["GET"],
        )
        cache_ratio = _prompt_ratio(
            "Recommended cache hit ratio",
            EU_SOUTH_2_DEFAULTS["recommended_cache_hit_ratio"],
        )
        cloudfront = CloudFrontPricing(
            data_transfer_out_per_gb=cf_tiers,
            requests_per_10000={"GET": cf_get},
            recommended_cache_hit_ratio=cache_ratio,
        )

    config = PricingConfig(
        effective_date=effective_date,
        region=region,
        currency="USD",
        display=DisplayConfig(
            show_eur=True,
            usd_eur_rate=usd_eur_rate,
            rate_note="Manual rate; update when estimating for finance reports.",
        ),
        sources={
            "s3": "https://aws.amazon.com/s3/pricing/",
            "cloudfront": "https://aws.amazon.com/cloudfront/pricing/",
            "region": "https://aws.amazon.com/about-aws/global-infrastructure/regions_az/",
        },
        s3=S3Pricing(
            storage_per_gb_month=storage,
            intelligent_tiering_monitoring_per_1000_objects=monitoring,
            requests_per_1000=requests,
            data_transfer_out_per_gb=s3_tiers,
        ),
        cloudfront=cloudfront,
    )

    parse_pricing_config(config.to_dict())
    return config


def print_pricing_summary(console: Console, config: PricingConfig) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Region", config.region)
    table.add_row("Effective date", config.effective_date.isoformat())
    table.add_row(
        "USD/EUR rate",
        f"{config.display.usd_eur_rate:.4f}",
    )
    table.add_row(
        "S3 STANDARD storage",
        format_money(
            config.s3.storage_per_gb_month["STANDARD"],
            config.display.usd_eur_rate,
            config.display.show_eur,
        )
        + " / GB-month",
    )
    table.add_row(
        "S3 GET requests",
        format_money(
            config.s3.requests_per_1000["GET"],
            config.display.usd_eur_rate,
            config.display.show_eur,
        )
        + " / 1k",
    )
    table.add_row(
        "CloudFront",
        "configured" if config.cloudfront else "not configured",
    )

    console.print(
        Panel(table, title="[bold]Pricing configuration[/bold]", border_style="green")
    )


def cmd_pricing_init(args: argparse.Namespace) -> int:
    console = Console()
    output = args.output

    if output.exists() and not args.force:
        console.print(
            f"[red]Error:[/red] '{output}' already exists. Use --force to overwrite."
        )
        return 1

    config = build_pricing_config_interactive(console)
    print_pricing_summary(console, config)

    if not Confirm.ask(f"Save pricing config to {output}?", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        return 1

    save_pricing_config(output, config)
    console.print(f"[green]Saved[/green] pricing config to {output}")
    return 0


def cmd_pricing_show(args: argparse.Namespace) -> int:
    console = Console()
    try:
        config, warnings = load_pricing_config(args.file)
    except (PricingValidationError, OSError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1

    print_pricing_summary(console, config)
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    return 0


def cmd_pricing_validate(args: argparse.Namespace) -> int:
    console = Console()
    try:
        config, warnings = load_pricing_config(args.file)
    except (PricingValidationError, OSError) as exc:
        console.print(f"[red]Invalid:[/red] {exc}")
        return 1

    console.print(f"[green]Valid[/green] pricing config for region {config.region}.")
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
    return 0


def cmd_pricing_download_offers(args: argparse.Namespace) -> int:
    console = Console()
    try:
        results = download_offers()
    except OSError as exc:
        console.print(f"[red]Error:[/red] failed to download AWS offers: {exc}")
        return 1

    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column("File", style="bold cyan")
    table.add_column("Products", justify="right")
    table.add_column("Publication date")

    for result in results:
        if result.name == "manifest":
            continue
        table.add_row(
            result.name,
            str(result.product_count),
            result.publication_date or "—",
        )

    console.print(
        Panel(
            table,
            title="[bold]Cached AWS offer files[/bold]",
            border_style="green",
        )
    )
    console.print(
        "Files saved under [bold]pricing/aws-offers/[/bold]. "
        "Re-run this command periodically to refresh AWS prices."
    )
    return 0


def cmd_pricing_generate(args: argparse.Namespace) -> int:
    console = Console()

    if args.output.exists() and not args.force:
        console.print(
            f"[red]Error:[/red] '{args.output}' already exists. "
            "Use --force to overwrite."
        )
        return 1

    if args.download:
        try:
            download_offers()
        except OSError as exc:
            console.print(f"[red]Error:[/red] failed to download AWS offers: {exc}")
            return 1

    try:
        config, warnings = generate_pricing_config(
            region=args.region,
            usd_eur_rate=args.eur_rate,
            include_cloudfront=not args.no_cloudfront,
        )
    except (PricingGenerationError, FileNotFoundError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print(
            "Run [bold]uv run python main.py pricing download-offers[/bold] first, "
            "or pass [bold]--download[/bold]."
        )
        return 1

    if args.eur_rate == DEFAULT_USD_EUR_RATE:
        warnings.append(DEFAULT_USD_EUR_RATE_WARNING)

    save_pricing_config(args.output, config)
    print_pricing_summary(console, config)
    for warning in warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")

    console.print(f"[green]Generated[/green] pricing config at {args.output}")
    return 0


def register_pricing_commands(subparsers: argparse._SubParsersAction) -> None:
    pricing = subparsers.add_parser("pricing", help="Manage AWS pricing JSON files")
    pricing_sub = pricing.add_subparsers(dest="pricing_command", required=True)

    init = pricing_sub.add_parser(
        "init", help="Create a pricing JSON file interactively"
    )
    init.add_argument(
        "--output",
        type=Path,
        default=Path("pricing/eu-south-2.json"),
        help="Output pricing JSON path",
    )
    init.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists",
    )
    init.set_defaults(func=cmd_pricing_init)

    show = pricing_sub.add_parser("show", help="Display a pricing JSON file")
    show.add_argument("file", type=Path, help="Pricing JSON file")
    show.set_defaults(func=cmd_pricing_show)

    validate = pricing_sub.add_parser("validate", help="Validate a pricing JSON file")
    validate.add_argument("file", type=Path, help="Pricing JSON file")
    validate.set_defaults(func=cmd_pricing_validate)

    download_offers_cmd = pricing_sub.add_parser(
        "download-offers",
        help="Download and cache AWS public price list JSON files",
    )
    download_offers_cmd.set_defaults(func=cmd_pricing_download_offers)

    generate = pricing_sub.add_parser(
        "generate",
        help="Generate pricing JSON from cached AWS offer files",
    )
    generate.add_argument(
        "--output",
        type=Path,
        default=Path("pricing/eu-south-2.json"),
        help="Output pricing JSON path",
    )
    generate.add_argument(
        "--region",
        default="eu-south-2",
        help="AWS region for the generated pricing file",
    )
    generate.add_argument(
        "--eur-rate",
        type=float,
        default=DEFAULT_USD_EUR_RATE,
        help="USD/EUR exchange rate stored in the pricing file",
    )
    generate.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists",
    )
    generate.add_argument(
        "--download",
        action="store_true",
        help="Download AWS offers before generating",
    )
    generate.add_argument(
        "--no-cloudfront",
        action="store_true",
        help="Generate S3 pricing only",
    )
    generate.set_defaults(func=cmd_pricing_generate)
