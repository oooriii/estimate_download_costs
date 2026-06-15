from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from abuse import BotTraffic, IpTraffic, UserAgentTraffic, is_abusive, top_items
from bots import BOT_CATEGORY_LABELS
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


def _truncate(text: str, limit: int = 60) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _abuse_style(
    *,
    records: int,
    bytes: int,
    total_records: int,
    total_bytes: int,
    min_bytes_pct: float,
) -> str:
    if is_abusive(
        records=records,
        bytes=bytes,
        total_records=total_records,
        total_bytes=total_bytes,
        min_bytes_pct=min_bytes_pct,
    ):
        return "bold yellow"
    return ""


def print_bot_summary(
    console: Console,
    bot_traffic: tuple[BotTraffic, ...],
    *,
    total_records: int,
    total_bytes: int,
) -> None:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Category")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")

    for item in bot_traffic:
        table.add_row(
            BOT_CATEGORY_LABELS[item.category],
            f"{item.records:,}",
            _format_share(item.records, total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, total_bytes),
        )

    console.print(
        Panel(
            table,
            title="[bold]Bot vs human traffic[/bold]",
            subtitle="Based on user-agent heuristics (bots may spoof browsers).",
            border_style="magenta",
        )
    )


def print_top_ips(
    console: Console,
    ips: tuple[IpTraffic, ...],
    *,
    total_records: int,
    total_bytes: int,
    top: int = 15,
    min_bytes_pct: float = 5.0,
) -> None:
    rows = top_items(ips, limit=top)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("IP")
    table.add_column("Country")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")
    table.add_column("UAs", justify="right")
    table.add_column("Top user-agent")

    for item in rows:
        country = item.country_name or "—"
        if item.country_code and item.country_code not in {"??", "LOCAL"}:
            country = f"{country} ({item.country_code})"
        style = _abuse_style(
            records=item.records,
            bytes=item.bytes,
            total_records=total_records,
            total_bytes=total_bytes,
            min_bytes_pct=min_bytes_pct,
        )
        table.add_row(
            item.remote_host,
            country,
            f"{item.records:,}",
            _format_share(item.records, total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, total_bytes),
            str(item.user_agent_count),
            _truncate(item.top_user_agent),
            style=style,
        )

    console.print(
        Panel(
            table,
            title="[bold]Top clients by IP[/bold]",
            subtitle=(
                f"Top {len(rows)} IPs by bytes. "
                f"Rows at or above {min_bytes_pct:.0f}% of total traffic are highlighted."
            ),
            border_style="yellow",
        )
    )


def print_top_user_agents(
    console: Console,
    user_agents: tuple[UserAgentTraffic, ...],
    *,
    total_records: int,
    total_bytes: int,
    top: int = 15,
    min_bytes_pct: float = 5.0,
) -> None:
    rows = top_items(user_agents, limit=top)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("User-agent")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")
    table.add_column("IPs", justify="right")

    for item in rows:
        style = _abuse_style(
            records=item.records,
            bytes=item.bytes,
            total_records=total_records,
            total_bytes=total_bytes,
            min_bytes_pct=min_bytes_pct,
        )
        table.add_row(
            _truncate(item.user_agent, limit=72),
            f"{item.records:,}",
            _format_share(item.records, total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, total_bytes),
            str(item.ip_count),
            style=style,
        )

    console.print(
        Panel(
            table,
            title="[bold]Top clients by user-agent[/bold]",
            subtitle=(
                f"Top {len(rows)} user-agents by bytes. "
                f"Rows at or above {min_bytes_pct:.0f}% of total traffic are highlighted."
            ),
            border_style="yellow",
        )
    )


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
            subtitle=(
                "Based on client IP geolocation (GeoLite2). "
                "Volume may be inflated by bots or hosting infrastructure."
            ),
            border_style="blue",
        )
    )
