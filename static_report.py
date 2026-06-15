from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from abuse import top_items
from report import _format_share, _truncate, format_bytes, print_traffic_stats
from static_demand import StaticDemandResult, StaticPathDemand, sort_paths_by_records
from static_paths import category_label, static_path_version_note


def _display_path(item: StaticPathDemand) -> str:
    return item.path.rsplit("/", 1)[-1] or item.path


def print_static_summary(console: Console, result: StaticDemandResult) -> None:
    stats = result.stats
    projection = result.projection
    unique_paths = len(result.paths)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Unique paths", f"{unique_paths:,}")
    table.add_row(
        "Repeat requests",
        f"{result.repeat_records:,} ({_format_share(result.repeat_records, stats.total_records)})",
    )
    table.add_row(
        "Repeat bytes (est.)",
        f"{format_bytes(result.repeat_bytes)} ({_format_share(result.repeat_bytes, stats.total_bytes)})",
    )
    table.add_row(
        "Avg requests / day",
        f"{stats.total_records / stats.observed_days:,.0f}",
    )
    table.add_row(
        "Projected monthly requests",
        f"{projection.monthly_requests:,.0f}",
    )
    table.add_row(
        "Avg bytes / day",
        format_bytes(int(stats.total_bytes / stats.observed_days)),
    )
    table.add_row(
        "Projected monthly transfer",
        format_bytes(int(projection.monthly_bytes)),
    )

    console.print(
        Panel(
            table,
            title="[bold]Static demand summary[/bold]",
            subtitle=(
                f"Projected to a {projection.target_month_days:.0f}-day month "
                f"from {projection.observed_days:.1f} observed days. "
                f"{static_path_version_note()}"
            ),
            border_style="green",
        )
    )


def print_category_breakdown(
    console: Console,
    result: StaticDemandResult,
) -> None:
    stats = result.stats
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Category")
    table.add_column("Unique paths", justify="right")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")

    for item in sorted(result.categories, key=lambda row: -row.bytes):
        table.add_row(
            item.label,
            f"{item.unique_paths:,}",
            f"{item.records:,}",
            _format_share(item.records, stats.total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, stats.total_bytes),
        )

    console.print(
        Panel(
            table,
            title="[bold]Traffic by category[/bold]",
            subtitle=static_path_version_note(),
            border_style="green",
        )
    )


def print_daily_breakdown(console: Console, result: StaticDemandResult) -> None:
    stats = result.stats
    projection = result.projection
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Day")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")

    for item in result.daily:
        table.add_row(
            item.day.isoformat(),
            f"{item.records:,}",
            _format_share(item.records, stats.total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, stats.total_bytes),
        )

    avg_records = stats.total_records / stats.observed_days
    avg_bytes = stats.total_bytes / stats.observed_days
    table.add_row(
        "[bold]Daily avg[/bold]",
        f"[bold]{avg_records:,.0f}[/bold]",
        "—",
        f"[bold]{format_bytes(int(avg_bytes))}[/bold]",
        "—",
    )
    table.add_row(
        "[bold]Projected month[/bold]",
        f"[bold]{projection.monthly_requests:,.0f}[/bold]",
        "—",
        f"[bold]{format_bytes(int(projection.monthly_bytes))}[/bold]",
        "—",
    )

    console.print(
        Panel(
            table,
            title="[bold]Daily traffic[/bold]",
            border_style="green",
        )
    )


def print_top_extensions(
    console: Console,
    result: StaticDemandResult,
    *,
    top: int = 15,
) -> None:
    stats = result.stats
    rows = top_items(result.extensions, limit=top)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right")
    table.add_column("Extension")
    table.add_column("Unique paths", justify="right")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")

    for index, item in enumerate(rows, start=1):
        table.add_row(
            str(index),
            item.extension,
            f"{item.unique_paths:,}",
            f"{item.records:,}",
            _format_share(item.records, stats.total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, stats.total_bytes),
        )

    console.print(
        Panel(
            table,
            title=f"[bold]Top {top} extensions by bytes[/bold]",
            border_style="green",
        )
    )


def _print_top_paths_table(
    console: Console,
    *,
    title: str,
    rows: tuple[StaticPathDemand, ...],
    total_records: int,
    total_bytes: int,
) -> None:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right")
    table.add_column("File")
    table.add_column("Category")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")
    table.add_column("Bot rec.", justify="right")

    for index, item in enumerate(rows, start=1):
        table.add_row(
            str(index),
            _truncate(_display_path(item), limit=36),
            _truncate(category_label(item.category), limit=24),
            f"{item.records:,}",
            _format_share(item.records, total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, total_bytes),
            f"{item.bot_records:,}",
        )

    console.print(Panel(table, title=f"[bold]{title}[/bold]", border_style="green"))


def print_top_paths(
    console: Console,
    result: StaticDemandResult,
    *,
    top: int = 25,
) -> None:
    stats = result.stats
    by_bytes = top_items(result.paths, limit=top)
    by_records = top_items(sort_paths_by_records(result.paths), limit=top)

    _print_top_paths_table(
        console,
        title=f"Top {top} static files by bytes",
        rows=by_bytes,
        total_records=stats.total_records,
        total_bytes=stats.total_bytes,
    )
    _print_top_paths_table(
        console,
        title=f"Top {top} static files by requests",
        rows=by_records,
        total_records=stats.total_records,
        total_bytes=stats.total_bytes,
    )


def print_static_report(
    console: Console,
    file_path: Path,
    result: StaticDemandResult,
    *,
    top: int = 25,
) -> None:
    print_traffic_stats(console, file_path, result.stats)
    print_static_summary(console, result)
    print_category_breakdown(console, result)
    print_daily_breakdown(console, result)
    print_top_extensions(console, result, top=min(top, 15))
    print_top_paths(console, result, top=top)
