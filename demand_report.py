from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from abuse import top_items
from demand import FileDemand, FileDemandResult, display_filename
from report import _format_share, _truncate, format_bytes, print_traffic_stats


def print_file_demand_summary(
    console: Console,
    result: FileDemandResult,
    *,
    bitstreams_only: bool,
) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")

    table.add_row("Unique paths", f"{len(result.files):,}")
    if bitstreams_only:
        table.add_row("Bitstream downloads", f"{result.bitstream_records:,}")
    else:
        table.add_row("Bitstream downloads", f"{result.bitstream_records:,}")
        table.add_row("Other paths", f"{result.other_records:,}")

    console.print(
        Panel(
            table,
            title="[bold]File demand summary[/bold]",
            subtitle=(
                "DSpace bitstream URLs are normalized (handle vs short path)."
                if bitstreams_only
                else "All request paths; bitstreams are normalized when possible."
            ),
            border_style="green",
        )
    )


def print_top_files(
    console: Console,
    files: tuple[FileDemand, ...],
    *,
    total_records: int,
    total_bytes: int,
    top: int = 25,
) -> None:
    rows = top_items(files, limit=top)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right")
    table.add_column("Filename")
    table.add_column("Item", justify="right")
    table.add_column("Records", justify="right")
    table.add_column("% rec.", justify="right")
    table.add_column("Bytes", justify="right")
    table.add_column("% bytes", justify="right")
    table.add_column("IPs", justify="right")
    table.add_column("Bot rec.", justify="right")

    for index, item in enumerate(rows, start=1):
        table.add_row(
            str(index),
            _truncate(display_filename(item), limit=40),
            item.item_id or "—",
            f"{item.records:,}",
            _format_share(item.records, total_records),
            format_bytes(item.bytes),
            _format_share(item.bytes, total_bytes),
            str(item.unique_ips),
            f"{item.bot_records:,}",
        )

    console.print(
        Panel(
            table,
            title="[bold]Top demanded files[/bold]",
            subtitle=f"Top {len(rows)} files by bytes transferred.",
            border_style="blue",
        )
    )


def print_file_path_reference(
    console: Console,
    files: tuple[FileDemand, ...],
    *,
    top: int = 25,
) -> None:
    rows = top_items(files, limit=top)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", width=4)
    table.add_column("Filename", width=28)
    table.add_column("Path")

    for index, item in enumerate(rows, start=1):
        table.add_row(
            str(index),
            display_filename(item),
            item.path,
        )

    console.print(
        Panel(
            table,
            title="[bold]File paths (reference)[/bold]",
            subtitle="Full normalized paths for the ranked files above.",
            border_style="cyan",
        )
    )


def print_demand_report(
    console: Console,
    log_file: Path,
    result: FileDemandResult,
    *,
    bitstreams_only: bool,
    top: int,
) -> None:
    print_traffic_stats(console, log_file, result.stats)
    print_file_demand_summary(console, result, bitstreams_only=bitstreams_only)
    print_top_files(
        console,
        result.files,
        total_records=result.stats.total_records,
        total_bytes=result.stats.total_bytes,
        top=top,
    )
    print_file_path_reference(console, result.files, top=top)
