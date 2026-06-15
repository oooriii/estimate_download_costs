from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from geo import CountryTraffic, top_countries
from parser import TrafficStats


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:,.2f} {unit}" if unit != "B" else f"{int(value):,} B"
        value /= 1024
    return f"{size:,} B"


def print_traffic_stats(console: Console, file_path: Path, stats: TrafficStats) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("File", str(file_path))
    table.add_row("Min date", str(stats.min_date) if stats.min_date else "—")
    table.add_row("Max date", str(stats.max_date) if stats.max_date else "—")
    table.add_row("Observed days", f"{stats.observed_days:.1f}")
    table.add_row("Records", f"{stats.total_records:,}")
    table.add_row("Bytes downloaded", format_bytes(stats.total_bytes))

    console.print(
        Panel(table, title="[bold]Study results[/bold]", border_style="green")
    )


def _format_share(part: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{100.0 * part / total:.1f}%"


def print_country_breakdown(
    console: Console,
    countries: tuple[CountryTraffic, ...],
    *,
    total_records: int,
    total_bytes: int,
    top: int = 15,
) -> None:
    rows = top_countries(countries, limit=top)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Country")
    table.add_column("Code", justify="center")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")

    for item in rows:
        table.add_row(
            item.country_name,
            item.country_code,
            f"{item.records:,}",
            _format_share(item.records, total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, total_bytes),
        )

    console.print(
        Panel(
            table,
            title="[bold]Traffic by country[/bold]",
            subtitle="Based on client IP geolocation (GeoLite2).",
            border_style="blue",
        )
    )
