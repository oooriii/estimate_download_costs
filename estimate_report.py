from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cost_model import EstimateResult, ScenarioCosts
from pricing.schema import PricingConfig, format_money
from projection import ProjectedTraffic
from report import format_bytes


def format_money_detailed(usd: float, rate: float, show_eur: bool = True) -> str:
    if abs(usd) < 0.01:
        if show_eur:
            return f"${usd:,.4f} (€{usd * rate:,.4f})"
        return f"${usd:,.4f}"
    return format_money(usd, rate, show_eur)


def _print_scenario_table(
    console: Console,
    scenario: ScenarioCosts,
    pricing: PricingConfig,
    period: str,
) -> None:
    lines = scenario.monthly if period == "monthly" else scenario.annual
    total = scenario.monthly_total if period == "monthly" else scenario.annual_total
    rate = pricing.display.usd_eur_rate
    show_eur = pricing.display.show_eur

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Component", style="bold cyan")
    table.add_column("Cost", justify="right")

    for line in lines:
        table.add_row(
            line.label,
            format_money_detailed(line.usd, rate, show_eur),
        )
    table.add_row("", "")
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{format_money_detailed(total, rate, show_eur)}[/bold]",
    )

    console.print(
        Panel(
            table,
            title=f"[bold]{scenario.name} — {period}[/bold]",
            border_style="blue",
        )
    )


def print_estimate_report(
    console: Console,
    *,
    log_file: Path,
    pricing: PricingConfig,
    traffic: ProjectedTraffic,
    result: EstimateResult,
    pricing_warnings: list[str],
) -> None:
    disclaimer = Table(show_header=False, box=None, padding=(0, 2))
    disclaimer.add_column(style="yellow")
    disclaimer.add_row(
        f"Observed period: {traffic.observed_days:.1f} days "
        f"(scaled ×{traffic.scale_factor:.2f} → 30-day month)."
    )
    disclaimer.add_row(
        f"Region: {pricing.region} | Pricing date: {pricing.effective_date}"
    )
    disclaimer.add_row(
        f"FX: 1 USD = {pricing.display.usd_eur_rate:.4f} EUR (indicative only)."
    )
    disclaimer.add_row("AWS prices change. This is not a billing guarantee.")

    console.print(
        Panel(
            disclaimer,
            title="[bold]Estimate disclaimer[/bold]",
            border_style="yellow",
        )
    )

    traffic_table = Table(show_header=False, box=None, padding=(0, 2))
    traffic_table.add_column("Field", style="bold cyan")
    traffic_table.add_column("Value")
    traffic_table.add_row("Log file", str(log_file))
    traffic_table.add_row(
        "Projected monthly requests",
        f"{traffic.monthly_requests:,.0f}",
    )
    traffic_table.add_row(
        "Projected monthly transfer",
        format_bytes(int(traffic.monthly_bytes)),
    )
    traffic_table.add_row(
        "Conservative traffic buffer",
        f"+{traffic.safety_margin:.0%} on worst-case scenario only",
    )
    console.print(
        Panel(
            traffic_table,
            title="[bold]Projected traffic (realistic)[/bold]",
            border_style="green",
        )
    )

    _print_scenario_table(console, result.realistic_s3, pricing, "monthly")
    _print_scenario_table(console, result.realistic_s3, pricing, "annual")
    if result.realistic_cloudfront is not None:
        _print_scenario_table(console, result.realistic_cloudfront, pricing, "monthly")
        _print_scenario_table(console, result.realistic_cloudfront, pricing, "annual")

    _print_scenario_table(console, result.conservative, pricing, "monthly")
    _print_scenario_table(console, result.conservative, pricing, "annual")

    rate = pricing.display.usd_eur_rate
    savings = result.realistic_s3.monthly_total - (
        result.realistic_cloudfront.monthly_total
        if result.realistic_cloudfront
        else result.realistic_s3.monthly_total
    )
    if result.realistic_cloudfront and savings > 0:
        console.print(
            "[green]Recommendation:[/green] CloudFront saves "
            f"{format_money_detailed(savings, rate)} per month versus S3 direct."
        )

    for warning in pricing_warnings:
        console.print(f"[yellow]Warning:[/yellow] {warning}")
