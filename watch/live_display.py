from __future__ import annotations

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table

from watch.aggregator import WatchSnapshot
from watch.blocking import BlockRecommendation


def _truncate(text: str, limit: int = 50) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _summary_table(snapshot: WatchSnapshot) -> Table:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")
    table.add_row("Window", f"{snapshot.window_seconds:.0f}s")
    table.add_row("Requests in window", f"{snapshot.total_requests:,}")
    table.add_row("Current RPS", f"{snapshot.current_rps:.2f}")
    if snapshot.window_start and snapshot.window_end:
        table.add_row("From", snapshot.window_start.strftime("%Y-%m-%d %H:%M:%S"))
        table.add_row("To", snapshot.window_end.strftime("%Y-%m-%d %H:%M:%S"))
    return table


def _actor_table(
    title: str,
    rows: tuple,
    *,
    show_ua: bool = False,
    show_bursts: bool = False,
) -> Panel:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Key")
    table.add_column("Req", justify="right")
    table.add_column("RPS", justify="right")
    if show_bursts:
        table.add_column("Burst", justify="right")
    if show_ua:
        table.add_column("Top UA")
    else:
        table.add_column("Kinds")

    for item in rows:
        kinds = ", ".join(f"{k}:{v}" for k, v in item.kinds.most_common(2))
        row = [
            _truncate(item.key, 36),
            f"{item.requests:,}",
            f"{item.rps:.2f}",
        ]
        if show_bursts:
            row.append(f"{item.max_burst_rps:.1f}")
        row.append(_truncate(item.top_user_agent if show_ua else kinds, 40))
        table.add_row(*row)

    return Panel(table, title=title, border_style="blue")


def _country_table(snapshot: WatchSnapshot) -> Panel:
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Country")
    table.add_column("Code")
    table.add_column("Req", justify="right")
    table.add_column("RPS", justify="right")
    table.add_column("IPs", justify="right")

    for item in snapshot.countries:
        table.add_row(
            item.country_name,
            item.country_code,
            f"{item.requests:,}",
            f"{item.rps:.2f}",
            f"{len(item.unique_ips):,}",
        )

    return Panel(table, title="[bold]Traffic by country[/bold]", border_style="magenta")


def _blocks_table(blocks: tuple[BlockRecommendation, ...]) -> Panel:
    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("Type")
    table.add_column("Target")
    table.add_column("RPS", justify="right")
    table.add_column("Req", justify="right")
    table.add_column("Reason")
    table.add_column("Detail")

    for item in blocks[:15]:
        table.add_row(
            item.block_type,
            item.target,
            f"{item.rps:.2f}",
            f"{item.requests:,}",
            item.reason,
            _truncate(item.detail, 45),
        )

    subtitle = (
        "Country blocks: CloudFront geo restriction or WAF. "
        "country_cidr: official GeoLite2 ranges for firewall/ipset. "
        "subnet/IP: observed traffic from logs."
    )
    return Panel(
        table,
        title="[bold]Suggested blocks[/bold]",
        subtitle=subtitle,
        border_style="yellow",
    )


def build_layout(
    snapshot: WatchSnapshot,
    blocks: tuple[BlockRecommendation, ...],
) -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="summary", size=7),
        Layout(name="blocks", size=12),
        Layout(name="main"),
    )
    layout["main"].split_row(
        Layout(name="countries"),
        Layout(name="actors"),
    )
    layout["actors"].split_column(
        Layout(name="ips"),
        Layout(name="user_agents"),
    )

    layout["summary"].update(
        Panel(
            _summary_table(snapshot),
            title="[bold]Live monitor[/bold]",
            border_style="green",
        )
    )
    layout["blocks"].update(_blocks_table(blocks))
    layout["countries"].update(_country_table(snapshot))
    layout["ips"].update(_actor_table("Top IPs", snapshot.ips, show_bursts=True))
    layout["user_agents"].update(
        _actor_table("Top user-agents", snapshot.user_agents, show_ua=True)
    )
    return layout


def render_snapshot(
    console: Console,
    snapshot: WatchSnapshot,
    blocks: tuple[BlockRecommendation, ...],
) -> None:
    console.print(build_layout(snapshot, blocks))


class LiveMonitor:
    def __init__(self, console: Console, *, refresh_per_second: float = 2.0) -> None:
        self.console = console
        self.refresh_per_second = refresh_per_second
        self._live: Live | None = None
        self._snapshot = WatchSnapshot(
            window_seconds=0,
            total_requests=0,
            current_rps=0.0,
            window_start=None,
            window_end=None,
            ips=(),
            subnets=(),
            countries=(),
            user_agents=(),
        )
        self._blocks: tuple[BlockRecommendation, ...] = ()

    def update(
        self,
        snapshot: WatchSnapshot,
        blocks: tuple[BlockRecommendation, ...],
    ) -> None:
        self._snapshot = snapshot
        self._blocks = blocks
        if self._live is not None:
            self._live.update(build_layout(snapshot, blocks))

    def __enter__(self) -> LiveMonitor:
        self._live = Live(
            build_layout(self._snapshot, self._blocks),
            console=self.console,
            refresh_per_second=self.refresh_per_second,
            screen=True,
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        if self._live is not None:
            self._live.__exit__(*args)
